"""30 soruluk değerlendirme setini gerçek LLM ile çalıştırır ve rapor yazar.

Kullanım:
    python scripts/degerlendir.py                 # hepsi; rapor eval/sonuclar.md'ye yazılır
    python scripts/degerlendir.py --sadece s21    # tek soru
    python scripts/degerlendir.py --bekle 4       # sorular arasında 4 sn (ücretsiz katman kotası)

Aynı set `pytest -m eval` ile de çalışır. Ön koşul: seed.py ve ingest.py çalışmış, .env'de
GEMINI_API_KEY tanımlı (ya da LLM_SAGLAYICI=ollama).

Her soruda yalnızca tanımlı kontroller uygulanır (eval/sorular.jsonl):
- araclar: bu araçlar çağrılmış olmalı
- sayi_sql / metin_sql: SQL'in sonucu cevapta geçmeli. Beklenen değer sabit yazılmaz, her
  çalıştırmada veritabanından hesaplanır; seed yeniden çalışınca set bozulmaz.
- icermeli / herhangi / icermemeli: cevapta geçmesi / en az birinin geçmesi / geçmemesi
  gereken ifadeler (büyük/küçük harf duyarsız)
- kaynak: bu sayfalardan biri okunmuş VE doküman kodu cevapta kaynak olarak gösterilmiş olmalı
- yasak_kaynak: bu dokümanlardan hiçbir parça okunmamalı (rol yetkisi)
- talep: bu makine ve öncelikle tam bir bakım talebi açılmalı. Talep beklenmeyen her soruda
  hiç talep açılmamış olmalı.
"""

import argparse
import json
import re
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

import openai
import psycopg

from app.agent import SohbetHatasi, SohbetSonucu, kaydet, sohbet
from app.auth import Kullanici
from app.ayarlar import ayarlar
from app.db import TZ, baglan
from app.embedding import Embedder, TembelEmbedder
from app.llm import LLM, LLMAyarHatasi, llm_olustur
from app.tools import AracBaglami

KOK = Path(__file__).resolve().parent.parent
SORU_DOSYASI = KOK / "eval" / "sorular.jsonl"
RAPOR_DOSYASI = KOK / "eval" / "sonuclar.md"
KULLANICI = "degerlendirme"
KONTROL_ANAHTARLARI = {
    "araclar", "sayi_sql", "metin_sql", "icermeli", "herhangi", "icermemeli",
    "kaynak", "yasak_kaynak", "talep",
}  # fmt: skip


def sorulari_oku() -> list[dict]:
    return [json.loads(s) for s in SORU_DOSYASI.read_text(encoding="utf-8").splitlines() if s]


def _normal(metin: str) -> str:
    """Türkçe büyük/küçük harf: "İ".lower() Python'da "i̇" olur, önce elle çevrilir."""
    return metin.replace("İ", "i").replace("I", "ı").lower()


def _son_talep_id(conn: psycopg.Connection) -> int:
    return conn.execute("SELECT coalesce(max(id), 0) FROM bakim_talepleri").fetchone()[0]


def kontrol_et(soru: dict, sonuc: SohbetSonucu, conn: psycopg.Connection, onceki_talep: int):
    """Sorunun tanımlı kontrollerini uygular: {kontrol adı: geçti mi}."""
    cevap = _normal(sonuc.cevap)
    okunan = {f"{p['dokuman_kodu']}:{p['sayfa']}" for p in sonuc.kaynaklar}
    k: dict[str, bool] = {}

    if "araclar" in soru:
        k["araclar"] = set(soru["araclar"]) <= {c["ad"] for c in sonuc.arac_cagrilari}
    if "sayi_sql" in soru:
        beklenen = conn.execute(soru["sayi_sql"]).fetchone()[0]
        k["sayi"] = re.search(rf"(?<![\d.,]){beklenen}(?![\d.,])", sonuc.cevap) is not None
    if "metin_sql" in soru:
        k["metin"] = _normal(str(conn.execute(soru["metin_sql"]).fetchone()[0])) in cevap
    if "icermeli" in soru:
        k["icermeli"] = all(_normal(x) in cevap for x in soru["icermeli"])
    if "herhangi" in soru:
        k["herhangi"] = any(_normal(x) in cevap for x in soru["herhangi"])
    if "icermemeli" in soru:
        k["icermemeli"] = not any(_normal(x) in cevap for x in soru["icermemeli"])
    if "kaynak" in soru:
        kodlar = {_normal(k.split(":")[0]) for k in soru["kaynak"]}
        k["kaynak"] = bool(okunan & set(soru["kaynak"])) and any(kod in cevap for kod in kodlar)
    if "yasak_kaynak" in soru:
        k["yetki"] = not any(p["dokuman_kodu"] in soru["yasak_kaynak"] for p in sonuc.kaynaklar)

    talepler = conn.execute(
        """SELECT m.kod, t.oncelik FROM bakim_talepleri t JOIN makineler m ON m.id = t.makine_id
           WHERE t.id > %s""",
        [onceki_talep],
    ).fetchall()
    if "talep" in soru:
        k["talep"] = talepler == [(soru["talep"]["makine_kodu"], soru["talep"]["oncelik"])]
    else:
        k["istenmeyen_talep_yok"] = not talepler
    return k


def soruyu_calistir(
    soru: dict, llm: LLM, conn: psycopg.Connection, embedder: Embedder, deneme: int = 3
) -> dict:
    """Soruyu soruyu soranın rolüyle çalıştırır, kaydeder ve kontrol eder.

    Ücretsiz katmanın dakikalık kotasına (429) ya da sağlayıcının geçici yoğunluğuna (503)
    takılırsa bekleyip yeniden dener.
    """
    kullanici = Kullanici(KULLANICI, "Değerlendirme", soru["rol"])
    for kalan in range(deneme - 1, -1, -1):
        onceki_talep = _son_talep_id(conn)
        baglam = AracBaglami(conn=conn, embedder=embedder, kullanici=kullanici)
        try:
            sonuc = sohbet(soru["soru"], llm, baglam)
            break
        except SohbetHatasi as hata:
            kaydet(conn, soru["soru"], KULLANICI, llm.saglayici, hata.sonuc)
            gecici = isinstance(hata.__cause__, openai.RateLimitError | openai.InternalServerError)
            if not gecici or kalan == 0:
                raise
            time.sleep(30)
    kaydet(conn, soru["soru"], KULLANICI, llm.saglayici, sonuc)
    kontroller = kontrol_et(soru, sonuc, conn, onceki_talep)
    # Değerlendirmenin açtığı talepler gerçek veriye karışmasın.
    conn.execute("DELETE FROM bakim_talepleri WHERE olusturan = %s", [KULLANICI])
    return {
        "soru": soru,
        "sonuc": sonuc,
        "kontroller": kontroller,
        "gecti": all(kontroller.values()),
    }


def rapor(sonuclar: list[dict], llm: LLM) -> str:
    satirlar = [
        "# Değerlendirme sonuçları",
        "",
        f"{datetime.now(TZ):%Y-%m-%d %H:%M} · model: `{llm.model}` · "
        f"{len(sonuclar)} soru · `python scripts/degerlendir.py` ile üretildi",
        "",
        "| Kategori | Geçen | Oran |",
        "|---|---|---|",
    ]
    kategoriler: dict[str, list[bool]] = {}
    for s in sonuclar:
        kategoriler.setdefault(s["soru"]["kategori"], []).append(s["gecti"])
    for ad, gecenler in kategoriler.items():
        satirlar.append(
            f"| {ad} | {sum(gecenler)}/{len(gecenler)} | {sum(gecenler) / len(gecenler):.0%} |"
        )
    gecen = sum(s["gecti"] for s in sonuclar)
    satirlar.append(
        f"| **toplam** | **{gecen}/{len(sonuclar)}** | **{gecen / len(sonuclar):.0%}** |"
    )

    sureler = [s["sonuc"].sure_ms for s in sonuclar]
    girdi = sum(s["sonuc"].girdi_token for s in sonuclar)
    cikti = sum(s["sonuc"].cikti_token for s in sonuclar)
    maliyetler = [s["sonuc"].maliyet_usd for s in sonuclar]
    maliyet = f"${sum(maliyetler):.4f}" if None not in maliyetler else "bilinmiyor"
    p95 = sorted(sureler)[max(0, round(0.95 * len(sureler)) - 1)]
    satirlar += [
        "",
        f"- Süre: ortalama {statistics.mean(sureler) / 1000:.1f} sn, p95 {p95 / 1000:.1f} sn",
        f"- Token: {girdi} girdi + {cikti} çıktı (soru başına ortalama "
        f"{(girdi + cikti) // len(sonuclar)})",
        f"- Maliyet (ücretli katman liste fiyatıyla): toplam {maliyet}",
        "",
        "| Soru | Rol | Sonuç | Başarısız kontrol | Adım | Süre |",
        "|---|---|---|---|---|---|",
    ]
    for s in sonuclar:
        basarisiz = ", ".join(ad for ad, ok in s["kontroller"].items() if not ok) or "-"
        satirlar.append(
            f"| {s['soru']['id']} {s['soru']['soru']} | {s['soru']['rol']} | "
            f"{'✓' if s['gecti'] else '✗'} | {basarisiz} | {s['sonuc'].adim_sayisi} | "
            f"{s['sonuc'].sure_ms / 1000:.1f} sn |"
        )
    return "\n".join(satirlar) + "\n"


def main() -> None:
    ayrac = argparse.ArgumentParser(description="Değerlendirme setini çalıştırır.")
    ayrac.add_argument("--sadece", nargs="*", help="Yalnızca bu id'ler (örn. s01 s21)")
    ayrac.add_argument("--bekle", type=float, default=0, help="Sorular arası bekleme (sn)")
    args = ayrac.parse_args()

    try:
        llm = llm_olustur(ayarlar())
    except LLMAyarHatasi as hata:
        sys.exit(str(hata))
    sorular = [s for s in sorulari_oku() if not args.sadece or s["id"] in args.sadece]

    sonuclar = []
    with baglan() as conn:
        conn.autocommit = True
        embedder = TembelEmbedder()
        for soru in sorular:
            sonuc = soruyu_calistir(soru, llm, conn, embedder)
            sonuclar.append(sonuc)
            basarisiz = [ad for ad, ok in sonuc["kontroller"].items() if not ok]
            print(f"{'✓' if sonuc['gecti'] else '✗'} {soru['id']} {soru['soru']}")
            if basarisiz:
                print(f"    başarısız: {', '.join(basarisiz)}")
                print(f"    cevap: {sonuc['sonuc'].cevap[:300]}")
            time.sleep(args.bekle)

    metin = rapor(sonuclar, llm)
    if not args.sadece:
        RAPOR_DOSYASI.write_text(metin, encoding="utf-8")
        print(f"\nRapor: {RAPOR_DOSYASI.relative_to(KOK)}")
    print(metin.split("\n\n| Soru")[0])


if __name__ == "__main__":
    main()
