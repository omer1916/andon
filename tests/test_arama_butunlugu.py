"""Arama bütünlüğü: kılavuzlardaki her parça için.

- Bakım rolüyle, parçanın kendi embedding metniyle yapılan arama o parçayı ilk sırada bulmalı.
  Bir parça yanlış sayfaya, yanlış dokümana yazıldıysa ya da vektörü kaybolduysa burada yakalanır.
- Operatör rolüyle, bakım kılavuzlarındaki her parçanın birebir metniyle aranınca bile hiçbir
  bakım dokümanı dönmemeli (yetki sızıntısı).

Testler sahte (kelime eşleşmeli) embedder'la çalışır; anlamsal kalite scripts/arama_olc.py ile
ölçülür.
"""

import zlib

import psycopg
import pytest

from app.auth import ROL_ERISIMI
from app.rag import dokuman_ara, embedding_metni
from scripts.ingest import kilavuzlari_oku
from tests.conftest import SahteEmbedder

KILAVUZLAR = kilavuzlari_oku()
PARCALAR = [(k, p) for k in KILAVUZLAR for p in k["parcalar"]]
BAKIM_PARCALARI = [(k, p) for k, p in PARCALAR if k["erisim"] == "bakim"]
BAKIM_KODLARI = {k["kod"] for k in KILAVUZLAR if k["erisim"] == "bakim"}


def _kimlik(oge) -> str:
    kilavuz, parca = oge
    return f"{kilavuz['kod']}-s{parca.sayfa}-{zlib.crc32(parca.icerik.encode()) % 10_000:04d}"


@pytest.fixture(scope="module")
def baglanti(test_veritabani):
    with psycopg.connect(test_veritabani) as conn:
        yield conn


def test_koleksiyon_beklenen_buyuklukte():
    assert len(KILAVUZLAR) == 4
    assert sum(k["sayfa_sayisi"] for k in KILAVUZLAR) == 20
    assert len(PARCALAR) == 67


@pytest.mark.parametrize("oge", PARCALAR, ids=_kimlik)
def test_her_parca_kendi_metniyle_ilk_sirada_bulunur(baglanti, oge):
    kilavuz, parca = oge
    (ilk,) = dokuman_ara(
        baglanti,
        SahteEmbedder(),
        embedding_metni(kilavuz["baslik"], parca),
        k=1,
        erisim=ROL_ERISIMI["bakim"],
    )
    assert (ilk["dokuman_kodu"], ilk["sayfa"], ilk["icerik"]) == (
        kilavuz["kod"],
        parca.sayfa,
        parca.icerik,
    )
    assert ilk["benzerlik"] == pytest.approx(1.0)


@pytest.mark.parametrize("oge", BAKIM_PARCALARI, ids=_kimlik)
def test_operator_bakim_parcasini_birebir_arasa_da_bulamaz(baglanti, oge):
    kilavuz, parca = oge
    sonuclar = dokuman_ara(
        baglanti,
        SahteEmbedder(),
        embedding_metni(kilavuz["baslik"], parca),
        k=10,
        erisim=ROL_ERISIMI["operator"],
    )
    assert len(sonuclar) == 10
    assert not {s["dokuman_kodu"] for s in sonuclar} & BAKIM_KODLARI


@pytest.mark.parametrize(
    "erisim", [[], ["yok"], ["OPERASYON"]], ids=["bos", "bilinmeyen", "buyuk-harf"]
)
def test_gecersiz_erisim_listesi_hicbir_sey_dondurmez(baglanti, erisim):
    assert dokuman_ara(baglanti, SahteEmbedder(), "hidrolik", k=5, erisim=erisim) == []


def test_erisim_parametresi_zorunlu(baglanti):
    with pytest.raises(TypeError):
        dokuman_ara(baglanti, SahteEmbedder(), "hidrolik", k=5)  # type: ignore[call-arg]
