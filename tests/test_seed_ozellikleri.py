"""Seed değişmezleri: 40 farklı rastgele tohumla üretilen verinin her biri şemanın ve veride
vaat edilen desenlerin kurallarına uymalı. Tek bir tohumda (42) tesadüfen tutan bir kural burada
yakalanır."""

from collections import Counter
from datetime import datetime, timedelta
from functools import cache

import pytest

from app.db import TZ
from scripts.seed import GUN_SAYISI, SUREN_ARIZALAR, veri_uret

SON_AN = datetime(2026, 9, 30, 12, 0, tzinfo=TZ)
TOHUMLAR = range(40)


@cache
def veri(tohum: int) -> dict:
    return veri_uret(SON_AN, tohum)


@pytest.mark.parametrize("tohum", TOHUMLAR)
def test_yabanci_anahtarlar_ve_idler(tohum):
    v = veri(tohum)
    for tablo, kayitlar in v.items():
        assert [k["id"] for k in kayitlar] == list(range(1, len(kayitlar) + 1)), tablo
    makine = {m["id"] for m in v["makineler"]}
    ariza_makinesi = {a["id"]: a["makine_id"] for a in v["ariza_kayitlari"]}
    stok = {s["id"] for s in v["stok"]}
    assert set(ariza_makinesi.values()) <= makine
    for emir in v["is_emirleri"]:
        assert emir["makine_id"] in makine
        assert emir["parca_id"] is None or emir["parca_id"] in stok
        if emir["ariza_id"] is not None:
            assert ariza_makinesi[emir["ariza_id"]] == emir["makine_id"]


@pytest.mark.parametrize("tohum", TOHUMLAR)
def test_ariza_zamanlari_gecerli(tohum):
    en_erken = SON_AN - timedelta(days=GUN_SAYISI)
    for ariza in veri(tohum)["ariza_kayitlari"]:
        assert en_erken <= ariza["baslangic"] <= SON_AN
        assert ariza["bitis"] is None or ariza["baslangic"] < ariza["bitis"] <= SON_AN
        assert ariza["onem"] in {"dusuk", "orta", "yuksek"}
        if ariza["onem"] == "yuksek":
            assert ariza["hat_durdu"]


@pytest.mark.parametrize("tohum", TOHUMLAR)
def test_is_emirleri_sema_kurallarina_uyar(tohum):
    for emir in veri(tohum)["is_emirleri"]:
        assert (emir["durum"] == "kapali") == (emir["kapanis"] is not None)
        assert emir["kapanis"] is None or emir["kapanis"] > emir["acilis"]
        assert (emir["tip"] == "ariza") == (emir["ariza_id"] is not None)
        assert (emir["parca_id"] is None) == (emir["parca_adet"] is None)
        assert emir["acilis"] <= SON_AN


@pytest.mark.parametrize("tohum", TOHUMLAR)
def test_pres_3_en_cok_ariza_veren_hat(tohum):
    v = veri(tohum)
    makine_hatti = {m["id"]: m["hat_id"] for m in v["makineler"]}
    sayac = Counter(makine_hatti[a["makine_id"]] for a in v["ariza_kayitlari"])
    assert sayac.most_common(1)[0][0] == 3  # Pres 3


@pytest.mark.parametrize("tohum", TOHUMLAR)
def test_pazar_en_az_arizali_gun(tohum):
    gunler = Counter(a["baslangic"].weekday() for a in veri(tohum)["ariza_kayitlari"])
    assert min(gunler, key=gunler.get) == 6


@pytest.mark.parametrize("tohum", TOHUMLAR)
def test_seed_aninda_suren_arizalar_var(tohum):
    suren = [a for a in veri(tohum)["ariza_kayitlari"] if a["bitis"] is None]
    assert len(suren) >= len(SUREN_ARIZALAR)
    assert any(a["hat_durdu"] for a in suren)


@pytest.mark.parametrize("tohum", TOHUMLAR)
def test_bakim_talepleri_gecerli(tohum):
    v = veri(tohum)
    for talep in v["bakim_talepleri"]:
        assert talep["oncelik"] in {"dusuk", "orta", "yuksek"}
        assert talep["durum"] in {"acik", "onaylandi", "reddedildi", "tamamlandi"}
        if (SON_AN - talep["olusturma"]).days >= 14:
            assert talep["durum"] != "acik"  # iki haftadan eski talep açık kalmaz
