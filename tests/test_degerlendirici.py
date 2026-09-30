"""Değerlendiricinin kendisi: yanlış puanlayan bir değerlendirici bütün ölçümleri boşa çıkarır.

İlk gerçek çalıştırmada iki doğru cevap, Türkçe ek farkı yüzünden ("bulunamamaktadır" ≠
"bulunamadı") başarısız sayılmıştı; buradaki testler o sınıf hataları yakalar.
"""

import psycopg
import pytest

from app.agent import SohbetSonucu
from scripts.degerlendir import _normal, kontrol_et, sayi_geciyor, sorulari_oku, yuzdelik

SORULAR = {s["id"]: s for s in sorulari_oku()}


@pytest.mark.parametrize(
    ("metin", "gecer"),
    [
        ("Geçen ay 25 arıza oldu.", True),
        ("Toplam: 25.", True),
        ("toplam **25** arıza", True),
        ("(25)", True),
        ("25'i hidrolik", True),
        ("25, 13'ü hidrolik", True),
        ("125 arıza", False),
        ("250 arıza", False),
        ("2,5 saat", False),
        ("25,5 saat", False),
        ("25.5 saat", False),
        ("0,25", False),
        ("yirmi beş arıza", False),
        ("", False),
    ],
)
def test_sayi_bagimsiz_olarak_aranir(metin, gecer):
    assert sayi_geciyor(metin, 25) is gecer


@pytest.mark.parametrize(
    ("metin", "beklenen"),
    [
        ("İLK PARÇA", "ilk parça"),
        ("HİDROLİK", "hidrolik"),
        ("ışık", "ışık"),
        ("IŞIK", "ışık"),
        ("Çıkış", "çıkış"),
        ("ŞÜPHELİ ÖĞE", "şüpheli öğe"),
    ],
)
def test_turkce_kucuk_harf(metin, beklenen):
    assert _normal(metin) == beklenen


def _sonuc(cevap: str, kaynaklar: tuple[str, ...] = (), araclar: tuple[str, ...] = ()):
    return SohbetSonucu(
        cevap=cevap,
        kaynaklar=[
            {"dokuman_kodu": k.split(":")[0], "sayfa": int(k.split(":")[1])} for k in kaynaklar
        ],
        arac_cagrilari=[{"ad": a, "argumanlar": {}, "hata": None} for a in araclar],
        adim_sayisi=1,
    )


@pytest.fixture(scope="module")
def baglanti(test_veritabani):
    with psycopg.connect(test_veritabani, autocommit=True) as conn:
        yield conn


def _kontroller(baglanti, soru_id, sonuc):
    son_talep = baglanti.execute("SELECT coalesce(max(id), 0) FROM bakim_talepleri").fetchone()[0]
    return kontrol_et(SORULAR[soru_id], sonuc, baglanti, son_talep)


@pytest.mark.parametrize(
    ("cevap", "gecer"),
    [
        ("Dokümanlarda bu konuda bir bilgi bulunamamaktadır.", True),
        ("Bu bilgi kılavuzlarda bulunamadı.", True),
        ("Kılavuzlarda yer almıyor.", True),
        ("Kılavuzlarda yer almamaktadır.", True),
        ("Bu konuda bilgi bulunmuyor.", True),
        ("Mevcut dokümanlar bu konuyu içermiyor.", True),
        # Olumlu ifadeler, olumsuz köklerle karıştırılmamalı:
        ("Filtreler her 6 ayda bir değiştirilmelidir; bilgi kılavuzda bulunmaktadır.", False),
        ("Bu bilgi kılavuzda yer almaktadır: her hafta.", False),
        ("Filtreler aylık değiştirilir.", False),
    ],
)
def test_bilinmeyen_soruda_olumsuz_ifade_kokleri(baglanti, cevap, gecer):
    assert _kontroller(baglanti, "s28", _sonuc(cevap))["herhangi"] is gecer


@pytest.mark.parametrize(
    ("cevap", "kaynaklar", "gecer"),
    [
        ("Önce sensörü kontrol edin (PRES-BK-01, s. 4).", ("PRES-BK-01:4",), True),
        ("Önce sensörü kontrol edin (pres-bk-01, s. 4).", ("PRES-BK-01:4",), True),
        ("Önce sensörü kontrol edin.", ("PRES-BK-01:4",), False),  # okundu ama gösterilmedi
        ("Önce sensörü kontrol edin (PRES-BK-01, s. 4).", (), False),  # gösterildi ama okunmadı
        ("Önce sensörü kontrol edin (PRES-BK-01, s. 7).", ("PRES-BK-01:7",), False),  # yanlış sayfa
    ],
)
def test_kaynak_hem_okunmus_hem_gosterilmis_olmali(baglanti, cevap, kaynaklar, gecer):
    sonuc = _sonuc(cevap, kaynaklar, ("dokuman_ara",))
    assert _kontroller(baglanti, "s11", sonuc)["kaynak"] is gecer


@pytest.mark.parametrize(
    ("kaynaklar", "gecer"),
    [
        (("PRES-OT-01:2", "KAL-PR-01:1"), True),
        (("PRES-OT-01:2", "PRES-BK-01:5"), False),
        (("KR-BK-01:3",), False),
        ((), True),
    ],
)
def test_yetki_kontrolu_yasak_dokumani_yakalar(baglanti, kaynaklar, gecer):
    sonuc = _sonuc("Bakım ekibini çağırın.", kaynaklar)
    assert _kontroller(baglanti, "s25", sonuc)["yetki"] is gecer


@pytest.mark.parametrize(
    ("araclar", "gecer"),
    [
        (("ariza_say", "dokuman_ara"), True),
        (("dokuman_ara", "ariza_say", "stok_sorgula"), True),
        (("ariza_say",), False),
        ((), False),
    ],
)
def test_beklenen_araclar_cagrilmis_olmali(baglanti, araclar, gecer):
    sonuc = _sonuc("-", araclar=araclar)
    assert _kontroller(baglanti, "s21", sonuc)["araclar"] is gecer


@pytest.mark.parametrize(
    ("degerler", "yuzde", "beklenen"),
    [
        (list(range(1, 31)), 95, 29),
        (list(range(1, 31)), 50, 15),
        (list(range(1, 11)), 90, 9),
        ([7], 95, 7),
        ([3, 1, 2], 100, 3),
        ([5, 1], 50, 1),
    ],
)
def test_yuzdelik_en_yakin_sira(degerler, yuzde, beklenen):
    assert yuzdelik(degerler, yuzde) == beklenen
