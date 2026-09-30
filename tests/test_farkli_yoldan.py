"""Farklı yoldan doğrulama.

API'nin ve agent araçlarının sonucu, aynı sahte veriden SQL kullanmadan Python'da hesaplanan
sonuçla karşılaştırılır. Her hat, ay ve arıza tipi kombinasyonu ayrı bir testtir; saat dilimi,
ay sınırı, büyük/küçük harf ve filtre birleşimi hataları burada yakalanır.
"""

import calendar
import json
import random
from collections import Counter
from datetime import date, timedelta

import psycopg
import pytest

from app import sorgular
from app.auth import Kullanici
from app.db import TZ
from app.tools import AracBaglami, arac_calistir
from scripts.seed import HATLAR, STOK
from tests.conftest import SahteEmbedder
from tests.test_api import _beklenen_idler

HAT_ADLARI = [ad for ad, _, _ in HATLAR]
ARIZA_TIPLERI = [None, "hidrolik", "mekanik", "elektrik", "sensor", "yazilim", "pnomatik"]
AYLAR = [(2026, ay) for ay in range(4, 10)]  # test verisi 30.09.2026'da biten 6 ay
GUNLER = [date(2026, 4, 1) + timedelta(days=i) for i in range(0, 183, 3)]


def _ay(yil: int, ay: int) -> tuple[date, date]:
    return date(yil, ay, 1), date(yil, ay, calendar.monthrange(yil, ay)[1])


def _hat_adi(veri: dict) -> dict[int, str]:
    makine_hatti = {m["id"]: m["hat_id"] for m in veri["makineler"]}
    hat_adi = {h["id"]: h["ad"] for h in veri["hatlar"]}
    return {m_id: hat_adi[h_id] for m_id, h_id in makine_hatti.items()}


@pytest.fixture(scope="module")
def baglanti(test_veritabani):
    with psycopg.connect(test_veritabani, autocommit=True) as conn:
        yield conn


@pytest.mark.parametrize("tip", ARIZA_TIPLERI, ids=lambda t: t or "tum-tipler")
@pytest.mark.parametrize("ay", AYLAR, ids=lambda a: f"{a[0]}-{a[1]:02d}")
@pytest.mark.parametrize("hat", HAT_ADLARI)
def test_arizalar_api_bagimsiz_hesapla_ayni(istemci, test_verisi, hat, ay, tip):
    baslangic, bitis = _ay(*ay)
    parametreler = {"hat": hat, "baslangic": baslangic, "bitis": bitis, "limit": 1000}
    if tip:
        parametreler["ariza_tipi"] = tip
    cevap = istemci.get("/arizalar", params=parametreler)
    assert cevap.status_code == 200
    beklenen = _beklenen_idler(test_verisi, hat, baslangic, bitis, tip)
    assert cevap.json()["toplam"] == len(beklenen)
    assert {a["id"] for a in cevap.json()["arizalar"]} == beklenen


@pytest.mark.parametrize("ay", AYLAR, ids=lambda a: f"{a[0]}-{a[1]:02d}")
@pytest.mark.parametrize("hat", [None, *HAT_ADLARI], ids=lambda h: h or "tum-hatlar")
def test_ariza_ozeti_tiplere_ve_makinelere_gore_dogru(baglanti, test_verisi, hat, ay):
    baslangic, bitis = _ay(*ay)
    hat_adi = _hat_adi(test_verisi)
    makine_kodu = {m["id"]: m["kod"] for m in test_verisi["makineler"]}
    secilen = [
        a
        for a in test_verisi["ariza_kayitlari"]
        if (hat is None or hat_adi[a["makine_id"]] == hat)
        and baslangic <= a["baslangic"].astimezone(TZ).date() <= bitis
    ]
    ozet = sorgular.ariza_ozeti(baglanti, hat=hat, baslangic=baslangic, bitis=bitis)
    assert ozet["toplam"] == len(secilen)
    assert ozet["tiplere_gore"] == dict(Counter(a["ariza_tipi"] for a in secilen))
    assert ozet["makinelere_gore"] == dict(Counter(makine_kodu[a["makine_id"]] for a in secilen))


@pytest.mark.parametrize("gun", GUNLER, ids=str)
def test_tek_gunluk_aralik_turkiye_saatiyle(istemci, test_verisi, gun):
    cevap = istemci.get("/arizalar", params={"baslangic": gun, "bitis": gun, "limit": 1000})
    assert {a["id"] for a in cevap.json()["arizalar"]} == _beklenen_idler(
        test_verisi, baslangic=gun, bitis=gun
    )


YAZIMLAR = {
    "ayni": str,
    "kucuk": str.lower,
    "buyuk": str.upper,
    "bosluklu": lambda metin: f"  {metin}  ",
}


@pytest.mark.parametrize("yazim", YAZIMLAR.values(), ids=YAZIMLAR.keys())
@pytest.mark.parametrize("hat", HAT_ADLARI)
def test_hat_adi_yazim_farklarina_dayanikli(istemci, test_verisi, hat, yazim):
    cevap = istemci.get("/arizalar", params={"hat": yazim(hat), "limit": 1})
    assert cevap.status_code == 200
    assert cevap.json()["toplam"] == len(_beklenen_idler(test_verisi, hat))


@pytest.mark.parametrize("yazim", YAZIMLAR.values(), ids=YAZIMLAR.keys())
@pytest.mark.parametrize("parca", STOK, ids=lambda p: p[0])
def test_stok_sorgusu_her_parca_icin_dogru(baglanti, parca, yazim):
    kod, ad, kategori, miktar, min_miktar, birim, konum = parca
    (satir,) = sorgular.stok_getir(baglanti, parca_kodu=yazim(kod))
    assert (satir["parca_kodu"], satir["ad"], satir["kategori"]) == (kod, ad, kategori)
    assert (satir["miktar"], satir["min_miktar"], satir["birim"], satir["konum"]) == (
        miktar,
        min_miktar,
        birim,
        konum,
    )
    assert satir["kritik"] is (miktar < min_miktar)


@pytest.mark.parametrize("oncelik", ["dusuk", "orta", "yuksek"])
@pytest.mark.parametrize("makine_sirasi", range(21))
def test_bakim_talebi_her_makine_ve_oncelik_icin(baglanti, test_verisi, makine_sirasi, oncelik):
    makine = test_verisi["makineler"][makine_sirasi]
    baglam = AracBaglami(
        conn=baglanti, embedder=SahteEmbedder(), kullanici=Kullanici("test-talep", "T", "operator")
    )
    arguman = json.dumps(
        {"makine_kodu": makine["kod"].lower(), "aciklama": "Test talebi", "oncelik": oncelik}
    )
    sonuc = arac_calistir("bakim_talebi_olustur", arguman, baglam)["sonuc"]
    satir = baglanti.execute(
        "SELECT makine_id, oncelik, durum, olusturan FROM bakim_talepleri WHERE id = %s",
        [sonuc["talep_id"]],
    ).fetchone()
    assert satir == (makine["id"], oncelik, "acik", "test-talep")


@pytest.mark.parametrize("tohum", range(25))
def test_rastgele_filtre_birlesimleri(istemci, test_verisi, tohum):
    rng = random.Random(tohum)
    hat = rng.choice([None, *HAT_ADLARI])
    tip = rng.choice(ARIZA_TIPLERI)
    baslangic = date(2026, 3, 25) + timedelta(days=rng.randrange(190))
    bitis = baslangic + timedelta(days=rng.randrange(60))
    parametreler = {"baslangic": baslangic, "bitis": bitis, "limit": 1000}
    if hat:
        parametreler["hat"] = hat
    if tip:
        parametreler["ariza_tipi"] = tip
    cevap = istemci.get("/arizalar", params=parametreler)
    beklenen = _beklenen_idler(test_verisi, hat, baslangic, bitis, tip)
    assert cevap.json()["toplam"] == len(beklenen)
    assert {a["id"] for a in cevap.json()["arizalar"]} == beklenen
