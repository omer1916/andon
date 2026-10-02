"""API girdi doğrulaması: geçersiz her istek 422 ile reddedilmeli, asla 500 üretmemeli."""

import pytest

from tests.test_agent import SenaryoluLLM, cevap_ver

ARIZALAR_GECERSIZ = {
    "tarih-yok-gun": {"baslangic": "2026-02-30"},
    "tarih-bicimi": {"baslangic": "2026/08/01"},
    "tarih-bos": {"baslangic": ""},
    "tarih-metin": {"bitis": "yarin"},
    "ters-aralik": {"baslangic": "2026-09-02", "bitis": "2026-09-01"},
    "limit-negatif": {"limit": -1},
    "limit-sifir": {"limit": 0},
    "limit-buyuk": {"limit": 1001},
    "limit-metin": {"limit": "on"},
    "limit-ondalik": {"limit": 2.5},
    "offset-negatif": {"offset": -1},
    "offset-metin": {"offset": "a"},
    "tip-buyuk-harf": {"ariza_tipi": "HIDROLIK"},
    "tip-bos": {"ariza_tipi": ""},
    "tip-bilinmeyen": {"ariza_tipi": "nukleer"},
    "bilinmeyen-parametre": {"hatt": "Pres 3"},
    "hat-nul": {"hat": "Pres\x003"},
}

OEE_GECERSIZ = {
    "tarih-yok-gun": {"baslangic": "2026-02-30"},
    "tarih-metin": {"bitis": "yarin"},
    "ters-aralik": {"baslangic": "2026-09-02", "bitis": "2026-09-01"},
    "bilinmeyen-parametre": {"grup": "hat"},
    "hat-nul": {"hat": "Pres\x003"},
}

ARA_GECERSIZ = {
    "soru-yok": {},
    "soru-kisa": {"soru": "ab"},
    "soru-uzun": {"soru": "a" * 501},
    "k-sifir": {"soru": "hidrolik", "k": 0},
    "k-buyuk": {"soru": "hidrolik", "k": 11},
    "k-metin": {"soru": "hidrolik", "k": "x"},
    "bilinmeyen-parametre": {"soru": "hidrolik", "limit": 5},
    "soru-nul": {"soru": "hidrolik\x00"},
}

CHAT_GECERSIZ = {
    "bos-govde": {},
    "bos-soru": {"soru": ""},
    "tek-harf": {"soru": "a"},
    "cok-uzun": {"soru": "a" * 2001},
    "sayi": {"soru": 5},
    "liste": {"soru": ["merhaba"]},
    "fazla-alan": {"soru": "merhaba", "rol": "bakim"},
    "nul": {"soru": "mer\x00haba"},
}


@pytest.fixture(scope="module")
def sahte_llm(istemci):
    from app.main import llm_getir

    istemci.app.dependency_overrides[llm_getir] = lambda: SenaryoluLLM(cevap_ver("-"))
    yield
    istemci.app.dependency_overrides.pop(llm_getir, None)


@pytest.mark.parametrize("parametreler", ARIZALAR_GECERSIZ.values(), ids=ARIZALAR_GECERSIZ.keys())
def test_arizalar_gecersiz_parametre_422(istemci, parametreler):
    assert istemci.get("/arizalar", params=parametreler).status_code == 422


@pytest.mark.parametrize("parametreler", OEE_GECERSIZ.values(), ids=OEE_GECERSIZ.keys())
def test_oee_gecersiz_parametre_422(istemci, parametreler):
    assert istemci.get("/oee", params=parametreler).status_code == 422


@pytest.mark.parametrize("parametreler", ARA_GECERSIZ.values(), ids=ARA_GECERSIZ.keys())
def test_ara_gecersiz_parametre_422(istemci, parametreler):
    assert istemci.get("/ara", params=parametreler).status_code == 422


@pytest.mark.parametrize("govde", CHAT_GECERSIZ.values(), ids=CHAT_GECERSIZ.keys())
def test_chat_gecersiz_govde_422(istemci, sahte_llm, govde):
    assert istemci.post("/chat", json=govde).status_code == 422


@pytest.mark.parametrize(
    "istek",
    [
        {"content": "json-degil", "headers": {"Content-Type": "application/json"}},
        {"content": "[1, 2]", "headers": {"Content-Type": "application/json"}},
        {"data": {"soru": "merhaba"}},  # form, JSON değil
    ],
    ids=["bozuk-json", "dizi", "form"],
)
def test_chat_json_olmayan_govde_422(istemci, sahte_llm, istek):
    assert istemci.post("/chat", **istek).status_code == 422


@pytest.mark.parametrize(
    "form",
    [{"username": "bakim"}, {"password": "x"}, {}],
    ids=["parola-yok", "kullanici-yok", "bos"],
)
def test_giris_eksik_alan_422(istemci, form):
    assert istemci.post("/giris", data=form).status_code == 422


def test_giris_json_ile_422(istemci):
    assert istemci.post("/giris", json={"username": "bakim", "password": "x"}).status_code == 422


@pytest.mark.parametrize(
    "parametreler",
    [
        {"limit": 1000},
        {"limit": 1},
        {"offset": 100_000},
        {"hat": "Boya 1", "ariza_tipi": "pnomatik"},
    ],
    ids=["limit-ust-sinir", "limit-alt-sinir", "offset-cok-buyuk", "hat-ve-tip"],
)
def test_arizalar_sinir_degerleri_kabul_edilir(istemci, parametreler):
    cevap = istemci.get("/arizalar", params=parametreler)
    assert cevap.status_code == 200
    if parametreler.get("offset"):
        assert cevap.json()["arizalar"] == []
        assert cevap.json()["toplam"] > 0


@pytest.mark.parametrize(
    "yol", ["/hatlar", "/arizalar", "/oee", "/ara?soru=pres", "/kullanim", "/saglik"]
)
def test_yanlis_http_yontemi_405(istemci, yol):
    assert istemci.post(yol).status_code == 405
