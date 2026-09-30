from collections import Counter
from datetime import datetime, timedelta

import pytest

from scripts.seed import GUN_SAYISI, TZ, veri_uret

SON_AN = datetime(2026, 9, 30, 12, 0, tzinfo=TZ)


@pytest.fixture(scope="module")
def veri():
    return veri_uret(SON_AN)


def test_ayni_tohum_ayni_veriyi_uretir(veri):
    assert veri_uret(SON_AN) == veri


def test_farkli_tohum_farkli_veri_uretir(veri):
    assert veri_uret(SON_AN, tohum=7)["ariza_kayitlari"] != veri["ariza_kayitlari"]


def test_arizalar_alti_aylik_aralikta(veri):
    en_erken = SON_AN - timedelta(days=GUN_SAYISI)
    for ariza in veri["ariza_kayitlari"]:
        assert en_erken <= ariza["baslangic"] <= SON_AN
        assert ariza["bitis"] is None or ariza["baslangic"] < ariza["bitis"] <= SON_AN


def test_idler_birden_baslayip_artiyor(veri):
    for tablo, kayitlar in veri.items():
        assert [k["id"] for k in kayitlar] == list(range(1, len(kayitlar) + 1)), tablo


def test_yabanci_anahtarlar_gecerli(veri):
    hat_idleri = {h["id"] for h in veri["hatlar"]}
    makine_idleri = {m["id"] for m in veri["makineler"]}
    stok_idleri = {s["id"] for s in veri["stok"]}
    ariza_makinesi = {a["id"]: a["makine_id"] for a in veri["ariza_kayitlari"]}

    assert {m["hat_id"] for m in veri["makineler"]} <= hat_idleri
    assert set(ariza_makinesi.values()) <= makine_idleri
    assert {t["makine_id"] for t in veri["bakim_talepleri"]} <= makine_idleri
    for emir in veri["is_emirleri"]:
        assert emir["makine_id"] in makine_idleri
        assert emir["parca_id"] is None or emir["parca_id"] in stok_idleri
        if emir["ariza_id"] is not None:
            assert ariza_makinesi[emir["ariza_id"]] == emir["makine_id"]


def test_is_emirleri_sema_kurallarina_uyuyor(veri):
    for emir in veri["is_emirleri"]:
        assert (emir["durum"] == "kapali") == (emir["kapanis"] is not None)
        assert emir["kapanis"] is None or emir["kapanis"] > emir["acilis"]
        assert (emir["tip"] == "ariza") == (emir["ariza_id"] is not None)
        assert (emir["parca_id"] is None) == (emir["parca_adet"] is None)


def test_en_cok_ariza_pres_3te(veri):
    makine_hatti = {m["id"]: m["hat_id"] for m in veri["makineler"]}
    hat_adi = {h["id"]: h["ad"] for h in veri["hatlar"]}
    sayac = Counter(hat_adi[makine_hatti[a["makine_id"]]] for a in veri["ariza_kayitlari"])
    assert sayac.most_common(1)[0][0] == "Pres 3"


def test_minimum_stok_altinda_parca_var(veri):
    assert any(s["miktar"] < s["min_miktar"] for s in veri["stok"])
