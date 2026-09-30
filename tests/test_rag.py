from pathlib import Path

import pytest

from app.rag import Parca, _baslik_mi, parcala, pdf_sayfalari

KILAVUZLAR = Path(__file__).resolve().parent.parent / "data" / "kilavuzlar"


def test_pdf_sayfalari_ust_ve_alt_bilgiyi_atar():
    sayfalar = pdf_sayfalari(KILAVUZLAR / "PRES-BK-01.pdf")
    assert len(sayfalar) == 9
    satirlar = [s for sayfa in sayfalar for s in sayfa]
    assert not any(s.startswith("Sayfa ") for s in satirlar)
    assert not any(s.startswith("PRES-BK-01 ·") for s in satirlar)
    assert "4.1 Genel yaklaşım" in sayfalar[3]


@pytest.mark.parametrize(
    ("satir", "beklenen"),
    [
        ("4. HİDROLİK ARIZALARDA İLK KONTROL", True),
        ("4.2 İlk kontrol sırası", True),
        ("4.2.1 Ayrıntı", True),
        ("1) Paneldeki alarm kodunu kaydedin.", False),  # numaralı adım
        ("2 Adet parça değiştirildi", False),  # numaradan sonra nokta yok
        ("6.1'e göre kontrol edilir.", False),  # satır kaymasıyla başa gelen atıf
        ("4.2 " + "Çok uzun bir satır " * 10, False),
    ],
)
def test_baslik_tanima(satir, beklenen):
    assert _baslik_mi(satir) is beklenen


def test_parca_sayfa_asmaz_ve_bolum_sonraki_sayfaya_tasinir():
    sayfalar = [
        ["1. GİRİŞ", "birinci sayfa metni"],
        ["bölümün devamı", "1.1 Alt başlık", "alt başlık metni"],
    ]
    assert parcala(sayfalar) == [
        Parca(1, "1. GİRİŞ", "birinci sayfa metni"),
        Parca(2, "1. GİRİŞ", "bölümün devamı"),
        Parca(2, "1. GİRİŞ > 1.1 Alt başlık", "alt başlık metni"),
    ]


def test_ust_seviye_baslik_alt_basliklari_sifirlar():
    sayfalar = [["1. BİR", "1.1 Alt", "metin a", "2. İKİ", "metin b"]]
    assert [p.bolum for p in parcala(sayfalar)] == ["1. BİR > 1.1 Alt", "2. İKİ"]


def test_uzun_bolum_ortusen_pencerelere_bolunur():
    kelimeler = [f"k{i}" for i in range(250)]
    parcalar = parcala([[" ".join(kelimeler)]], en_fazla_kelime=120, ortusme=30)

    pencereler = [p.icerik.split() for p in parcalar]
    assert [len(p) for p in pencereler] == [120, 120, 70]
    for onceki, sonraki in zip(pencereler, pencereler[1:], strict=False):
        assert onceki[-30:] == sonraki[:30]
    assert sorted({k for p in pencereler for k in p}) == sorted(kelimeler)


def test_gercek_kilavuzda_her_parca_sinir_icinde():
    parcalar = parcala(pdf_sayfalari(KILAVUZLAR / "PRES-BK-01.pdf"))
    assert all(1 <= p.sayfa <= 9 for p in parcalar)
    assert all(0 < len(p.icerik.split()) <= 120 for p in parcalar)
    ilk_kontrol = [p for p in parcalar if p.sayfa == 4]
    assert any("hidrolik basınç sensörüdür" in p.icerik for p in ilk_kontrol)
