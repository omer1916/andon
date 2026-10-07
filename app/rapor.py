"""Vardiya sonu raporu.

Raporun bütün sayıları kodda hesaplanır. LLM yalnızca bu sayılara dayanan kısa bir yorum yazar
(özet, dikkat edilecekler, öneriler) ve yorum iki denetimden geçer:

1. Biçim: yanıt RaporYorumu modeline uyan bir JSON olmalı.
2. Sayı denetimi: yorumdaki her sayı, LLM'e verilen verilerde geçmeli. Model "8 puan düştü"
   gibi kendi hesapladığı ya da uydurduğu bir sayı yazarsa yorum reddedilir.

Denetimden geçmeyen yanıt, sorun söylenerek bir kez daha istenir. İkinci yanıt da geçmezse,
LLM'e ulaşılamazsa ya da LLM ayarlı değilse yorumu kurallar yazar; rapor her durumda çıkar.
"""

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

import psycopg
from pydantic import ValidationError

from app import agent, sorgular
from app.db import TZ
from app.llm import LLM, maliyet_hesapla
from app.models import VARDIYA_SAATLERI, VARDIYA_SURESI, RaporYorumu
from app.tools import DURUS_ADLARI, yuzde

MAKS_DENEME = 2
DUSUK_OEE = 0.65  # andon panelindeki kırmızı eşik

SISTEM_ISTEMI = """\
Bir fabrikanın vardiya sonu raporunun yorum kısmını yazıyorsun. Okuyan kişi bir sonraki
vardiyanın sorumlusu; kısa ve somut yaz.

Yalnızca kullanıcının verdiği JSON'daki bilgileri kullan:
- Yeni sayı üretme ve hesap yapma (fark, toplam, ortalama yok). Yazdığın her sayı JSON'da
  aynen geçmeli. Sayıları Türkçe yaz: %63,8 ve 4.237 dk.
- JSON'da olmayan bir neden ya da durum uydurma. Öneriler verilerden çıkmalı.
- OEE'si %65'in altındaki hatları, vardiya sonunda süren arızaları ve kritik stoğu öne çıkar.

Yanıtın yalnızca şu biçimde bir JSON nesnesi olsun, öncesinde ya da sonrasında metin olmasın:
{"ozet": "2-3 cümle", "dikkat": ["en fazla 4 madde"], "oneriler": ["en fazla 4 madde"]}
"""


def vardiya_numarasi(baslangic: datetime) -> int:
    saat = baslangic.astimezone(TZ).hour
    return next(no for no, s in VARDIYA_SAATLERI.items() if s == saat)


def rapor_verisi(conn: psycopg.Connection, baslangic: datetime) -> dict:
    """Raporun sayısal kısmı: OEE, duruşlar, arızalar, açık talepler, kritik stok."""
    bitis = baslangic + VARDIYA_SURESI
    gun = baslangic.astimezone(TZ).date()
    (fabrika,) = sorgular.oee_hesapla(conn, vardiya_baslangici=baslangic)
    son_7_gun = {
        h["hat"]: h["oee"]
        for h in sorgular.oee_hesapla(
            conn, baslangic=gun - timedelta(days=7), bitis=gun - timedelta(days=1), grup="hat"
        )
    }
    hatlar = [
        {**h, "son_7_gun_oee": son_7_gun.get(h["hat"])}
        for h in sorgular.oee_hesapla(conn, vardiya_baslangici=baslangic, grup="hat")
    ]
    hatlar.sort(key=lambda h: (h["oee"] is None, h["oee"] or 0))

    arizalar = sorgular.araliktaki_arizalar(conn, baslangic, bitis)
    for ariza in arizalar:
        ariza["vardiya_sonunda_suruyor"] = ariza["bitis"] is None or ariza["bitis"] > bitis
        if ariza["vardiya_sonunda_suruyor"]:
            ariza["sure_dk"] = None
        del ariza["bitis"]

    talep_sayisi, talepler = sorgular.acik_talepler(conn)
    kritik_stok = [
        {k: p[k] for k in ("parca_kodu", "ad", "miktar", "min_miktar", "birim")}
        for p in sorgular.stok_getir(conn, sadece_kritik=True)
    ]
    return {
        "tarih": gun,
        "vardiya": vardiya_numarasi(baslangic),
        "baslangic": baslangic,
        "bitis": bitis,
        "fabrika": fabrika,
        "hatlar": hatlar,
        "duruslar": sorgular.vardiya_duruslari_getir(conn, baslangic),
        "arizalar": arizalar,
        "acik_talep_sayisi": talep_sayisi,
        "acik_talepler": talepler,
        "kritik_stok": kritik_stok,
    }


def durus_adi(durus: dict) -> str:
    return DURUS_ADLARI.get(durus["neden"]) or f"arıza ({durus['ariza_tipi']})"


def _saat_araligi(vardiya: int) -> str:
    saat = VARDIYA_SAATLERI[vardiya]
    return f"{saat:02d}:00-{(saat + 8) % 24:02d}:00"


def _oranlar(d: dict) -> dict:
    return {
        "oee": yuzde(d["oee"]),
        "kullanilabilirlik": yuzde(d["kullanilabilirlik"]),
        "performans": yuzde(d["performans"]),
        "kalite": yuzde(d["kalite"]),
        "durus_dk": d["durus_dk"],
        "toplam_adet": d["toplam_adet"],
        "hurda_adet": d["hurda_adet"],
    }


def llm_verisi(v: dict) -> dict:
    """LLM'e giden veri: yüzdeler hazır, adlar okunur, gereksiz alan yok (token)."""
    return {
        "vardiya": f"{v['tarih']:%d.%m.%Y}, {v['vardiya']}. vardiya "
        f"({_saat_araligi(v['vardiya'])})",
        # Sistem istemi "%65'in altındaki hatları öne çıkar" der; eşik veride olmazsa model
        # "%65'in altında" yazınca sayı denetimi doğru cümleyi uydurma sayar (arayüzde görüldü).
        "dusuk_oee_esigi_yuzde": yuzde(DUSUK_OEE),
        "fabrika_yuzde": _oranlar(v["fabrika"]),
        "hatlar_yuzde": [
            {"hat": h["hat"], **_oranlar(h), "son_7_gun_oee": yuzde(h["son_7_gun_oee"])}
            for h in v["hatlar"]
        ],
        "en_uzun_duruslar": [
            {
                "hat": d["hat"],
                "neden": durus_adi(d),
                "makine": d["makine_kodu"],
                "sure_dk": d["sure_dk"],
            }
            for d in v["duruslar"]
        ],
        # Sayımlar açıkça verilir: model (ya da kural yorumu) "3 arıza başladı" yazdığında
        # sayı denetimi bunu başka bir alanda tesadüfen geçen bir 3'e değil, buraya dayandırır.
        "vardiyada_baslayan_ariza_sayisi": len(v["arizalar"]),
        "hatti_durduran_ariza_sayisi": sum(a["hat_durdu"] for a in v["arizalar"]),
        "vardiyada_baslayan_arizalar": [
            {
                "makine": a["makine_kodu"],
                "hat": a["hat"],
                "tip": a["ariza_tipi"],
                "onem": a["onem"],
                "hatti_durdurdu": a["hat_durdu"],
                "sure_dk": a["sure_dk"],
                "vardiya_sonunda_suruyor": a["vardiya_sonunda_suruyor"],
                "aciklama": a["aciklama"],
            }
            for a in v["arizalar"]
        ],
        "acik_bakim_talebi_sayisi": v["acik_talep_sayisi"],
        "oncelikli_acik_talepler": [
            {"makine": t["makine_kodu"], "oncelik": t["oncelik"], "aciklama": t["aciklama"]}
            for t in v["acik_talepler"][:3]
        ],
        "minimum_seviyenin_altindaki_parcalar": [
            {
                "parca": f"{p['parca_kodu']} {p['ad']}",
                "miktar": p["miktar"],
                "minimum": p["min_miktar"],
                "birim": p["birim"],
            }
            for p in v["kritik_stok"]
        ],
    }


# --- Sayı denetimi ----------------------------------------------------------------------

_SAYI = re.compile(r"\d+(?:[.,]\d+)*")


def _okumalar(yazim: str) -> set[float]:
    """Bir sayı yazımının olası değerleri. Türkçe okuma: "4.237" = 4237, "63,8" = 63,8.
    İngilizce okuma: "4.237" = 4,237, "1,234" = 1234. İkisinden biri tutması yeterli."""
    degerler = set()
    for metin in (yazim.replace(".", "").replace(",", "."), yazim.replace(",", "")):
        try:
            degerler.add(round(float(metin), 3))
        except ValueError:
            pass  # "29.09.2026" İngilizce okunamaz
    return degerler


def izinli_sayilar(veri: dict) -> set[float]:
    """Verilerde geçen bütün sayılar. Tarih gibi iki ve daha çok ayırıcılı yazımların
    ("29.09.2026") parçaları da ayrıca eklenir; model "29 Eylül" yazabilsin. Tek ayırıcılı
    yazım ("63.8") parçalanmaz: parçalansaydı uydurulmuş bir "8 puan" denetimden geçerdi."""
    izinli: set[float] = set()
    for yazim in _SAYI.findall(json.dumps(veri, ensure_ascii=False, default=str)):
        izinli |= _okumalar(yazim)
        parcalar = re.split(r"[.,]", yazim)
        if len(parcalar) > 2:
            izinli |= {float(parca) for parca in parcalar}
    return izinli


def uydurulmus_sayilar(yorum: RaporYorumu, izinli: set[float]) -> list[str]:
    """Yorumda geçen ama verilerde olmayan sayılar."""
    metin = " ".join([yorum.ozet, *yorum.dikkat, *yorum.oneriler])
    return [yazim for yazim in _SAYI.findall(metin) if not _okumalar(yazim) & izinli]


def _denetle(metin: str | None, izinli: set[float]) -> tuple[RaporYorumu | None, str | None]:
    """(yorum, None) ya da (None, LLM'e geri söylenecek sorun)."""
    eslesme = re.search(r"\{.*\}", metin or "", re.DOTALL)
    if eslesme is None:
        return None, "Yanıtta JSON nesnesi yok."
    try:
        yorum = RaporYorumu.model_validate_json(eslesme.group())
    except ValidationError as hata:
        alanlar = ", ".join(
            sorted({str(e["loc"][0]) if e["loc"] else "json" for e in hata.errors()})
        )
        return None, f"JSON istenen biçimde değil (sorunlu alanlar: {alanlar})."
    uydurma = uydurulmus_sayilar(yorum, izinli)
    if uydurma:
        return None, f"Verilerde olmayan sayılar var: {', '.join(uydurma)}."
    return yorum, None


# --- Yorum ------------------------------------------------------------------------------


@dataclass
class YorumSonucu:
    yorum: RaporYorumu | None = None
    deneme_sayisi: int = 0
    girdi_token: int = 0
    cikti_token: int = 0
    notu: str | None = None  # kullanıcıya gösterilir
    hata: str | None = None  # llm_istekleri kaydına yazılır


def llm_yorumu(llm: LLM, veri: dict) -> YorumSonucu:
    izinli = izinli_sayilar(veri)
    mesajlar: list[dict] = [
        {"role": "system", "content": SISTEM_ISTEMI},
        {"role": "user", "content": json.dumps(veri, ensure_ascii=False, default=str)},
    ]
    sonuc = YorumSonucu()
    sorunlar: list[str] = []
    for _ in range(MAKS_DENEME):
        try:
            yanit = llm.tamamla(mesajlar, [])
        except Exception as hata:  # kota, ağ, sağlayıcı hatası: rapor yine de çıkmalı
            sonuc.hata = f"{type(hata).__name__}: {hata}"
            sonuc.notu = "LLM'e ulaşılamadı; yorum kurallarla yazıldı."
            return sonuc
        sonuc.deneme_sayisi += 1
        sonuc.girdi_token += yanit.girdi_token
        sonuc.cikti_token += yanit.cikti_token

        yorum, sorun = _denetle(yanit.metin, izinli)
        if yorum is not None:
            sonuc.yorum = yorum
            if sorunlar:
                sonuc.notu = f"İlk yanıt denetimde reddedildi ({sorunlar[0]}) ve düzeltildi."
            return sonuc
        sorunlar.append(sorun)
        mesajlar += [
            yanit.mesaj,
            {
                "role": "user",
                "content": f"{sorun} Yanıtı yalnızca verilerdeki sayıları kullanarak, istenen "
                "JSON biçiminde yeniden yaz.",
            },
        ]
    sonuc.notu = f"LLM'in yanıtı denetimden geçmedi ({sorunlar[-1]}); yorum kurallarla yazıldı."
    sonuc.hata = "; ".join(sorunlar)
    return sonuc


def yuzde_metni(oran: float | None) -> str:
    return "–" if oran is None else f"%{oran * 100:.1f}".replace(".", ",")


def _dk_metni(dakika: int) -> str:
    return f"{dakika:,} dk".replace(",", ".")


def kural_yorumu(v: dict) -> RaporYorumu:
    """LLM kullanılamadığında aynı verilerden kurallarla yazılan yorum."""
    cumleler = [f"Vardiyada fabrika OEE'si {yuzde_metni(v['fabrika']['oee'])}."]
    if v["hatlar"]:
        en_dusuk = v["hatlar"][0]
        cumleler.append(f"En düşük hat {en_dusuk['hat']} ({yuzde_metni(en_dusuk['oee'])}).")
    if v["duruslar"]:
        d = v["duruslar"][0]
        cumleler.append(
            f"En uzun duruş {d['hat']} hattında, {durus_adi(d)}: {_dk_metni(d['sure_dk'])}."
        )
    if v["arizalar"]:
        durduran = sum(a["hat_durdu"] for a in v["arizalar"])
        cumleler.append(
            f"Vardiyada {len(v['arizalar'])} arıza başladı, {durduran} tanesi hattı durdurdu."
        )
    else:
        cumleler.append("Vardiyada yeni arıza başlamadı.")

    dikkat = []
    for h in v["hatlar"]:
        if h["oee"] is not None and h["oee"] < DUSUK_OEE:
            yedi_gun = h["son_7_gun_oee"]
            ek = f" (son 7 gün {yuzde_metni(yedi_gun)})" if yedi_gun is not None else ""
            dikkat.append(f"{h['hat']}: OEE {yuzde_metni(h['oee'])}{ek}.")
    for a in v["arizalar"]:
        if a["vardiya_sonunda_suruyor"]:
            dikkat.append(
                f"{a['makine_kodu']} ({a['hat']}) {a['ariza_tipi']} arızası vardiya sonunda "
                "sürüyordu."
            )
    if v["kritik_stok"]:
        kodlar = ", ".join(p["parca_kodu"] for p in v["kritik_stok"])
        dikkat.append(f"Minimum seviyenin altındaki parçalar: {kodlar}.")

    oneriler = []
    nedenler = {d["neden"] for d in v["duruslar"]}
    if "urun_degisimi" in nedenler:
        oneriler.append(
            "Ürün değişimi sürelerini kısaltmak için hızlı kalıp değişimi (SMED) çalışmasını "
            "gündeme alın."
        )
    makineler = list(dict.fromkeys(d["makine_kodu"] for d in v["duruslar"] if d["makine_kodu"]))
    if makineler:
        oneriler.append(
            f"Hattı durduran arızaların görüldüğü makineler ({', '.join(makineler[:3])}) için "
            "açık bakım talebi olup olmadığını kontrol edin."
        )
    if "malzeme_bekleme" in nedenler:
        oneriler.append("Malzeme beklemesi olan hatlarda hat yanı stok seviyesini kontrol edin.")
    if v["kritik_stok"]:
        oneriler.append("Minimum seviyenin altındaki parçalar için sipariş açın.")
    return RaporYorumu(ozet=" ".join(cumleler), dikkat=dikkat[:5], oneriler=oneriler[:5])


# --- Rapor ------------------------------------------------------------------------------


def markdown(r: dict) -> str:
    """Kopyalanıp e-postaya ya da mesaja yapıştırılabilecek rapor."""
    f = r["fabrika"]
    satirlar = [
        f"# Vardiya raporu: {r['tarih']:%d.%m.%Y}, {r['vardiya']}. vardiya "
        f"({_saat_araligi(r['vardiya'])})",
        "",
        f"**Fabrika OEE: {yuzde_metni(f['oee'])}** (kullanılabilirlik "
        f"{yuzde_metni(f['kullanilabilirlik'])}, performans {yuzde_metni(f['performans'])}, "
        f"kalite {yuzde_metni(f['kalite'])})",
        "",
        "## Özet",
        "",
        r["yorum"]["ozet"],
    ]
    for baslik, maddeler in (
        ("Dikkat", r["yorum"]["dikkat"]),
        ("Öneriler", r["yorum"]["oneriler"]),
    ):
        if maddeler:
            satirlar += ["", f"### {baslik}", "", *[f"- {m}" for m in maddeler]]

    satirlar += ["", "## Hatlar", "", "| Hat | OEE | Kull. | Perf. | Kalite | Duruş | Son 7 gün |"]
    satirlar.append("|---|---|---|---|---|---|---|")
    for h in r["hatlar"]:
        satirlar.append(
            f"| {h['hat']} | {yuzde_metni(h['oee'])} | {yuzde_metni(h['kullanilabilirlik'])} "
            f"| {yuzde_metni(h['performans'])} | {yuzde_metni(h['kalite'])} "
            f"| {_dk_metni(h['durus_dk'])} | {yuzde_metni(h['son_7_gun_oee'])} |"
        )

    if r["duruslar"]:
        satirlar += ["", "## En uzun duruşlar", ""]
        for d in r["duruslar"]:
            makine = f" ({d['makine_kodu']})" if d["makine_kodu"] else ""
            satirlar.append(f"- {d['hat']}: {durus_adi(d)}{makine}, {_dk_metni(d['sure_dk'])}")

    satirlar += ["", "## Vardiyada başlayan arızalar", ""]
    for a in r["arizalar"]:
        sure = "sürüyor" if a["vardiya_sonunda_suruyor"] else _dk_metni(a["sure_dk"])
        durdu = ", hattı durdurdu" if a["hat_durdu"] else ""
        satirlar.append(
            f"- {a['baslangic'].astimezone(TZ):%H:%M} {a['makine_kodu']} ({a['hat']}): "
            f"{a['ariza_tipi']}, {a['onem']} önem{durdu}, {sure}. {a['aciklama']}"
        )
    if not r["arizalar"]:
        satirlar.append("- Yok")

    satirlar += ["", f"## Açık bakım talepleri ({r['acik_talep_sayisi']})", ""]
    for t in r["acik_talepler"]:
        satirlar.append(f"- #{t['id']} {t['makine_kodu']}, {t['oncelik']}: {t['aciklama']}")
    if r["kritik_stok"]:
        satirlar += ["", "## Minimum seviyenin altındaki parçalar", ""]
        for p in r["kritik_stok"]:
            satirlar.append(
                f"- {p['parca_kodu']} {p['ad']}: {p['miktar']} / {p['min_miktar']} {p['birim']}"
            )

    kaynak = (
        f"LLM ({r['kullanim']['model']}), sayı denetiminden geçti"
        if r["yorum_kaynagi"] == "llm"
        else "kurallarla yazıldı"
    )
    satirlar += ["", f"_Yorum: {kaynak}. Sayılar veritabanından hesaplandı._"]
    return "\n".join(satirlar) + "\n"


def rapor_olustur(
    conn: psycopg.Connection, llm: LLM | None, vardiya_baslangici: datetime
) -> tuple[dict, YorumSonucu]:
    baslangic = time.perf_counter()
    r = rapor_verisi(conn, vardiya_baslangici)
    if llm is None:
        yorum_sonucu = YorumSonucu(notu="LLM ayarlı değil; yorum kurallarla yazıldı.")
    else:
        yorum_sonucu = llm_yorumu(llm, llm_verisi(r))

    yorum = yorum_sonucu.yorum or kural_yorumu(r)
    llm_kullanildi = llm is not None and yorum_sonucu.deneme_sayisi > 0
    r.update(
        yorum=yorum.model_dump(),
        yorum_kaynagi="llm" if yorum_sonucu.yorum else "kural",
        yorum_notu=yorum_sonucu.notu,
        kullanim={
            "model": llm.model if llm_kullanildi else None,
            "deneme_sayisi": yorum_sonucu.deneme_sayisi,
            "girdi_token": yorum_sonucu.girdi_token,
            "cikti_token": yorum_sonucu.cikti_token,
            "maliyet_usd": maliyet_hesapla(
                llm.saglayici, llm.model, yorum_sonucu.girdi_token, yorum_sonucu.cikti_token
            )
            if llm_kullanildi
            else None,
            "sure_ms": 0,
        },
    )
    r["markdown"] = markdown(r)
    r["kullanim"]["sure_ms"] = round((time.perf_counter() - baslangic) * 1000)
    return r, yorum_sonucu


def kaydet(
    conn: psycopg.Connection,
    kullanici: str,
    llm: LLM | None,
    r: dict,
    yorum_sonucu: YorumSonucu,
) -> None:
    """LLM'e istek atıldıysa (başarısız da olsa) llm_istekleri tablosuna yazar; /kullanim
    özetindeki token ve maliyete raporlar da girer."""
    if llm is None or (yorum_sonucu.deneme_sayisi == 0 and yorum_sonucu.hata is None):
        return
    agent.kaydet(
        conn,
        f"Vardiya raporu: {r['tarih']}, {r['vardiya']}. vardiya",
        kullanici,
        llm.saglayici,
        agent.SohbetSonucu(
            cevap=r["yorum"]["ozet"] if r["yorum_kaynagi"] == "llm" else "",
            kaynaklar=[],
            arac_cagrilari=[],
            adim_sayisi=yorum_sonucu.deneme_sayisi,
            girdi_token=yorum_sonucu.girdi_token,
            cikti_token=yorum_sonucu.cikti_token,
            sure_ms=r["kullanim"]["sure_ms"],
            maliyet_usd=r["kullanim"]["maliyet_usd"],
            model=llm.model,
            hata=yorum_sonucu.hata,
        ),
    )
