"""Özellik tabanlı testler (Hypothesis).

Tek tek örnek yazmak yerine her girdi için doğru olması gereken kural tanımlanır; Hypothesis
her testte yüzlerce rastgele girdi üretip kuralı bozmaya çalışır, bozan en küçük girdiyi
raporlar.
"""

import string
from datetime import date

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from app.auth import Kullanici, token_coz, token_uret
from app.models import ArizaFiltresi
from app.rag import _baslik_mi, parcala, vektor_metni
from scripts.degerlendir import _normal, sayi_geciyor

AYAR = settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])

kelime = st.text(alphabet=string.ascii_lowercase + "çğıöşü", min_size=1, max_size=8)
satir = st.lists(kelime, min_size=1, max_size=15).map(" ".join)
baslik = st.builds(
    lambda no, alt, ad: f"{no}.{alt if alt else ''} {ad.capitalize()}",
    st.integers(1, 9),
    st.one_of(st.none(), st.integers(1, 9)),
    kelime,
)
sayfa = st.lists(st.one_of(satir, baslik), max_size=12)
dokuman = st.lists(sayfa, min_size=1, max_size=6)
pencere = st.tuples(st.integers(5, 150), st.integers(0, 40)).filter(lambda p: p[1] < p[0])


@AYAR
@given(dokuman, pencere)
def test_parca_siniri_asmaz_ve_bos_olmaz(sayfalar, ayar):
    en_fazla, ortusme = ayar
    for parca in parcala(sayfalar, en_fazla, ortusme):
        assert 1 <= parca.sayfa <= len(sayfalar)
        assert 0 < len(parca.icerik.split()) <= en_fazla


@AYAR
@given(dokuman, pencere)
def test_baslik_disindaki_her_kelime_kendi_sayfasinin_bir_parcasinda(sayfalar, ayar):
    parcalar = parcala(sayfalar, *ayar)
    for no, satirlar in enumerate(sayfalar, start=1):
        sayfa_kelimeleri = set()
        for p in parcalar:
            if p.sayfa == no:
                sayfa_kelimeleri.update(p.icerik.split())
        for s in satirlar:
            if not _baslik_mi(s):
                assert set(s.split()) <= sayfa_kelimeleri


@AYAR
@given(dokuman, pencere)
def test_parca_metni_sayfa_metninin_ardisik_bir_dilimi(sayfalar, ayar):
    # Parçalar kelimeleri karıştırmaz, atlamaz: her parça, sayfadaki bir bölümün kelime
    # dizisinin ardışık bir dilimidir.
    for parca in parcala(sayfalar, *ayar):
        metin = " ".join(s for s in sayfalar[parca.sayfa - 1] if not _baslik_mi(s)).split()
        dilim = parca.icerik.split()
        assert any(metin[i : i + len(dilim)] == dilim for i in range(len(metin)))


@AYAR
@given(st.lists(st.floats(-1, 1, allow_nan=False), min_size=1, max_size=384))
def test_vektor_metni_geri_okunabilir(vektor):
    metin = vektor_metni(vektor)
    assert metin.startswith("[") and metin.endswith("]")
    geri = [float(x) for x in metin[1:-1].split(",")]
    assert geri == pytest.approx(vektor, abs=1e-6)


@AYAR
@given(st.integers(0, 10**7), st.text(max_size=20), st.text(max_size=20))
def test_sayi_kendi_basina_gectiginde_bulunur(sayi, once, sonra):
    once = once.rstrip(string.digits + ".,")
    sonra = sonra.lstrip(string.digits)
    if sonra[:1] in {".", ","} and sonra[1:2].isdigit():
        sonra = " " + sonra
    assert sayi_geciyor(f"{once} {sayi}{sonra}", sayi)


@AYAR
@given(st.integers(1, 10**6), st.integers(1, 9))
def test_sayi_baska_sayinin_parcasi_olarak_bulunmaz(sayi, rakam):
    assert not sayi_geciyor(f"toplam {rakam}{sayi} arıza", sayi)
    assert not sayi_geciyor(f"toplam {sayi}{rakam} arıza", sayi)
    assert not sayi_geciyor(f"{sayi},{rakam} saat", sayi)


@AYAR
@given(st.text(max_size=60))
def test_turkce_kucuk_harf_idempotent(metin):
    assert _normal(_normal(metin)) == _normal(metin)


@AYAR
@given(
    st.text(alphabet=string.ascii_letters + string.digits + "çğıöşüÇĞİÖŞÜ-_.", min_size=1),
    st.text(min_size=1, max_size=40).filter(lambda m: "\x00" not in m),
    st.sampled_from(["operator", "bakim"]),
)
def test_token_gidis_donus(kullanici_adi, ad_soyad, rol):
    kullanici = Kullanici(kullanici_adi, ad_soyad, rol)
    assert token_coz(token_uret(kullanici)) == kullanici


@AYAR
@given(st.dates(date(2000, 1, 1), date(2100, 1, 1)), st.dates(date(2000, 1, 1), date(2100, 1, 1)))
def test_ariza_filtresi_tarih_sirasi(baslangic, bitis):
    if baslangic <= bitis:
        assert ArizaFiltresi(baslangic=baslangic, bitis=bitis).bitis == bitis
    else:
        with pytest.raises(ValidationError):
            ArizaFiltresi(baslangic=baslangic, bitis=bitis)


@AYAR
@given(st.text(max_size=100))
def test_baslik_tanima_numarasiz_satiri_baslik_saymaz(metin):
    if not metin[:1].isdigit():
        assert not _baslik_mi(metin)
