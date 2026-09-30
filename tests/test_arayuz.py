import pytest

from tests.conftest import BAKIM, OPERATOR, yetki


def test_ana_sayfa_ve_statik_dosyalar_girissiz_sunulur(istemci):
    sayfa = istemci.get("/", headers={"Authorization": ""})
    assert sayfa.status_code == 200
    assert "text/html" in sayfa.headers["content-type"]
    for dosya in ["/static/app.js", "/static/style.css"]:
        assert istemci.get(dosya, headers={"Authorization": ""}).status_code == 200


@pytest.mark.parametrize(
    ("kullanici", "kod", "durum"),
    [
        (BAKIM, "PRES-BK-01", 200),
        (BAKIM, "PRES-OT-01", 200),
        (OPERATOR, "PRES-OT-01", 200),
        (OPERATOR, "PRES-BK-01", 404),  # yetkisiz: dokümanın varlığı da gizlenir
        (BAKIM, "YOK-01", 404),
        (BAKIM, "..%2F..%2F.env", 404),
    ],
)
def test_pdf_rol_yetkisine_uyar(istemci, kullanici, kod, durum):
    cevap = istemci.get(f"/dokumanlar/{kod}/pdf", headers=yetki(kullanici))
    assert cevap.status_code == durum
    if durum == 200:
        assert cevap.headers["content-type"] == "application/pdf"
        assert cevap.content.startswith(b"%PDF")


def test_pdf_girissiz_401(istemci):
    cevap = istemci.get("/dokumanlar/PRES-OT-01/pdf", headers={"Authorization": ""})
    assert cevap.status_code == 401
