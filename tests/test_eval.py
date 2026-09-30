"""Değerlendirme seti.

İki bölüm var:
- Setin kendisinin tutarlılığı (her zaman çalışır): soru sayısı, alanlar, SQL'lerin geçerliliği.
- Gerçek LLM ile uçtan uca değerlendirme (`pytest -m eval`): her soru bir test. Ana veritabanını
  (seed + ingest edilmiş) ve .env'deki LLM'i kullanır; anahtar yoksa atlanır.
"""

import re
from datetime import datetime, timedelta

import psycopg
import pytest

from app.ayarlar import ayarlar
from app.db import TZ, baglan
from app.embedding import TembelEmbedder
from app.llm import llm_olustur
from scripts.degerlendir import KONTROL_ANAHTARLARI, sorulari_oku, soruyu_calistir
from scripts.ingest import kilavuzlari_oku
from tests.conftest import SahteEmbedder
from tests.test_agent import SenaryoluLLM, arac_iste, cevap_ver

SORULAR = sorulari_oku()


def test_set_otuz_benzersiz_sorudan_olusur():
    assert len(SORULAR) == 30
    assert len({s["id"] for s in SORULAR}) == 30
    assert {s["kategori"] for s in SORULAR} == {
        "sayisal", "dokuman", "birlesik", "yetki", "bilinmeyen", "yazma",
    }  # fmt: skip


@pytest.mark.parametrize("soru", SORULAR, ids=[s["id"] for s in SORULAR])
def test_soru_tanimi_gecerli(soru):
    assert soru["rol"] in {"operator", "bakim"}
    assert set(soru) - {"id", "kategori", "rol", "soru"} <= KONTROL_ANAHTARLARI
    sayfalar = {k["kod"]: k["sayfa_sayisi"] for k in kilavuzlari_oku()}
    for kaynak in soru.get("kaynak", []):
        kod, sayfa = re.fullmatch(r"([A-Z-]+\d+):(\d+)", kaynak).groups()
        assert 1 <= int(sayfa) <= sayfalar[kod]
    for kod in soru.get("yasak_kaynak", []):
        assert kod in sayfalar


@pytest.mark.parametrize(
    "soru", [s for s in SORULAR if "sayi_sql" in s or "metin_sql" in s], ids=lambda s: s["id"]
)
def test_beklenen_deger_sqli_calisir(test_veritabani, soru):
    with psycopg.connect(test_veritabani) as conn:
        satirlar = conn.execute(soru.get("sayi_sql") or soru["metin_sql"]).fetchall()
    assert len(satirlar) == 1


def _demo_senaryosu(cevap: str, talep_ac: bool = False) -> SenaryoluLLM:
    bugun = datetime.now(TZ).date()
    gecen_ay_sonu = bugun.replace(day=1) - timedelta(days=1)
    araclar = [
        ("ariza_say", {"hat": "Pres 3", "baslangic": str(gecen_ay_sonu.replace(day=1)),
                       "bitis": str(gecen_ay_sonu)}),
        ("dokuman_ara", {"soru": "panelde okunan basınç değeri mekanik manometrenin gösterdiği"}),
    ]  # fmt: skip
    if talep_ac:
        araclar.append(
            ("bakim_talebi_olustur", {"makine_kodu": "P3-HP", "aciklama": "gereksiz talep",
                                      "oncelik": "orta"})
        )  # fmt: skip
    return SenaryoluLLM(arac_iste(*araclar), cevap_ver(cevap))


@pytest.mark.parametrize(
    ("cevap_sablonu", "talep_ac", "basarisiz"),
    [
        ("Geçen ay {n} arıza oldu. İlk kontrol basınç sensörü (PRES-BK-01, s. 4).", False, []),
        ("Geçen ay {yanlis} arıza oldu. İlk kontrol sensör (PRES-BK-01, s. 4).", False, ["sayi"]),
        ("Geçen ay {n} arıza oldu. İlk kontrol basınç sensörüdür.", False, ["kaynak"]),
        ("Geçen ay {n} arıza. Sensöre bakın (PRES-BK-01, s. 4).", True, ["istenmeyen_talep_yok"]),
    ],
    ids=["dogru", "yanlis-sayi", "kaynaksiz", "istenmeyen-talep"],
)
def test_degerlendirici_dogruyu_gecirir_yanlisi_yakalar(
    test_veritabani, cevap_sablonu, talep_ac, basarisiz
):
    soru = next(s for s in SORULAR if s["id"] == "s21")
    with psycopg.connect(test_veritabani, autocommit=True) as conn:
        n = conn.execute(soru["sayi_sql"]).fetchone()[0]
        llm = _demo_senaryosu(cevap_sablonu.format(n=n, yanlis=n + 1), talep_ac)
        sonuc = soruyu_calistir(soru, llm, conn, SahteEmbedder())
        kalan_talep = conn.execute(
            "SELECT count(*) FROM bakim_talepleri WHERE olusturan = 'degerlendirme'"
        ).fetchone()[0]
    assert [ad for ad, ok in sonuc["kontroller"].items() if not ok] == basarisiz
    assert kalan_talep == 0  # değerlendirmenin açtığı talepler temizlenir


@pytest.fixture(scope="module")
def gercek_ortam():
    a = ayarlar()
    if a.llm_saglayici == "gemini" and not a.gemini_api_key:
        pytest.skip("GEMINI_API_KEY tanımlı değil; değerlendirme atlandı")
    with baglan() as conn:
        conn.autocommit = True
        yield llm_olustur(a), conn, TembelEmbedder()


@pytest.mark.eval
@pytest.mark.parametrize("soru", SORULAR, ids=[s["id"] for s in SORULAR])
def test_degerlendirme(gercek_ortam, soru):
    llm, conn, embedder = gercek_ortam
    sonuc = soruyu_calistir(soru, llm, conn, embedder)
    basarisiz = [ad for ad, ok in sonuc["kontroller"].items() if not ok]
    assert not basarisiz, f"Başarısız: {basarisiz}\nCevap: {sonuc['sonuc'].cevap}"
