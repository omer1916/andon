from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from psycopg_pool import PoolTimeout

from app.db import TZ
from app.main import uygulama_olustur


def _beklenen_idler(veri, hat=None, baslangic=None, bitis=None, ariza_tipi=None) -> set[int]:
    """Aynı filtreye uyan arızaları API'den bağımsız olarak, doğrudan üretilen veriden bulur."""
    makine_hatti = {m["id"]: m["hat_id"] for m in veri["makineler"]}
    hat_adi = {h["id"]: h["ad"] for h in veri["hatlar"]}
    idler = set()
    for ariza in veri["ariza_kayitlari"]:
        gun = ariza["baslangic"].astimezone(TZ).date()
        if hat and hat_adi[makine_hatti[ariza["makine_id"]]] != hat:
            continue
        if baslangic and gun < baslangic:
            continue
        if bitis and gun > bitis:
            continue
        if ariza_tipi and ariza["ariza_tipi"] != ariza_tipi:
            continue
        idler.add(ariza["id"])
    return idler


def _idler(cevap) -> set[int]:
    return {a["id"] for a in cevap.json()["arizalar"]}


def test_saglik(istemci):
    cevap = istemci.get("/saglik")
    assert cevap.status_code == 200
    assert cevap.json() == {"veritabani": True}


def test_hatlar_listelenir(istemci, test_verisi):
    cevap = istemci.get("/hatlar")
    assert cevap.status_code == 200
    hatlar = cevap.json()
    assert [h["ad"] for h in hatlar] == [h["ad"] for h in test_verisi["hatlar"]]
    assert all(h["makine_sayisi"] == 3 for h in hatlar)


def test_demo_sorusu_pres_3_gecen_ay(istemci, test_verisi):
    # Test verisi 30 Eylül 2026'da bitiyor, yani "geçen ay" ağustos.
    cevap = istemci.get(
        "/arizalar", params={"hat": "Pres 3", "baslangic": "2026-08-01", "bitis": "2026-08-31"}
    )
    assert cevap.status_code == 200
    beklenen = _beklenen_idler(test_verisi, "Pres 3", date(2026, 8, 1), date(2026, 8, 31))
    assert cevap.json()["toplam"] == len(beklenen) > 0
    assert _idler(cevap) == beklenen


def test_gun_sinirlari_turkiye_saatine_gore(istemci, test_verisi):
    # Gece 03:00'ten önce başlayan arıza UTC'de bir önceki güne düşer. API onu
    # Türkiye saatindeki gününe saymalı; bitiş günü de aralığa dahil olmalı.
    gece_arizasi = next(
        a for a in test_verisi["ariza_kayitlari"] if a["baslangic"].astimezone(TZ).hour < 3
    )
    gun = gece_arizasi["baslangic"].astimezone(TZ).date()
    cevap = istemci.get("/arizalar", params={"baslangic": gun, "bitis": gun})
    assert gece_arizasi["id"] in _idler(cevap)
    assert _idler(cevap) == _beklenen_idler(test_verisi, baslangic=gun, bitis=gun)


def test_ariza_tipine_gore_filtrelenir(istemci, test_verisi):
    cevap = istemci.get(
        "/arizalar", params={"hat": "Pres 3", "ariza_tipi": "hidrolik", "limit": 1000}
    )
    beklenen = _beklenen_idler(test_verisi, hat="Pres 3", ariza_tipi="hidrolik")
    assert _idler(cevap) == beklenen


def test_filtresiz_toplam_tum_arizalar(istemci, test_verisi):
    cevap = istemci.get("/arizalar", params={"limit": 1})
    assert cevap.json()["toplam"] == len(test_verisi["ariza_kayitlari"])
    assert len(cevap.json()["arizalar"]) == 1


def test_sayfalama_yeniden_eskiye(istemci):
    ilk = istemci.get("/arizalar", params={"limit": 5}).json()["arizalar"]
    ikinci = istemci.get("/arizalar", params={"limit": 5, "offset": 5}).json()["arizalar"]
    assert len(ilk) == len(ikinci) == 5
    assert not {a["id"] for a in ilk} & {a["id"] for a in ikinci}
    zamanlar = [datetime.fromisoformat(a["baslangic"]) for a in ilk + ikinci]
    assert zamanlar == sorted(zamanlar, reverse=True)


def test_hat_adi_buyuk_kucuk_harf_duyarsiz(istemci):
    duzgun = istemci.get("/arizalar", params={"hat": "Pres 3"}).json()["toplam"]
    daginik = istemci.get("/arizalar", params={"hat": "  pres 3 "}).json()["toplam"]
    assert duzgun == daginik > 0


def test_suren_arizanin_bitisi_ve_suresi_bos(istemci):
    cevap = istemci.get("/arizalar", params={"baslangic": "2026-09-30", "bitis": "2026-09-30"})
    suren = [a for a in cevap.json()["arizalar"] if a["bitis"] is None]
    assert suren
    assert all(a["sure_dk"] is None for a in suren)


def test_bilinmeyen_hat_404_ve_gecerli_hatlari_soyler(istemci):
    cevap = istemci.get("/arizalar", params={"hat": "Pres 9"})
    assert cevap.status_code == 404
    assert "Pres 3" in cevap.json()["detail"]


@pytest.mark.parametrize(
    "parametreler",
    [
        {"baslangic": "2026-09-01", "bitis": "2026-08-01"},  # ters aralık
        {"baslangic": "dün"},  # tarih değil
        {"ariza_tipi": "nukleer"},  # tanımsız tip
        {"limit": 0},
        {"limit": 5000},
        {"hatt": "Pres 3"},  # yazım hatası: bilinmeyen parametre
    ],
)
def test_gecersiz_parametre_422(istemci, parametreler):
    assert istemci.get("/arizalar", params=parametreler).status_code == 422


class _UlasilamayanHavuz:
    def connection(self, timeout=None):
        raise PoolTimeout("veritabanına ulaşılamıyor")


def test_veritabani_yoksa_saglik_503():
    uygulama = uygulama_olustur()
    uygulama.state.havuz = _UlasilamayanHavuz()
    # `with` kullanmıyoruz: lifespan çalışmaz, gerçek havuz hiç açılmaz.
    cevap = TestClient(uygulama).get("/saglik")
    assert cevap.status_code == 503
    assert cevap.json() == {"veritabani": False}
