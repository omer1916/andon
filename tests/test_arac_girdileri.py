"""Agent araçlarına LLM'in gönderebileceği bozuk ve kötü niyetli argümanlar.

Her durumda araç istisna fırlatmamalı; LLM'in okuyup düzeltebileceği bir hata mesajı dönmeli.
SQL injection denemeleri parametre olarak gittiği için etkisiz kalmalı: veri bozulmamalı.
"""

import json

import psycopg
import pytest

from app.auth import Kullanici
from app.tools import AracBaglami, arac_calistir
from tests.conftest import SahteEmbedder

TARIH = {"baslangic": "2026-08-01", "bitis": "2026-08-31"}
TALEP = {"makine_kodu": "P3-HP", "aciklama": "Basınç düşüyor", "oncelik": "orta"}

# (araç, argümanlar, hata mesajında geçmesi gereken ifade)
GECERSIZ = [
    ("ariza_say", {"hat": "Pres 3", "bitis": "2026-08-31"}, "baslangic: Field required"),
    ("ariza_say", {"hat": "Pres 3", "baslangic": "2026-08-01"}, "bitis: Field required"),
    ("ariza_say", {"baslangic": "2026-13-01", "bitis": "2026-12-31"}, "baslangic"),
    ("ariza_say", {"baslangic": "2026-02-30", "bitis": "2026-03-31"}, "baslangic"),
    ("ariza_say", {"baslangic": "dün", "bitis": "bugün"}, "baslangic"),
    ("ariza_say", {"baslangic": "2026-09-01", "bitis": "2026-08-01"}, "sonra olamaz"),
    ("ariza_say", {**TARIH, "ariza_tipi": "nukleer"}, "ariza_tipi"),
    ("ariza_say", {**TARIH, "ariza_tipi": "HIDROLIK"}, "ariza_tipi"),
    ("ariza_say", {**TARIH, "hat": 3}, "hat"),
    ("ariza_say", {**TARIH, "hat": ["Pres 3"]}, "hat"),
    ("ariza_say", {**TARIH, "hat": "Pres 9"}, "Geçerli hatlar: Pres 1"),
    ("ariza_say", {**TARIH, "hat": ""}, "Geçerli hatlar"),
    ("ariza_say", {**TARIH, "hat": "Pres 3' OR '1'='1"}, "Geçerli hatlar"),
    ("ariza_say", {**TARIH, "hat": "Pres 3\x00"}, "geçersiz karakter"),
    ("ariza_say", {"baslangic": "2025-09-25", "bitis": "2025-10-02"}, "özellikle yılı"),
    ("ariza_say", {"baslangic": "2027-01-01", "bitis": "2027-01-31"}, "arıza kayıtları 2026-"),
    ("dokuman_ara", {}, "soru: Field required"),
    ("dokuman_ara", {"soru": "ab"}, "soru"),
    ("dokuman_ara", {"soru": None}, "soru"),
    ("dokuman_ara", {"soru": "hidrolik", "k": 0}, "k"),
    ("dokuman_ara", {"soru": "hidrolik", "k": 9}, "k"),
    ("dokuman_ara", {"soru": "hidrolik", "k": "üç"}, "k"),
    ("stok_sorgula", {"parca_kodu": 123}, "parca_kodu"),
    ("stok_sorgula", {"sadece_kritik": "belki"}, "sadece_kritik"),
    ("stok_sorgula", {"parca_kodu": "XYZ-999"}, "stokta tanımlı değil"),
    ("stok_sorgula", {"parca_kodu": "' OR 1=1 --"}, "stokta tanımlı değil"),
    ("stok_sorgula", {"parca_kodu": "SNS-002\x00"}, "geçersiz karakter"),
    ("bakim_talebi_olustur", {**TALEP, "makine_kodu": None}, "makine_kodu"),
    ("bakim_talebi_olustur", {k: v for k, v in TALEP.items() if k != "aciklama"}, "aciklama"),
    ("bakim_talebi_olustur", {**TALEP, "aciklama": "kısa"}, "aciklama"),
    ("bakim_talebi_olustur", {**TALEP, "aciklama": "x" * 501}, "aciklama"),
    ("bakim_talebi_olustur", {**TALEP, "oncelik": "acil"}, "oncelik"),
    ("bakim_talebi_olustur", {**TALEP, "oncelik": "YUKSEK"}, "oncelik"),
    ("bakim_talebi_olustur", {k: v for k, v in TALEP.items() if k != "oncelik"}, "oncelik"),
    ("bakim_talebi_olustur", {**TALEP, "makine_kodu": "P9-XX"}, "Geçerli kodlar"),
    (
        "bakim_talebi_olustur",
        {**TALEP, "makine_kodu": "P3-HP'; DROP TABLE hatlar; --"},
        "Geçerli kodlar",
    ),
    ("bakim_talebi_olustur", {**TALEP, "aciklama": "Basınç\x00 düşük"}, "geçersiz karakter"),
]

BOZUK_JSON = ["{", "[]", "null", '"metin"', "{'tek': 'tirnak'}", "42", "{}}"]


def _kimlik(oge) -> str:
    arac, argumanlar, _ = oge
    return f"{arac}-{json.dumps(argumanlar, ensure_ascii=False)[:40]}"


@pytest.fixture(scope="module")
def baglam(test_veritabani):
    with psycopg.connect(test_veritabani, autocommit=True) as conn:
        yield AracBaglami(
            conn=conn, embedder=SahteEmbedder(), kullanici=Kullanici("test-girdi", "T", "bakim")
        )


@pytest.mark.parametrize("oge", GECERSIZ, ids=_kimlik)
def test_gecersiz_arguman_duzeltilebilir_hata_doner(baglam, oge):
    arac, argumanlar, beklenen = oge
    baglam.acilan_talepler.clear()
    cikti = arac_calistir(arac, json.dumps(argumanlar), baglam)
    assert set(cikti) == {"hata"}
    assert beklenen in cikti["hata"]


@pytest.mark.parametrize(
    "arac", ["ariza_say", "dokuman_ara", "stok_sorgula", "bakim_talebi_olustur"]
)
@pytest.mark.parametrize("metin", BOZUK_JSON)
def test_bozuk_json_istisna_firlatmaz(baglam, arac, metin):
    cikti = arac_calistir(arac, metin, baglam)
    assert "Geçersiz argüman" in cikti["hata"]


@pytest.mark.parametrize(
    "soru",
    [
        "'; DROP TABLE dokumanlar; --",
        "hidrolik' UNION SELECT parola_hash FROM kullanicilar --",
        "$$; DELETE FROM stok; $$",
        "\\'; TRUNCATE hatlar CASCADE; --",
    ],
)
def test_sql_injection_denemesi_veriyi_bozmaz(baglam, soru):
    cikti = arac_calistir("dokuman_ara", json.dumps({"soru": soru}), baglam)
    assert "sonuc" in cikti
    assert all("parola" not in json.dumps(s) for s in cikti["sonuc"])
    sayilar = baglam.conn.execute(
        """SELECT (SELECT count(*) FROM hatlar), (SELECT count(*) FROM stok),
                  (SELECT count(*) FROM dokumanlar), (SELECT count(*) FROM kullanicilar)"""
    ).fetchone()
    assert sayilar == (7, 23, 4, 2)


@pytest.mark.parametrize(
    ("arac", "argumanlar"),
    [
        ("ariza_say", TARIH),
        ("ariza_say", {**TARIH, "hat": "pres 3"}),
        ("ariza_say", {**TARIH, "ariza_tipi": "hidrolik"}),
        ("dokuman_ara", {"soru": "hidrolik basınç"}),
        ("dokuman_ara", {"soru": "hidrolik basınç", "k": 8}),
        # Arama metni SQL'e değil yalnızca embedder'a gider; NUL baytı burada zararsızdır.
        ("dokuman_ara", {"soru": "hidrolik\x00basınç"}),
        ("stok_sorgula", {}),
        ("stok_sorgula", {"sadece_kritik": True}),
        ("stok_sorgula", {"parca_kodu": "sns-002"}),
    ],
    ids=lambda d: json.dumps(d, ensure_ascii=False)[:30] if isinstance(d, dict) else d,
)
def test_gecerli_argumanlar_sonuc_doner(baglam, arac, argumanlar):
    cikti = arac_calistir(arac, json.dumps(argumanlar), baglam)
    assert set(cikti) == {"sonuc"}
