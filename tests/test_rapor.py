"""Vardiya sonu raporu: sayı denetimi, raporun verileri, LLM'li ve LLM'siz yorum."""

import json
import random
from datetime import datetime, time, timedelta

import httpx
import openai
import psycopg
import pytest

from app import rapor
from app.db import TZ
from app.main import rapor_llm_getir
from app.models import RaporYorumu
from tests.conftest import SABIT_AN
from tests.test_agent import SenaryoluLLM, cevap_ver
from tests.test_oee import _beklenen

# --- Sayı denetimi (veritabanı gerekmez) -------------------------------------------------

VERI = {
    "vardiya": "29.09.2026, 3. vardiya (23:00-07:00)",
    "hat": "Pres 3",
    "oee": 63.8,
    "durus_dk": 4237,
    "makine": "P3-HP",
}


@pytest.mark.parametrize(
    "metin",
    [
        "OEE %63,8 oldu.",  # Türkçe ondalık
        "OEE %63.8 oldu.",  # İngilizce ondalık
        "4.237 dk duruş",  # Türkçe binlik
        "4,237 dk duruş",  # İngilizce binlik
        "4237 dk",
        "29 Eylül gece vardiyası",  # tarihin parçası
        "29.09.2026",
        "3. vardiya 23:00'te başladı, 07:00'de bitti",
        "Pres 3 hattında P3-HP",
        "Sayı yok.",
    ],
)
def test_verideki_sayilar_kabul_edilir(metin):
    yorum = RaporYorumu(ozet=f"Özet cümlesi: {metin}")
    assert rapor.uydurulmus_sayilar(yorum, rapor.izinli_sayilar(VERI)) == []


@pytest.mark.parametrize(
    ("metin", "uydurma"),
    [
        ("OEE 8 puan düştü.", "8"),  # LLM'in kendi hesapladığı fark
        ("OEE %64 civarında.", "64"),  # yuvarlama
        ("OEE %63,9 oldu.", "63,9"),
        ("4.238 dk duruş", "4.238"),
        ("Hedef %85, OEE %63,8.", "85"),  # veride olmayan hedef
        ("Pres 4 hattında", "4"),
    ],
)
def test_veride_olmayan_sayi_yakalanir(metin, uydurma):
    yorum = RaporYorumu(ozet="Özet cümlesi burada.", dikkat=[metin])
    assert rapor.uydurulmus_sayilar(yorum, rapor.izinli_sayilar(VERI)) == [uydurma]


@pytest.mark.parametrize(
    ("yanit", "sorun"),
    [
        ("Rapor hazır.", "JSON nesnesi yok"),
        ('{"ozet": "kısa"}', "sorunlu alanlar: ozet"),
        ('{"ozet": "Yeterince uzun bir özet.", "dikkat": "metin"}', "sorunlu alanlar: dikkat"),
        ('{"ozet": "OEE %70,1 oldu, hedefin altında."}', "Verilerde olmayan sayılar var: 70,1"),
    ],
    ids=["json-yok", "kisa-ozet", "liste-degil", "uydurma-sayi"],
)
def test_denetim_reddeder_ve_sorunu_soyler(yanit, sorun):
    yorum, mesaj = rapor._denetle(yanit, rapor.izinli_sayilar(VERI))
    assert yorum is None
    assert sorun in mesaj


def test_denetim_kod_blogundaki_json_u_kabul_eder():
    yanit = 'İşte rapor:\n```json\n{"ozet": "OEE %63,8 ile düşük.", "oneriler": ["SMED"]}\n```'
    yorum, sorun = rapor._denetle(yanit, rapor.izinli_sayilar(VERI))
    assert sorun is None
    assert yorum.oneriler == ["SMED"]


# --- Raporun verileri (veritabanı) -------------------------------------------------------


@pytest.fixture(scope="module")
def baglanti(test_veritabani):
    with psycopg.connect(test_veritabani, autocommit=True) as conn:
        yield conn


def _vardiya_baslangiclari(test_verisi) -> list[datetime]:
    return sorted({r["baslangic"] for r in test_verisi["vardiya_uretimi"]})


def _ornek_vardiyalar(test_verisi) -> list[datetime]:
    baslangiclar = _vardiya_baslangiclari(test_verisi)
    return [baslangiclar[-1], *random.Random(3).sample(baslangiclar, 14)]


@pytest.mark.parametrize("sira", range(15))
def test_rapor_verisi_python_hesabiyla_ayni(baglanti, test_verisi, sira):
    baslangic = _ornek_vardiyalar(test_verisi)[sira]
    bitis = baslangic + timedelta(hours=8)
    v = rapor.rapor_verisi(baglanti, baslangic)
    secilen = [r for r in test_verisi["vardiya_uretimi"] if r["baslangic"] == baslangic]
    hat_adi = {h["id"]: h["ad"] for h in test_verisi["hatlar"]}

    assert v["vardiya"] == {7: 1, 15: 2, 23: 3}[baslangic.astimezone(TZ).hour]
    assert v["fabrika"]["planli_sure_dk"] == _beklenen(test_verisi, secilen)["planli_sure_dk"]
    assert v["fabrika"]["oee"] == pytest.approx(_beklenen(test_verisi, secilen)["oee"], abs=6e-5)

    gun = baslangic.astimezone(TZ).date()
    for h in v["hatlar"]:
        hattaki = [r for r in secilen if hat_adi[r["hat_id"]] == h["hat"]]
        assert h["oee"] == pytest.approx(_beklenen(test_verisi, hattaki)["oee"], abs=6e-5)
        once = [
            r
            for r in test_verisi["vardiya_uretimi"]
            if hat_adi[r["hat_id"]] == h["hat"]
            and gun - timedelta(days=7) <= r["baslangic"].astimezone(TZ).date() < gun
        ]
        beklenen_7 = _beklenen(test_verisi, once)["oee"] if once else None
        assert h["son_7_gun_oee"] == pytest.approx(beklenen_7, abs=6e-5)
    oee_sirasi = [h["oee"] for h in v["hatlar"]]
    assert oee_sirasi == sorted(oee_sirasi)  # en düşük hat ilk sırada

    makine_kodu = {m["id"]: m["kod"] for m in test_verisi["makineler"]}
    beklenen_arizalar = [
        (makine_kodu[a["makine_id"]], a["baslangic"], a["bitis"] is None or a["bitis"] > bitis)
        for a in sorted(test_verisi["ariza_kayitlari"], key=lambda a: (a["baslangic"], a["id"]))
        if baslangic <= a["baslangic"] < bitis
    ]
    assert [
        (a["makine_kodu"], a["baslangic"], a["vardiya_sonunda_suruyor"]) for a in v["arizalar"]
    ] == beklenen_arizalar
    assert all((a["sure_dk"] is None) == a["vardiya_sonunda_suruyor"] for a in v["arizalar"])

    vardiya_idleri = {r["id"] for r in secilen}
    sureler = [
        d["sure_dk"] for d in test_verisi["vardiya_duruslari"] if d["vardiya_id"] in vardiya_idleri
    ]
    beklenen_sureler = sorted(sureler, reverse=True)[:8]
    assert [d["sure_dk"] for d in v["duruslar"]] == beklenen_sureler


@pytest.mark.parametrize("sira", range(15))
def test_kural_yorumu_da_sayi_denetiminden_gecer(baglanti, test_verisi, sira):
    """LLM'siz yorum da yalnızca verideki sayıları kullanır (aynı denetimle)."""
    v = rapor.rapor_verisi(baglanti, _ornek_vardiyalar(test_verisi)[sira])
    yorum = rapor.kural_yorumu(v)
    veri = rapor.llm_verisi(v)
    assert rapor.uydurulmus_sayilar(yorum, rapor.izinli_sayilar(veri)) == []
    # Yorumdaki sayımlar veride açıkça var; başka bir alandaki aynı sayıya tesadüfen dayanmaz.
    assert veri["vardiyada_baslayan_ariza_sayisi"] == len(v["arizalar"])
    assert veri["hatti_durduran_ariza_sayisi"] == sum(a["hat_durdu"] for a in v["arizalar"])


def test_kural_yorumu_dusuk_oee_suren_ariza_ve_kritik_stogu_soyler(baglanti, test_verisi):
    v = rapor.rapor_verisi(baglanti, _vardiya_baslangiclari(test_verisi)[-1])
    v["hatlar"][0]["oee"] = 0.5
    v["arizalar"].append(
        {**(v["arizalar"] or [{}])[0], "makine_kodu": "P3-HP", "hat": "Pres 3",
         "ariza_tipi": "hidrolik", "vardiya_sonunda_suruyor": True, "hat_durdu": True}
    )  # fmt: skip
    yorum = rapor.kural_yorumu(v)
    metin = " ".join(yorum.dikkat)
    assert f"{v['hatlar'][0]['hat']}: OEE %50,0" in metin
    assert "P3-HP (Pres 3) hidrolik arızası vardiya sonunda sürüyordu" in metin
    assert "SNS-002" in metin  # test verisinde minimum seviyenin altında
    assert any("sipariş" in o for o in yorum.oneriler)


# --- Uç nokta ---------------------------------------------------------------------------

YORUM = {
    "ozet": "Gece vardiyası genel olarak sakin geçti; presler kalıp değişiminde zaman kaybetti.",
    "dikkat": ["Pres hatlarında kalıp değişimi öne çıkıyor."],
    "oneriler": ["Kalıp değişimi için SMED çalışmasını planlayın."],
}


@pytest.fixture
def rapor_llm(istemci):
    """POST /rapor/vardiya'nın kullandığı LLM'i test süresince değiştirir."""

    def degistir(llm):
        istemci.app.dependency_overrides[rapor_llm_getir] = lambda: llm
        return llm

    yield degistir
    istemci.app.dependency_overrides[rapor_llm_getir] = lambda: None


def _istek_sayisi(istemci) -> tuple[int, int]:
    k = istemci.get("/kullanim").json()
    return k["istek_sayisi"], k["hatali_istek"]


def test_varsayilan_son_tamamlanan_vardiya_llmsiz(istemci, test_verisi):
    oncesi = _istek_sayisi(istemci)
    cevap = istemci.post("/rapor/vardiya")
    assert cevap.status_code == 200, cevap.text
    r = cevap.json()
    son = _vardiya_baslangiclari(test_verisi)[-1]
    assert datetime.fromisoformat(r["baslangic"]) == son
    assert (r["tarih"], r["vardiya"]) == (son.date().isoformat(), 3)
    assert r["yorum_kaynagi"] == "kural"
    assert "ayarlı değil" in r["yorum_notu"]
    assert r["kullanim"]["model"] is None and r["kullanim"]["deneme_sayisi"] == 0
    assert _istek_sayisi(istemci) == oncesi  # LLM'e gidilmediyse kayıt yok
    for h in r["hatlar"]:
        assert f"| {h['hat']} |" in r["markdown"]
    assert r["markdown"].startswith("# Vardiya raporu: 29.09.2026, 3. vardiya (23:00-07:00)")


def test_llm_yorumu_denetimden_gecerse_kullanilir_ve_kaydedilir(istemci, rapor_llm):
    llm = rapor_llm(SenaryoluLLM(cevap_ver(json.dumps(YORUM, ensure_ascii=False))))
    oncesi = _istek_sayisi(istemci)
    r = istemci.post("/rapor/vardiya", json={"tarih": "2026-09-29", "vardiya": 2}).json()
    assert r["yorum"] == YORUM
    assert (r["yorum_kaynagi"], r["yorum_notu"]) == ("llm", None)
    assert r["kullanim"]["deneme_sayisi"] == 1 and r["kullanim"]["model"] == "sahte-model"
    assert YORUM["ozet"] in r["markdown"] and "sayı denetiminden geçti" in r["markdown"]
    assert _istek_sayisi(istemci) == (oncesi[0] + 1, oncesi[1])

    sistem, kullanici = llm.gelen_mesajlar[0]
    assert "Yeni sayı üretme" in sistem["content"]
    veri = json.loads(kullanici["content"])
    assert veri["vardiya"] == "29.09.2026, 2. vardiya (15:00-23:00)"
    assert {h["hat"] for h in veri["hatlar_yuzde"]} == {h["hat"] for h in r["hatlar"]}


def test_uydurma_sayili_yanit_bir_kez_duzelttirilir(istemci, rapor_llm):
    # İki ondalıklı bir fark: modelin kendi hesapladığı türden. (Küçük tam sayılar veride sık
    # geçtiği için uydurulsa bile denetimden kaçabilir; README'de sınır olarak yazıyor.)
    uydurma = {**YORUM, "ozet": "OEE geçen haftaya göre 17,35 puan düştü, dikkat."}
    llm = rapor_llm(
        SenaryoluLLM(
            cevap_ver(json.dumps(uydurma, ensure_ascii=False)),
            cevap_ver(json.dumps(YORUM, ensure_ascii=False)),
        )
    )
    r = istemci.post("/rapor/vardiya", json={"tarih": "2026-09-29", "vardiya": 1}).json()
    assert r["yorum"] == YORUM and r["yorum_kaynagi"] == "llm"
    assert r["kullanim"]["deneme_sayisi"] == 2
    assert "reddedildi" in r["yorum_notu"] and "17,35" in r["yorum_notu"]
    duzeltme = llm.gelen_mesajlar[1][-1]["content"]
    assert "Verilerde olmayan sayılar var: 17,35." in duzeltme


def test_iki_yanit_da_gecmezse_kural_yorumu(istemci, rapor_llm):
    rapor_llm(SenaryoluLLM(cevap_ver("Vardiya iyi geçti."), cevap_ver('{"ozet": "x"}')))
    oncesi = _istek_sayisi(istemci)
    r = istemci.post("/rapor/vardiya").json()
    assert r["yorum_kaynagi"] == "kural"
    assert "denetimden geçmedi" in r["yorum_notu"]
    assert r["kullanim"]["deneme_sayisi"] == 2
    assert r["yorum"]["ozet"].startswith("Vardiyada fabrika OEE'si %")
    assert _istek_sayisi(istemci) == (oncesi[0] + 1, oncesi[1] + 1)  # hatalı istek olarak kayıtlı


def test_llm_hata_verirse_rapor_yine_cikar(istemci, rapor_llm):
    istek = httpx.Request("POST", "https://ornek.test")
    kota = openai.RateLimitError("kota", response=httpx.Response(429, request=istek), body=None)
    rapor_llm(SenaryoluLLM(kota))
    oncesi = _istek_sayisi(istemci)
    cevap = istemci.post("/rapor/vardiya")
    assert cevap.status_code == 200
    r = cevap.json()
    assert r["yorum_kaynagi"] == "kural" and "ulaşılamadı" in r["yorum_notu"]
    assert _istek_sayisi(istemci) == (oncesi[0] + 1, oncesi[1] + 1)


def test_belirli_vardiya_ve_bulunamayan_vardiya(istemci):
    cevap = istemci.post("/rapor/vardiya", json={"tarih": "2026-09-27", "vardiya": 1})
    assert cevap.status_code == 200
    assert datetime.fromisoformat(cevap.json()["baslangic"]) == datetime.combine(
        SABIT_AN.date() - timedelta(days=3), time(7), TZ
    )
    # 27.09.2026 pazar: yalnızca 1. vardiya çalışılır
    pazar = istemci.post("/rapor/vardiya", json={"tarih": "2026-09-27", "vardiya": 3})
    assert pazar.status_code == 404
    assert "pazar 2. ve 3. vardiya yok" in pazar.json()["detail"]
    # Henüz bitmemiş vardiya
    bitmemis = istemci.post("/rapor/vardiya", json={"tarih": "2026-09-30", "vardiya": 1})
    assert bitmemis.status_code == 404
    assert "henüz bitmemiş" in bitmemis.json()["detail"]
