"""OEE: üretim verisinin kuralları, duruşların farklı yoldan hesaplanması ve API'nin sonucunun
SQL kullanmadan Python'da hesaplanan sonuçla aynı olması."""

import calendar
import json
import random
import re
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta

import psycopg
import pytest

from app.auth import Kullanici
from app.db import TZ
from app.tools import AracBaglami, arac_calistir
from scripts.seed import CALISAN_VARDIYALAR, GUN_SAYISI, HATLAR, MOLA_DK, VARDIYA_DK
from tests.conftest import SABIT_AN, SahteEmbedder
from tests.test_seed_ozellikleri import TOHUMLAR, veri

HAT_ADLARI = [ad for ad, _, _ in HATLAR]
AYLAR = [(2026, ay) for ay in range(4, 10)]  # test verisi 30.09.2026'da biten 6 ay
VARDIYA_SAATI = {1: 7, 2: 15, 3: 23}
ORANLAR = ("kullanilabilirlik", "performans", "kalite", "oee")


def _ay(yil: int, ay: int) -> tuple[date, date]:
    return date(yil, ay, 1), date(yil, ay, calendar.monthrange(yil, ay)[1])


def _gun(vardiya: dict) -> date:
    return vardiya["baslangic"].astimezone(TZ).date()


def _hat_adi(v: dict) -> dict[int, str]:
    return {h["id"]: h["ad"] for h in v["hatlar"]}


def _durus(v: dict) -> dict[int, int]:
    toplam: dict[int, int] = defaultdict(int)
    for d in v["vardiya_duruslari"]:
        toplam[d["vardiya_id"]] += d["sure_dk"]
    return toplam


def _secilen(v: dict, hat=None, baslangic=None, bitis=None) -> list[dict]:
    hat_adi = _hat_adi(v)
    return [
        r
        for r in v["vardiya_uretimi"]
        if (hat is None or hat_adi[r["hat_id"]] == hat)
        and (baslangic is None or _gun(r) >= baslangic)
        and (bitis is None or _gun(r) <= bitis)
    ]


def _beklenen(v: dict, vardiyalar: list[dict]) -> dict:
    """OEE, ders kitabı tanımıyla ve SQL kullanmadan:
    kullanılabilirlik = çalışma / planlı, performans = net süre / çalışma,
    kalite = değerli süre / net süre, OEE = değerli süre / planlı."""
    ideal = {h["id"]: h["ideal_cevrim_sn"] for h in v["hatlar"]}
    durus = _durus(v)
    planli = sum(r["planli_sure_dk"] for r in vardiyalar)
    durus_dk = sum(durus[r["id"]] for r in vardiyalar)
    net = sum(r["toplam_adet"] * ideal[r["hat_id"]] for r in vardiyalar) / 60
    degerli = sum((r["toplam_adet"] - r["hurda_adet"]) * ideal[r["hat_id"]] for r in vardiyalar)
    degerli /= 60
    calisma = planli - durus_dk
    return {
        "vardiya_sayisi": len(vardiyalar),
        "planli_sure_dk": planli,
        "durus_dk": durus_dk,
        "toplam_adet": sum(r["toplam_adet"] for r in vardiyalar),
        "hurda_adet": sum(r["hurda_adet"] for r in vardiyalar),
        "kullanilabilirlik": calisma / planli if planli else None,
        "performans": net / calisma if calisma else None,
        "kalite": degerli / net if net else None,
        "oee": degerli / planli if planli else None,
    }


def _ayni(api: dict, beklenen: dict) -> None:
    for alan in ("vardiya_sayisi", "planli_sure_dk", "durus_dk", "toplam_adet", "hurda_adet"):
        assert api[alan] == beklenen[alan], alan
    for alan in ORANLAR:
        if beklenen[alan] is None:
            assert api[alan] is None, alan
        else:  # API oranları 4 haneye yuvarlar
            assert api[alan] == pytest.approx(beklenen[alan], abs=6e-5), alan


def _beklenen_pareto(v: dict, vardiyalar: list[dict]) -> list[dict]:
    idler = {r["id"] for r in vardiyalar}
    tip = {a["id"]: a["ariza_tipi"] for a in v["ariza_kayitlari"]}
    sure: Counter = Counter()
    arizalar: dict = defaultdict(set)
    olay: Counter = Counter()
    for d in v["vardiya_duruslari"]:
        if d["vardiya_id"] not in idler:
            continue
        anahtar = (d["neden"], tip.get(d["ariza_id"]))
        sure[anahtar] += d["sure_dk"]
        if d["ariza_id"] is None:
            olay[anahtar] += 1
        else:
            arizalar[anahtar].add(d["ariza_id"])
    sirali = sorted(sure, key=lambda k: (-sure[k], k[0], k[1] is None, k[1] or ""))
    return [
        {
            "neden": neden,
            "ariza_tipi": ariza_tipi,
            "adet": len(arizalar[(neden, ariza_tipi)]) + olay[(neden, ariza_tipi)],
            "sure_dk": sure[(neden, ariza_tipi)],
        }
        for neden, ariza_tipi in sirali
    ]


def _beklenen_makineler(v: dict, vardiyalar: list[dict], limit: int = 5) -> list[tuple]:
    idler = {r["id"] for r in vardiyalar}
    makine = {a["id"]: a["makine_id"] for a in v["ariza_kayitlari"]}
    kod = {m["id"]: m["kod"] for m in v["makineler"]}
    sure: Counter = Counter()
    arizalar: dict = defaultdict(set)
    for d in v["vardiya_duruslari"]:
        if d["vardiya_id"] in idler and d["ariza_id"] is not None:
            k = kod[makine[d["ariza_id"]]]
            sure[k] += d["sure_dk"]
            arizalar[k].add(d["ariza_id"])
    sirali = sorted(sure, key=lambda k: (-sure[k], k))[:limit]
    return [(k, len(arizalar[k]), sure[k]) for k in sirali]


# --- Seed kuralları (40 tohum) ----------------------------------------------------------


@pytest.mark.parametrize("tohum", TOHUMLAR)
def test_vardiyalar_takvime_uyar(tohum):
    v = veri(tohum)
    beklenen_anahtarlar = set()
    ilk_gun = (SABIT_AN - timedelta(days=GUN_SAYISI - 1)).date()
    for gun_no in range(GUN_SAYISI):
        gun = ilk_gun + timedelta(days=gun_no)
        for no in CALISAN_VARDIYALAR.get(gun.weekday(), (1, 2, 3)):
            bas = datetime.combine(gun, time(VARDIYA_SAATI[no]), TZ)
            if bas + timedelta(minutes=VARDIYA_DK) <= SABIT_AN:
                beklenen_anahtarlar |= {(h["id"], bas) for h in v["hatlar"]}

    anahtarlar = [(r["hat_id"], r["baslangic"]) for r in v["vardiya_uretimi"]]
    assert len(anahtarlar) == len(set(anahtarlar))  # (hat, başlangıç) tekil
    assert set(anahtarlar) == beklenen_anahtarlar  # tamamlanmış her vardiya, eksiksiz
    for r in v["vardiya_uretimi"]:
        yerel = r["baslangic"].astimezone(TZ)
        assert (yerel.hour, yerel.minute) == (VARDIYA_SAATI[r["vardiya"]], 0)
        assert r["bitis"] - r["baslangic"] == timedelta(minutes=VARDIYA_DK)
        assert 0 < r["planli_sure_dk"] <= VARDIYA_DK - MOLA_DK
        assert 0 <= r["hurda_adet"] <= r["toplam_adet"]


@pytest.mark.parametrize("tohum", TOHUMLAR)
def test_duruslar_vardiyaya_ve_arizaya_uyar(tohum):
    v = veri(tohum)
    vardiya = {r["id"]: r for r in v["vardiya_uretimi"]}
    ariza = {a["id"]: a for a in v["ariza_kayitlari"]}
    makine_hatti = {m["id"]: m["hat_id"] for m in v["makineler"]}
    for vardiya_id, toplam in _durus(v).items():
        assert toplam <= vardiya[vardiya_id]["planli_sure_dk"]
    ciftler = set()
    for d in v["vardiya_duruslari"]:
        assert d["sure_dk"] > 0
        assert (d["neden"] == "ariza") == (d["ariza_id"] is not None)
        if d["ariza_id"] is None:
            continue
        r, a = vardiya[d["vardiya_id"]], ariza[d["ariza_id"]]
        assert a["hat_durdu"]
        assert makine_hatti[a["makine_id"]] == r["hat_id"]
        ortusme = min(a["bitis"] or SABIT_AN, r["bitis"]) - max(a["baslangic"], r["baslangic"])
        assert d["sure_dk"] <= ortusme.total_seconds() / 60
        assert (d["vardiya_id"], d["ariza_id"]) not in ciftler
        ciftler.add((d["vardiya_id"], d["ariza_id"]))


@pytest.mark.parametrize("tohum", TOHUMLAR)
def test_performans_yuzde_yuzu_asmaz(tohum):
    v = veri(tohum)
    ideal = {h["id"]: h["ideal_cevrim_sn"] for h in v["hatlar"]}
    durus = _durus(v)
    for r in v["vardiya_uretimi"]:
        calisma = r["planli_sure_dk"] - durus[r["id"]]
        assert r["toplam_adet"] * ideal[r["hat_id"]] / 60 <= calisma


@pytest.mark.parametrize("tohum", TOHUMLAR)
def test_pres_3_oee_en_dusuk_hat(tohum):
    v = veri(tohum)
    oee = {ad: _beklenen(v, _secilen(v, hat=ad))["oee"] for ad in HAT_ADLARI}
    assert min(oee, key=oee.get) == "Pres 3"


@pytest.mark.parametrize("tohum", TOHUMLAR)
def test_pres_3_kalitesi_son_iki_ayda_duser(tohum):
    v = veri(tohum)
    sinir = (SABIT_AN - timedelta(days=60)).date()
    once = _beklenen(v, _secilen(v, hat="Pres 3", bitis=sinir - timedelta(days=1)))
    sonra = _beklenen(v, _secilen(v, hat="Pres 3", baslangic=sinir))
    assert sonra["kalite"] < once["kalite"] - 0.01


@pytest.mark.parametrize("tohum", TOHUMLAR)
def test_gece_vardiyasi_performansi_dusuk(tohum):
    v = veri(tohum)
    performans = {
        no: _beklenen(v, [r for r in v["vardiya_uretimi"] if r["vardiya"] == no])["performans"]
        for no in (1, 2, 3)
    }
    assert performans[3] < min(performans[1], performans[2])


@pytest.mark.parametrize("tohum", TOHUMLAR)
def test_preslerde_en_buyuk_kayip_urun_degisimi(tohum):
    v = veri(tohum)
    for ad in ("Pres 1", "Pres 2", "Pres 3"):
        assert _beklenen_pareto(v, _secilen(v, hat=ad))[0]["neden"] == "urun_degisimi", ad


# --- Duruşun farklı yoldan hesabı: dakika dakika kümelerle ---------------------------------


def _dakikalar(bas: datetime, bit: datetime) -> set[int]:
    return set(range(int(bas.timestamp()) // 60, int(bit.timestamp()) // 60))


@pytest.mark.parametrize("hat_id", range(1, len(HATLAR) + 1))
def test_planli_sure_ve_ariza_durusu_dakika_dakika_ayni(test_verisi, hat_id):
    """Seed aralıklarla çalışır (birleştirme, kesişim). Burada aynı değerler her dakikayı bir
    küme elemanı sayarak hesaplanır: planlı süre = 450 - bakımdaki dakikalar, arıza duruşu =
    hattı durduran arızaların kapsadığı ama bakımda olmayan dakikalar (planlı süreyle sınırlı)."""
    v = test_verisi
    makine_hatti = {m["id"]: m["hat_id"] for m in v["makineler"]}
    ariza_dk: set[int] = set()
    for a in v["ariza_kayitlari"]:
        if a["hat_durdu"] and makine_hatti[a["makine_id"]] == hat_id:
            ariza_dk |= _dakikalar(a["baslangic"], a["bitis"] or SABIT_AN)
    bakim_dk: set[int] = set()
    for e in v["is_emirleri"]:
        if e["tip"] == "periyodik" and makine_hatti[e["makine_id"]] == hat_id:
            bakim_dk |= _dakikalar(e["acilis"], e["kapanis"] or SABIT_AN)
    ariza_durusu: dict[int, int] = defaultdict(int)
    for d in v["vardiya_duruslari"]:
        if d["neden"] == "ariza":
            ariza_durusu[d["vardiya_id"]] += d["sure_dk"]

    for r in v["vardiya_uretimi"]:
        if r["hat_id"] != hat_id:
            continue
        pencere = _dakikalar(r["baslangic"], r["bitis"])
        assert r["planli_sure_dk"] == VARDIYA_DK - MOLA_DK - len(pencere & bakim_dk)
        beklenen = min(len((pencere & ariza_dk) - bakim_dk), r["planli_sure_dk"])
        assert ariza_durusu[r["id"]] == beklenen, r


# --- API, Python'da hesaplanan sonuçla aynı ------------------------------------------------


def _api_ile_karsilastir(istemci, v: dict, hat=None, baslangic=None, bitis=None) -> dict:
    secim = {"hat": hat, "baslangic": baslangic, "bitis": bitis}
    cevap = istemci.get("/oee", params={k: d for k, d in secim.items() if d})
    assert cevap.status_code == 200, cevap.text
    govde = cevap.json()
    secilen = _secilen(v, hat, baslangic, bitis)

    _ayni(govde["toplam"], _beklenen(v, secilen))

    hat_adi = _hat_adi(v)
    hatlar = [ad for ad in HAT_ADLARI if any(hat_adi[r["hat_id"]] == ad for r in secilen)]
    assert [h["hat"] for h in govde["hatlara_gore"]] == hatlar
    for satir in govde["hatlara_gore"]:
        _ayni(satir, _beklenen(v, [r for r in secilen if hat_adi[r["hat_id"]] == satir["hat"]]))

    vardiyalar = sorted({r["vardiya"] for r in secilen})
    assert [s["vardiya"] for s in govde["vardiyalara_gore"]] == vardiyalar
    for satir in govde["vardiyalara_gore"]:
        _ayni(satir, _beklenen(v, [r for r in secilen if r["vardiya"] == satir["vardiya"]]))

    gunler = sorted({_gun(r) for r in secilen})
    assert [date.fromisoformat(s["gun"]) for s in govde["gunluk"]] == gunler
    for satir in govde["gunluk"]:
        gun = date.fromisoformat(satir["gun"])
        _ayni(satir, _beklenen(v, [r for r in secilen if _gun(r) == gun]))

    alanlar = ("neden", "ariza_tipi", "adet", "sure_dk")
    pareto = [{k: d[k] for k in alanlar} for d in govde["duruslar"]]
    assert pareto == _beklenen_pareto(v, secilen)
    if pareto:
        toplam = sum(d["sure_dk"] for d in govde["duruslar"])
        assert toplam == govde["toplam"]["durus_dk"]  # Pareto, OEE'deki duruşla birebir aynı
        assert govde["duruslar"][-1]["kumulatif_pay"] == pytest.approx(1.0)
        for d in govde["duruslar"]:
            assert d["pay"] == pytest.approx(d["sure_dk"] / toplam, abs=6e-5)

    assert [
        (m["makine_kodu"], m["ariza_sayisi"], m["sure_dk"]) for m in govde["makineler"]
    ] == _beklenen_makineler(v, secilen)
    return govde


@pytest.mark.parametrize("ay", AYLAR, ids=lambda a: f"{a[0]}-{a[1]:02d}")
@pytest.mark.parametrize("hat", [None, *HAT_ADLARI], ids=lambda h: h or "fabrika")
def test_oee_api_her_hat_ve_ay_icin_ayni(istemci, test_verisi, hat, ay):
    _api_ile_karsilastir(istemci, test_verisi, hat, *_ay(*ay))


@pytest.mark.parametrize("hat", [None, *HAT_ADLARI], ids=lambda h: h or "fabrika")
def test_oee_api_tum_donem(istemci, test_verisi, hat):
    govde = _api_ile_karsilastir(istemci, test_verisi, hat)
    t = govde["toplam"]
    # Tanımın tutarlılığı: OEE = kullanılabilirlik x performans x kalite
    assert t["oee"] == pytest.approx(t["kullanilabilirlik"] * t["performans"] * t["kalite"], 1e-3)


@pytest.mark.parametrize("tohum", range(20))
def test_oee_api_rastgele_araliklar(istemci, test_verisi, tohum):
    rng = random.Random(tohum)
    hat = rng.choice([None, *HAT_ADLARI])
    baslangic = date(2026, 3, 25) + timedelta(days=rng.randrange(190))
    bitis = baslangic + timedelta(days=rng.randrange(45))
    _api_ile_karsilastir(istemci, test_verisi, hat, baslangic, bitis)


def test_oee_veri_olmayan_aralikta_bos_doner(istemci):
    govde = istemci.get("/oee", params={"baslangic": "2020-01-01", "bitis": "2020-01-31"}).json()
    assert govde["toplam"]["vardiya_sayisi"] == 0
    assert all(govde["toplam"][alan] is None for alan in ORANLAR)
    assert govde["hatlara_gore"] == govde["gunluk"] == govde["duruslar"] == []


def test_oee_hat_adi_yazima_dayanikli_ve_bilinmeyen_hat_404(istemci):
    pres = istemci.get("/oee", params={"hat": "  pres 3 "}).json()["toplam"]
    assert pres == istemci.get("/oee", params={"hat": "Pres 3"}).json()["toplam"]
    cevap = istemci.get("/oee", params={"hat": "Pres 9"})
    assert cevap.status_code == 404
    assert "Geçerli hatlar: Pres 1" in cevap.json()["detail"]


# --- Agent aracı ------------------------------------------------------------------------


@pytest.fixture
def baglam(test_veritabani):
    with psycopg.connect(test_veritabani, autocommit=True) as conn:
        yield AracBaglami(
            conn=conn, embedder=SahteEmbedder(), kullanici=Kullanici("test", "Test", "operator")
        )


def _arac(baglam, **argumanlar) -> dict:
    return arac_calistir("oee_hesapla", json.dumps(argumanlar), baglam)


def test_oee_araci_api_ile_ayni_yuzdeleri_doner(istemci, baglam):
    aralik = {"baslangic": "2026-09-01", "bitis": "2026-09-30"}
    sonuc = _arac(baglam, hat="pres 3", **aralik)["sonuc"]
    api = istemci.get("/oee", params={"hat": "Pres 3", **aralik}).json()
    for alan in ORANLAR:
        assert sonuc[f"{alan}_yuzde"] == round(api["toplam"][alan] * 100, 1)
    assert sonuc["durus_dk"] == api["toplam"]["durus_dk"]
    assert sonuc["vardiyalara_gore_oee_yuzde"] == {
        str(s["vardiya"]): round(s["oee"] * 100, 1) for s in api["vardiyalara_gore"]
    }
    ilk = sonuc["en_buyuk_duruslar"][0]
    assert ilk["neden"].startswith("ürün değişimi")
    assert ilk["sure_dk"] == api["duruslar"][0]["sure_dk"]
    assert len(sonuc["en_cok_durduran_makineler"]) <= 3
    assert "hatlara_gore_oee_yuzde" not in sonuc  # tek hat sorulduğunda gereksiz token


def test_oee_araci_fabrika_genelinde_hatlari_karsilastirir(baglam):
    sonuc = _arac(baglam, baslangic="2026-04-01", bitis="2026-09-30")["sonuc"]
    hatlar = sonuc["hatlara_gore_oee_yuzde"]
    assert list(hatlar) == HAT_ADLARI
    assert min(hatlar, key=hatlar.get) == "Pres 3"
    assert any(d["neden"].startswith("arıza (") for d in sonuc["en_buyuk_duruslar"])


@pytest.mark.parametrize(
    ("argumanlar", "beklenen"),
    [
        ({"hat": "Pres 9", "baslangic": "2026-09-01", "bitis": "2026-09-30"}, "Geçerli hatlar"),
        ({"baslangic": "2026-09-30", "bitis": "2026-09-01"}, "sonra olamaz"),
        ({"baslangic": "2026-09-01"}, "bitis: Field required"),
        ({"baslangic": "2020-01-01", "bitis": "2020-01-31"}, "tamamlanmış vardiya kaydı yok"),
    ],
    ids=["bilinmeyen-hat", "ters-aralik", "bitis-yok", "veri-yok"],
)
def test_oee_araci_duzeltilebilir_hata_doner(baglam, argumanlar, beklenen):
    hata = _arac(baglam, **argumanlar)["hata"]
    assert beklenen in hata


def test_oee_araci_veri_yoksa_veri_araligini_soyler(baglam):
    hata = _arac(baglam, baslangic="2020-01-01", bitis="2020-01-31")["hata"]
    ilk, son = re.search(r"(\d{4}-\d\d-\d\d) ile (\d{4}-\d\d-\d\d)", hata).groups()
    assert ilk == (SABIT_AN - timedelta(days=GUN_SAYISI - 1)).date().isoformat()
    assert son == (SABIT_AN.date() - timedelta(days=1)).isoformat()  # son tamamlanan gece vardiyası
