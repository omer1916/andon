from datetime import UTC, datetime, timedelta

import jwt
import psycopg
import pytest

from app.agent import sohbet
from app.auth import TOKEN_SURESI, Kullanici, token_coz, token_uret
from app.tools import AracBaglami
from tests.conftest import BAKIM, OPERATOR, SABIT_AN, TEST_PAROLA, SahteEmbedder, yetki
from tests.test_agent import SenaryoluLLM, arac_iste, arac_sonuclari, cevap_ver

BAKIM_DOKUMANLARI = {"PRES-BK-01", "KR-BK-01"}
# Bakım kılavuzundan birebir alınmış ifade: kelime eşleşmeli sahte embedder'da bile
# en yakın sonuç bakım kılavuzu olur. Operatör için yine de hiç çıkmamalı.
BAKIM_SORUSU = "oransal valf bobininin direnci ölçülür 20-24 ohm dışındaki değerler bobin arızası"


@pytest.mark.parametrize("kullanici_adi", ["operator", "bakim", "  BAKIM "])
def test_giris_basarili_token_doner(istemci, kullanici_adi):
    cevap = istemci.post("/giris", data={"username": kullanici_adi, "password": TEST_PAROLA})
    assert cevap.status_code == 200
    govde = cevap.json()
    assert govde["token_type"] == "bearer"
    kullanici = token_coz(govde["access_token"])
    assert kullanici.kullanici_adi == kullanici_adi.strip().lower() == govde["rol"]


@pytest.mark.parametrize(
    ("kullanici_adi", "parola"), [("bakim", "yanlis-parola"), ("olmayan", TEST_PAROLA)]
)
def test_giris_hatali_bilgiyle_401_ve_ayni_mesaj(istemci, kullanici_adi, parola):
    cevap = istemci.post("/giris", data={"username": kullanici_adi, "password": parola})
    assert cevap.status_code == 401
    # Kullanıcı adının var olup olmadığı mesajdan anlaşılmamalı.
    assert cevap.json()["detail"] == "Kullanıcı adı veya parola hatalı."


@pytest.mark.parametrize("yol", ["/hatlar", "/arizalar", "/ara?soru=pres", "/kullanim"])
def test_token_olmadan_veri_uc_noktalari_401(istemci, yol):
    assert istemci.get(yol, headers={"Authorization": ""}).status_code == 401


def test_saglik_girissiz_acik(istemci):
    assert istemci.get("/saglik", headers={"Authorization": ""}).status_code == 200


def test_chat_token_olmadan_401(istemci):
    cevap = istemci.post("/chat", json={"soru": "merhaba"}, headers={"Authorization": ""})
    assert cevap.status_code == 401


@pytest.mark.parametrize(
    "token",
    [
        # süresi dolmuş
        token_uret(BAKIM, simdi=datetime.now(UTC) - TOKEN_SURESI - timedelta(minutes=1)),
        # başka anahtarla imzalanmış
        jwt.encode(
            {"sub": "bakim", "rol": "bakim", "exp": datetime.now(UTC) + TOKEN_SURESI},
            "baska-bir-anahtar-en-az-otuz-iki-bayt-uzunlukta",
            algorithm="HS256",
        ),
        # imzasız ("alg: none" saldırısı)
        jwt.encode(
            {"sub": "bakim", "rol": "bakim", "exp": datetime.now(UTC) + TOKEN_SURESI},
            None,
            algorithm="none",
        ),
        "rastgele-metin",
    ],
    ids=["suresi-dolmus", "yanlis-imza", "imzasiz", "bozuk"],
)
def test_gecersiz_token_401(istemci, token):
    cevap = istemci.get("/hatlar", headers={"Authorization": f"Bearer {token}"})
    assert cevap.status_code == 401


def test_rol_degistirilmis_token_reddedilir(istemci):
    # Operatör kendi token'ının içindeki rolü "bakim" yapıp imzayı koruyamaz.
    baslik, _, imza = token_uret(OPERATOR).split(".")
    sahte_govde = jwt.utils.base64url_encode(
        jwt.api_jws.json.dumps({"sub": "operator", "rol": "bakim", "exp": 9999999999}).encode()
    ).decode()
    cevap = istemci.get(
        "/hatlar", headers={"Authorization": f"Bearer {baslik}.{sahte_govde}.{imza}"}
    )
    assert cevap.status_code == 401


def test_kullanim_ozeti_yalnizca_bakim_rolune_acik(istemci):
    assert istemci.get("/kullanim", headers=yetki(OPERATOR)).status_code == 403
    assert istemci.get("/kullanim", headers=yetki(BAKIM)).status_code == 200


def test_ara_operatore_bakim_dokumani_dondurmez(istemci):
    bakim = istemci.get("/ara", params={"soru": BAKIM_SORUSU, "k": 10}, headers=yetki(BAKIM))
    operator = istemci.get("/ara", params={"soru": BAKIM_SORUSU, "k": 10}, headers=yetki(OPERATOR))
    assert bakim.json()[0]["dokuman_kodu"] == "PRES-BK-01"
    assert len(operator.json()) == 10  # filtre sıralamadan önce: yine k sonuç döner
    assert not {s["dokuman_kodu"] for s in operator.json()} & BAKIM_DOKUMANLARI


@pytest.mark.parametrize(("kullanici", "gorebilir"), [(OPERATOR, False), (BAKIM, True)])
def test_agent_araci_rol_yetkisine_uyar(test_veritabani, kullanici, gorebilir):
    llm = SenaryoluLLM(arac_iste(("dokuman_ara", {"soru": BAKIM_SORUSU, "k": 5})), cevap_ver("-"))
    with psycopg.connect(test_veritabani, autocommit=True) as conn:
        baglam = AracBaglami(conn=conn, embedder=SahteEmbedder(), kullanici=kullanici)
        sonuc = sohbet("valf bobini", llm, baglam, simdi=SABIT_AN)

    (arac_sonucu,) = arac_sonuclari(llm)
    gorulen = {p["dokuman_kodu"] for p in arac_sonucu["sonuc"]}
    assert bool(gorulen & BAKIM_DOKUMANLARI) is gorebilir
    assert bool({p["dokuman_kodu"] for p in sonuc.kaynaklar} & BAKIM_DOKUMANLARI) is gorebilir
    istem = llm.gelen_mesajlar[0][0]["content"]
    assert ("bakım kılavuzlarını göremez" in istem) is not gorebilir


def test_chat_kaydi_token_sahibinin_adiyla(istemci, test_veritabani):
    from app.main import llm_getir

    istemci.app.dependency_overrides[llm_getir] = lambda: SenaryoluLLM(cevap_ver("merhaba"))
    try:
        cevap = istemci.post(
            "/chat", json={"soru": "kim olarak kayıtlıyım?"}, headers=yetki(OPERATOR)
        )
    finally:
        istemci.app.dependency_overrides.pop(llm_getir)
    assert cevap.status_code == 200
    with psycopg.connect(test_veritabani) as conn:
        kullanici = conn.execute(
            "SELECT kullanici FROM llm_istekleri WHERE soru = 'kim olarak kayıtlıyım?'"
        ).fetchone()[0]
    assert kullanici == "operator"


def test_token_icerigi():
    kullanici = Kullanici("bakim", "Demo Bakım Mühendisi", "bakim")
    assert token_coz(token_uret(kullanici)) == kullanici
