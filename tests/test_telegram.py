"""Telegram botu: eşleştirme, gizlilik, rol, soru sınırı, fotoğraflı talep, arıza bildirimi,
komutlar ve Bot API istemcisi. Gerçek Telegram'a bağlanılmaz; sahte bir istemci kullanılır."""

import json
from datetime import datetime, timedelta

import httpx
import openai
import psycopg
import pytest

from app import sorgular
from app import telegram_bot as tb
from app.db import TZ
from app.telegram_api import MESAJ_SINIRI, TelegramAPI, TelegramHatasi, mesaji_bol
from tests.conftest import OPERATOR, SABIT_AN, SahteEmbedder, yetki
from tests.test_agent import SenaryoluLLM, arac_iste, arac_sonuclari, cevap_ver

BAKIM_SOHBETI, OPERATOR_SOHBETI, YABANCI = 1001, 2002, 9009
OPERASYON_DOKUMANLARI = {"PRES-OT-01", "KAL-PR-01"}


class SahteTelegram:
    def __init__(self):
        self.giden: list[tuple[int, str]] = []
        self.dosyalar: dict[str, bytes] = {}
        self.indirilen: list[str] = []
        self.engelleyen: set[int] = set()

    def guncellemeler(self, offset, zaman_asimi):
        return []

    def mesaj_gonder(self, chat_id, metin):
        if chat_id in self.engelleyen:
            raise TelegramHatasi("sendMessage: Forbidden: bot was blocked by the user")
        self.giden.append((chat_id, metin))

    def yaziyor(self, chat_id):
        pass

    def dosya_indir(self, file_id, en_fazla_bayt):
        self.indirilen.append(file_id)
        return self.dosyalar[file_id]

    def mesajlar(self, chat_id) -> list[str]:
        return [m for c, m in self.giden if c == chat_id]

    def son(self, chat_id) -> str:
        return self.mesajlar(chat_id)[-1]


def guncelleme(chat_id, metin=None, foto=None, tip="private", aciklama=None) -> dict:
    mesaj = {"message_id": 1, "chat": {"id": chat_id, "type": tip}}
    if metin is not None:
        mesaj["text"] = metin
    if foto is not None:
        mesaj["photo"] = foto
        if aciklama:
            mesaj["caption"] = aciklama
    return {"update_id": 1, "message": mesaj}


class Saat:
    def __init__(self):
        self.an = 1000.0

    def __call__(self):
        return self.an


@pytest.fixture
def conn(test_veritabani):
    with psycopg.connect(test_veritabani, autocommit=True) as baglanti:
        baglanti.execute("DELETE FROM telegram_baglantilari; DELETE FROM telegram_kodlari")
        yield baglanti


@pytest.fixture
def ortam(conn):
    """Bot, sahte Telegram, sahte saat ve değiştirilebilir LLM."""

    class Ortam:
        api = SahteTelegram()
        saat = Saat()
        llm = None

        def bot(self, **ayarlar):
            return tb.Bot(
                self.api, conn, SahteEmbedder(), lambda: self.llm, saat=self.saat,
                simdi=lambda: SABIT_AN, **ayarlar,
            )  # fmt: skip

        def bagla(self, bot, kullanici_adi, chat_id):
            kod = tb.kod_uret(conn, kullanici_adi, simdi=SABIT_AN)
            bot.guncellemeyi_isle(guncelleme(chat_id, f"/baglan {kod}"))
            assert "Bağlandı" in self.api.son(chat_id)

    return Ortam()


# --- Eşleştirme ve gizlilik -----------------------------------------------------------------


@pytest.mark.parametrize(
    "istek",
    [
        guncelleme(YABANCI, "Pres 3'te geçen ay kaç arıza oldu?"),
        guncelleme(YABANCI, "/rapor"),
        guncelleme(YABANCI, "/plan"),
        guncelleme(YABANCI, "/oee Pres 3"),
        guncelleme(YABANCI, "/gizlilik"),
        guncelleme(YABANCI, foto=[{"file_id": "f1", "file_size": 10}], aciklama="P3-HP kaçak"),
    ],
    ids=["soru", "rapor", "plan", "oee", "gizlilik", "fotograf"],
)
def test_eslesmemis_sohbete_tanitimdan_baska_bir_sey_gitmez(ortam, istek):
    llm = ortam.llm = SenaryoluLLM(cevap_ver("gizli veri"))
    ortam.bot().guncellemeyi_isle(istek)
    assert ortam.api.mesajlar(YABANCI) == [tb.TANITIM]
    assert llm.gelen_mesajlar == [] and ortam.api.indirilen == []


@pytest.mark.parametrize("tip", ["group", "supergroup", "channel"])
def test_grup_ve_kanal_mesajlari_yok_sayilir(ortam, conn, tip):
    bot = ortam.bot()
    kod = tb.kod_uret(conn, "bakim", simdi=SABIT_AN)
    for metin in (f"/baglan {kod}", "Pres 3 kaç arıza?", "/plan"):
        bot.guncellemeyi_isle(guncelleme(-500, metin, tip=tip))
    assert ortam.api.giden == []
    assert not tb.bagli_mi(conn, "bakim")


def test_kod_tek_kullanimlik_ve_ozeti_saklanir(ortam, conn):
    kod = tb.kod_uret(conn, "bakim", simdi=SABIT_AN)
    assert kod.isdigit() and len(kod) == 6
    (ozet,) = conn.execute("SELECT kod_ozeti FROM telegram_kodlari").fetchone()
    assert ozet == tb.kod_ozeti(kod) and kod not in ozet  # kodun kendisi saklanmaz

    bot = ortam.bot()
    bot.guncellemeyi_isle(guncelleme(BAKIM_SOHBETI, f"/baglan {kod}"))
    bagli = ortam.api.son(BAKIM_SOHBETI)
    assert "Bağlandı: <b>Demo Bakım Mühendisi</b>" in bagli
    assert "uçtan uca şifreli değildir" in bagli and "/gizlilik" in bagli
    bot.guncellemeyi_isle(guncelleme(YABANCI, f"/baglan {kod}"))
    assert "geçersiz" in ortam.api.son(YABANCI)
    assert conn.execute("SELECT count(*) FROM telegram_kodlari").fetchone()[0] == 0


def test_tek_tikla_baglanti_start_parametresiyle(ortam, conn):
    kod = tb.kod_uret(conn, "operator", simdi=SABIT_AN)
    ortam.bot().guncellemeyi_isle(guncelleme(OPERATOR_SOHBETI, f"/start {kod}"))
    assert "Bağlandı" in ortam.api.son(OPERATOR_SOHBETI)


def test_suresi_dolmus_kod_kabul_edilmez(ortam, conn):
    kod = tb.kod_uret(conn, "bakim", simdi=SABIT_AN - tb.KOD_GECERLILIK - timedelta(seconds=1))
    ortam.bot().guncellemeyi_isle(guncelleme(BAKIM_SOHBETI, f"/baglan {kod}"))
    assert "süresi dolmuş" in ortam.api.son(BAKIM_SOHBETI)
    assert not tb.bagli_mi(conn, "bakim")


def test_yanlis_kod_denemesi_sinirli(ortam, conn):
    bot = ortam.bot()
    for yanlis in ("000000", "abc", "1234567", "999999", "111111"):
        bot.guncellemeyi_isle(guncelleme(YABANCI, f"/baglan {yanlis}"))
    kod = tb.kod_uret(conn, "bakim", simdi=SABIT_AN)
    bot.guncellemeyi_isle(guncelleme(YABANCI, f"/baglan {kod}"))  # doğru kod bile reddedilir
    assert "Çok fazla yanlış kod" in ortam.api.son(YABANCI)
    assert not tb.bagli_mi(conn, "bakim")
    ortam.saat.an += tb.KOD_GECERLILIK.total_seconds() + 1
    bot.guncellemeyi_isle(guncelleme(YABANCI, f"/baglan {kod}"))
    assert "Bağlandı" in ortam.api.son(YABANCI)


def test_baska_kullanicinin_kodu_ustune_yazilmaz(conn, monkeypatch):
    """İki kullanıcıya aynı kod düşerse ikinci kod yeniden üretilir; ilk kullanıcının kodu
    başkasının hesabına bağlanmaz."""
    sirali = iter([123456, 123456, 654321])
    monkeypatch.setattr(tb.secrets, "randbelow", lambda _: next(sirali))
    assert tb.kod_uret(conn, "bakim", simdi=SABIT_AN) == "123456"
    assert tb.kod_uret(conn, "operator", simdi=SABIT_AN) == "654321"
    sahibi = conn.execute(
        "SELECT kullanici_adi FROM telegram_kodlari WHERE kod_ozeti = %s", [tb.kod_ozeti("123456")]
    ).fetchone()[0]
    assert sahibi == "bakim"


def test_yeni_sohbete_baglaninca_eski_sohbet_duser(ortam):
    bot = ortam.bot()
    ortam.bagla(bot, "bakim", BAKIM_SOHBETI)
    ortam.bagla(bot, "bakim", YABANCI)
    bot.guncellemeyi_isle(guncelleme(BAKIM_SOHBETI, "/plan"))
    assert ortam.api.son(BAKIM_SOHBETI) == tb.TANITIM


def test_gizlilik_metni_ve_cikis(ortam, conn):
    bot = ortam.bot(fotograf_saklama_gun=30)
    ortam.bagla(bot, "bakim", BAKIM_SOHBETI)
    ortam.llm = SenaryoluLLM(cevap_ver("-"))
    ortam.llm.saglayici = "gemini"
    bot.guncellemeyi_isle(guncelleme(BAKIM_SOHBETI, "/gizlilik"))
    metin = ortam.api.son(BAKIM_SOHBETI)
    for beklenen in ("uçtan uca şifreli değildir", "Google Gemini", "30 gün", "/cikis",
                     "Telefon numaranız"):  # fmt: skip
        assert beklenen in metin

    tb.kod_uret(conn, "bakim", simdi=SABIT_AN)  # bekleyen kod da silinmeli
    bot.guncellemeyi_isle(guncelleme(BAKIM_SOHBETI, "/cikis"))
    assert "silindi" in ortam.api.son(BAKIM_SOHBETI)
    assert not tb.bagli_mi(conn, "bakim")
    assert conn.execute("SELECT count(*) FROM telegram_kodlari").fetchone()[0] == 0
    bot.guncellemeyi_isle(guncelleme(BAKIM_SOHBETI, "Pres 3?"))
    assert ortam.api.son(BAKIM_SOHBETI) == tb.TANITIM


def test_eski_veriler_temizlenir(ortam, conn, test_verisi):
    bot = ortam.bot(fotograf_saklama_gun=90)
    # Sıra önemli: kod_uret yeni kod üretirken süresi geçmiş kodları da siler.
    tb.kod_uret(conn, "operator", simdi=SABIT_AN)  # geçerli
    tb.kod_uret(conn, "bakim", simdi=SABIT_AN - timedelta(hours=1))  # süresi geçmiş
    talep_id = test_verisi["bakim_talepleri"][0]["id"]
    eski, yeni = (
        conn.execute(
            "INSERT INTO talep_fotograflari (talep_id, icerik, mime, eklenme) "
            "VALUES (%s, %s, 'image/jpeg', %s) RETURNING id",
            [talep_id, b"x", SABIT_AN - timedelta(days=gun)],
        ).fetchone()[0]
        for gun in (91, 89)
    )
    assert bot.eski_verileri_temizle() == (1, 1)
    kalan = {r[0] for r in conn.execute("SELECT id FROM talep_fotograflari WHERE id IN (%s, %s)",
                                         [eski, yeni])}  # fmt: skip
    assert kalan == {yeni}
    assert tb.bagli_mi(conn, "operator") is False  # temizlik bağlantıya dokunmaz
    assert conn.execute("SELECT count(*) FROM telegram_kodlari").fetchone()[0] == 1


# --- Soru, rol ve sınırlar --------------------------------------------------------------------


def test_soru_kullanicinin_roluyle_cevaplanir_ve_kaydedilir(ortam, conn):
    bot = ortam.bot()
    ortam.bagla(bot, "operator", OPERATOR_SOHBETI)
    ortam.llm = SenaryoluLLM(
        arac_iste(("dokuman_ara", {"soru": "hidrolik pompa bakım basınç sensörü değişimi"})),
        cevap_ver("Önce **basınç** kontrol edilir."),
    )
    oncesi = conn.execute("SELECT count(*) FROM llm_istekleri WHERE kullanici = 'operator'")
    oncesi = oncesi.fetchone()[0]
    bot.guncellemeyi_isle(guncelleme(OPERATOR_SOHBETI, "Hidrolik pompayı nasıl değiştiririm?"))

    (arac,) = arac_sonuclari(ortam.llm)
    assert {p["dokuman_kodu"] for p in arac["sonuc"]} <= OPERASYON_DOKUMANLARI  # bakım yok
    cevap = ortam.api.son(OPERATOR_SOHBETI)
    assert cevap.startswith("Önce <b>basınç</b> kontrol edilir.")
    sonra = conn.execute("SELECT count(*) FROM llm_istekleri WHERE kullanici = 'operator'")
    assert sonra.fetchone()[0] == oncesi + 1


def test_cevaptaki_html_kacirilir(ortam):
    bot = ortam.bot()
    ortam.bagla(bot, "bakim", BAKIM_SOHBETI)
    ortam.llm = SenaryoluLLM(cevap_ver('<script>alert(1)</script> <a href="x">tık</a> `P3-HP`'))
    bot.guncellemeyi_isle(guncelleme(BAKIM_SOHBETI, "deneme"))
    cevap = ortam.api.son(BAKIM_SOHBETI)
    assert "<script>" not in cevap and "<a " not in cevap
    assert "&lt;script&gt;" in cevap and "<code>P3-HP</code>" in cevap


def test_soru_siniri(ortam):
    bot = ortam.bot()
    ortam.bagla(bot, "bakim", BAKIM_SOHBETI)
    llm = ortam.llm = SenaryoluLLM(cevap_ver("tamam"))
    for _ in range(tb.SORU_SINIRI + 1):
        bot.guncellemeyi_isle(guncelleme(BAKIM_SOHBETI, "soru"))
    assert len(llm.gelen_mesajlar) == tb.SORU_SINIRI
    assert "Dakikada en fazla" in ortam.api.son(BAKIM_SOHBETI)
    ortam.saat.an += tb.SORU_PENCERESI_SN + 1
    bot.guncellemeyi_isle(guncelleme(BAKIM_SOHBETI, "soru"))
    assert ortam.api.son(BAKIM_SOHBETI) == "tamam"


def test_llm_yoksa_ya_da_hata_verirse_anlasilir_mesaj(ortam, conn):
    bot = ortam.bot()
    ortam.bagla(bot, "bakim", BAKIM_SOHBETI)
    bot.guncellemeyi_isle(guncelleme(BAKIM_SOHBETI, "soru"))
    assert "ayarlı değil" in ortam.api.son(BAKIM_SOHBETI)

    istek = httpx.Request("POST", "https://ornek.test")
    ortam.llm = SenaryoluLLM(
        openai.RateLimitError("kota", response=httpx.Response(429, request=istek), body=None)
    )
    bot.guncellemeyi_isle(guncelleme(BAKIM_SOHBETI, "soru"))
    assert "cevap veremiyor" in ortam.api.son(BAKIM_SOHBETI)
    hata = conn.execute(
        "SELECT hata FROM llm_istekleri WHERE kullanici = 'bakim' ORDER BY id DESC LIMIT 1"
    ).fetchone()[0]
    assert "RateLimitError" in hata


# --- Fotoğraflı bakım talebi ------------------------------------------------------------------

FOTO = [{"file_id": "kucuk", "file_size": 100}, {"file_id": "buyuk", "file_size": 2000}]


def test_fotografli_talep_acilir_ve_fotograf_eklenir(ortam, conn):
    bot = ortam.bot()
    ortam.bagla(bot, "operator", OPERATOR_SOHBETI)
    ortam.api.dosyalar["buyuk"] = b"\xff\xd8sahte-jpeg"
    talep = {"makine_kodu": "P3-HP", "aciklama": "Yağ kaçağı var", "oncelik": "yuksek"}
    ortam.llm = SenaryoluLLM(arac_iste(("bakim_talebi_olustur", talep)), cevap_ver("Talep açıldı."))
    bot.guncellemeyi_isle(guncelleme(OPERATOR_SOHBETI, foto=FOTO, aciklama="P3-HP'de yağ kaçağı"))

    assert ortam.api.indirilen == ["buyuk"]  # en büyük boyut indirilir
    assert "P3-HP'de yağ kaçağı" in ortam.llm.gelen_mesajlar[0][1]["content"]
    (talep_sonucu,) = arac_sonuclari(ortam.llm)
    talep_id = talep_sonucu["sonuc"]["talep_id"]
    icerik, olusturan = conn.execute(
        "SELECT f.icerik, t.olusturan FROM talep_fotograflari f "
        "JOIN bakim_talepleri t ON t.id = f.talep_id WHERE f.talep_id = %s",
        [talep_id],
    ).fetchone()
    assert (bytes(icerik), olusturan) == (b"\xff\xd8sahte-jpeg", "operator")
    assert f"#{talep_id}" in ortam.api.son(OPERATOR_SOHBETI)


def test_talep_acilmazsa_fotograf_saklanmaz(ortam, conn):
    bot = ortam.bot()
    ortam.bagla(bot, "bakim", BAKIM_SOHBETI)
    ortam.api.dosyalar["buyuk"] = b"jpeg"
    ortam.llm = SenaryoluLLM(cevap_ver("Hangi makine?"))
    oncesi = conn.execute("SELECT count(*) FROM talep_fotograflari").fetchone()[0]
    bot.guncellemeyi_isle(guncelleme(BAKIM_SOHBETI, foto=FOTO, aciklama="kaçak var"))
    assert "Talep açılmadı" in ortam.api.son(BAKIM_SOHBETI)
    assert conn.execute("SELECT count(*) FROM talep_fotograflari").fetchone()[0] == oncesi


@pytest.mark.parametrize(
    ("foto", "aciklama", "beklenen"),
    [
        (FOTO, None, "altına makine kodunu"),
        ([{"file_id": "dev", "file_size": tb.EN_BUYUK_FOTOGRAF + 1}], "P3-HP", "çok büyük"),
    ],
    ids=["aciklamasiz", "buyuk"],
)
def test_fotograf_kurallari(ortam, foto, aciklama, beklenen):
    bot = ortam.bot()
    ortam.bagla(bot, "bakim", BAKIM_SOHBETI)
    llm = ortam.llm = SenaryoluLLM(cevap_ver("-"))
    bot.guncellemeyi_isle(guncelleme(BAKIM_SOHBETI, foto=foto, aciklama=aciklama))
    assert beklenen in ortam.api.son(BAKIM_SOHBETI)
    assert ortam.api.indirilen == [] and llm.gelen_mesajlar == []


# --- Arıza bildirimi ------------------------------------------------------------------------


@pytest.fixture
def yeni_ariza(conn):
    """Test süresince arıza ekleyen fonksiyon; eklenenler sonda silinir (diğer testler veriyi
    seed'le karşılaştırıyor)."""
    eklenenler = []

    def ekle(makine="P3-HP", tip="hidrolik", hat_durdu=True):
        (ariza_id,) = conn.execute(
            "INSERT INTO ariza_kayitlari (makine_id, baslangic, bitis, ariza_tipi, onem, "
            "hat_durdu, aciklama) SELECT id, %s, %s, %s, 'yuksek', %s, "
            "'Hidrolik basınç set değerinin altına düştü' FROM makineler WHERE kod = %s "
            "RETURNING id",
            [SABIT_AN, SABIT_AN + timedelta(minutes=5), tip, hat_durdu, makine],
        ).fetchone()
        eklenenler.append(ariza_id)
        return ariza_id

    yield ekle
    conn.execute("DELETE FROM ariza_kayitlari WHERE id = ANY(%s)", [eklenenler])


def test_hat_durunca_bakima_ayrintili_operatore_kisa_bildirim(ortam, yeni_ariza):
    bot = ortam.bot()
    ortam.bagla(bot, "bakim", BAKIM_SOHBETI)
    ortam.bagla(bot, "operator", OPERATOR_SOHBETI)
    assert bot.bildirimleri_gonder() == 0  # ilk tur: geçmiş arızalar bildirilmez
    yeni_ariza()
    assert bot.bildirimleri_gonder() == 2

    bakim = ortam.api.son(BAKIM_SOHBETI)
    assert "Pres 3 durdu" in bakim and "P3-HP" in bakim
    assert "Kılavuz (" in bakim and "-BK-01" in bakim  # bakım kılavuzundan alıntı
    assert "HYD-" in bakim and "minimumun altında" in bakim  # HYD-002 kritik
    operator = ortam.api.son(OPERATOR_SOHBETI)
    assert "Pres 3 durdu" in operator
    for gizli in ("Kılavuz", "-BK-01", "HYD-", "s. "):
        assert gizli not in operator
    assert bot.bildirimleri_gonder() == 0  # aynı arıza ikinci kez bildirilmez


def test_kisa_modda_bakima_da_kilavuz_ve_stok_gitmez(ortam, yeni_ariza):
    bot = ortam.bot(bildirim_ayrintisi="kisa")
    ortam.bagla(bot, "bakim", BAKIM_SOHBETI)
    bot.bildirimleri_gonder()
    yeni_ariza()
    assert bot.bildirimleri_gonder() == 1
    mesaj = ortam.api.son(BAKIM_SOHBETI)
    assert "Pres 3 durdu" in mesaj and "Kılavuz" not in mesaj and "HYD-" not in mesaj


def test_hatti_durdurmayan_arizada_ve_engelleyende(ortam, yeni_ariza):
    bot = ortam.bot()
    ortam.bagla(bot, "bakim", BAKIM_SOHBETI)
    ortam.bagla(bot, "operator", OPERATOR_SOHBETI)
    bot.bildirimleri_gonder()
    yeni_ariza(hat_durdu=False)
    assert bot.bildirimleri_gonder() == 0
    ortam.api.engelleyen.add(BAKIM_SOHBETI)  # biri botu engellese de diğerine gider
    yeni_ariza(makine="K1-KR1", tip="yazilim")
    assert bot.bildirimleri_gonder() == 1
    assert "Kaynak 1 durdu" in ortam.api.son(OPERATOR_SOHBETI)


def test_seed_yeniden_kurulunca_eski_arizalar_bildirilmez(ortam, conn):
    bot = ortam.bot()
    ortam.bagla(bot, "bakim", BAKIM_SOHBETI)
    bot.son_ariza_id = 10**9  # seed'den önceki büyük id
    assert bot.bildirimleri_gonder() == 0
    assert bot.son_ariza_id == conn.execute("SELECT max(id) FROM ariza_kayitlari").fetchone()[0]


# --- Komutlar ------------------------------------------------------------------------------


def test_komutlar(ortam):
    bot = ortam.bot()
    ortam.bagla(bot, "bakim", BAKIM_SOHBETI)
    ortam.bagla(bot, "operator", OPERATOR_SOHBETI)

    bot.guncellemeyi_isle(guncelleme(BAKIM_SOHBETI, "/oee"))
    oee = ortam.api.son(BAKIM_SOHBETI)
    assert "Son 7 günde" in oee and all(h in oee for h in ("Pres 3", "Boya 1", "Montaj 1"))
    bot.guncellemeyi_isle(guncelleme(BAKIM_SOHBETI, "/oee pres 3"))
    assert "Pres 3, son 7 gün" in ortam.api.son(BAKIM_SOHBETI)
    bot.guncellemeyi_isle(guncelleme(BAKIM_SOHBETI, "/oee Pres 9"))
    assert "adında hat yok" in ortam.api.son(BAKIM_SOHBETI)

    bot.guncellemeyi_isle(guncelleme(BAKIM_SOHBETI, "/plan 12"))
    plan = ortam.api.son(BAKIM_SOHBETI)
    assert "(12 saat)" in plan and "P3-HP" in plan and "tamirden sonra" in plan
    bot.guncellemeyi_isle(guncelleme(OPERATOR_SOHBETI, "/plan"))
    assert "yalnızca bakım" in ortam.api.son(OPERATOR_SOHBETI)
    bot.guncellemeyi_isle(guncelleme(OPERATOR_SOHBETI, "/yardim"))
    assert "/plan" not in ortam.api.son(OPERATOR_SOHBETI)  # operatöre gösterilmez

    bot.guncellemeyi_isle(guncelleme(BAKIM_SOHBETI, "/rapor"))
    rapor = ortam.api.son(BAKIM_SOHBETI)
    assert rapor.startswith("<b>Vardiya raporu: 29.09.2026, 3. vardiya</b>")
    assert "Yorum kurallarla" in rapor

    bot.guncellemeyi_isle(guncelleme(BAKIM_SOHBETI, "/sil_herseyi"))
    assert "tanımıyorum" in ortam.api.son(BAKIM_SOHBETI)


# --- Biçim ve Bot API istemcisi ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("girdi", "beklenen"),
    [
        ("**kalın** ve `kod`", "<b>kalın</b> ve <code>kod</code>"),
        ("- bir\n* iki", "• bir\n• iki"),
        ("### Başlık", "<b>Başlık</b>"),
        ("*(Not: tamirden sonra)*", "<i>(Not: tamirden sonra)</i>"),
        ("2 * 3 = 6", "2 * 3 = 6"),
        ("a < b & c > d", "a &lt; b &amp; c &gt; d"),
        ('<b onmouseover="x">', '&lt;b onmouseover="x"&gt;'),
    ],
)
def test_telegram_html(girdi, beklenen):
    assert tb.telegram_html(girdi) == beklenen


def test_mesaj_sinira_gore_bolunur():
    satir = "x" * 100
    metin = "\n".join([satir] * 120)  # ~12.000 karakter
    parcalar = mesaji_bol(metin)
    assert len(parcalar) == 3 and all(len(p) <= MESAJ_SINIRI for p in parcalar)
    assert "\n".join(parcalar) == metin  # satır sonlarından bölündü, hiçbir şey kaybolmadı
    assert mesaji_bol("") == [] and mesaji_bol("kısa") == ["kısa"]


TOKEN = "123456:GIZLI-TOKEN-ABC"


def _api(isleyici) -> TelegramAPI:
    return TelegramAPI(TOKEN, httpx.Client(transport=httpx.MockTransport(isleyici)))


def test_api_istekleri_ve_bolme():
    istekler = []

    def isleyici(istek: httpx.Request):
        istekler.append((istek.url.path, json.loads(istek.content)))
        return httpx.Response(200, json={"ok": True, "result": {"username": "andon_bot"}})

    api = _api(isleyici)
    assert api.ben() == {"username": "andon_bot"}
    api.mesaj_gonder(5, "a" * 5000)
    yollar = [y for y, _ in istekler]
    assert yollar[0].endswith("/getMe") and yollar.count(f"/bot{TOKEN}/sendMessage") == 2
    assert all(g["parse_mode"] == "HTML" for y, g in istekler if y.endswith("sendMessage"))


def test_api_hatalarinda_token_sizmaz():
    def reddet(istek):
        return httpx.Response(401, json={"ok": False, "description": "Unauthorized"})

    def kopuk(istek):
        raise httpx.ConnectError(f"bağlanılamadı: {istek.url}", request=istek)

    for isleyici, beklenen in ((reddet, "Unauthorized"), (kopuk, "ConnectError")):
        with pytest.raises(TelegramHatasi) as hata:
            _api(isleyici).ben()
        assert beklenen in str(hata.value) and TOKEN not in str(hata.value)
        assert "GIZLI" not in repr(hata.value) and hata.value.__cause__ is None


def test_api_buyuk_dosyayi_indirmez():
    def isleyici(istek):
        if istek.url.path.endswith("getFile"):
            return httpx.Response(
                200, json={"ok": True, "result": {"file_path": "p/1.jpg", "file_size": 10_000}}
            )
        return httpx.Response(200, content=b"x" * 10_000)

    with pytest.raises(TelegramHatasi, match="çok büyük"):
        _api(isleyici).dosya_indir("f", en_fazla_bayt=5_000)
    assert _api(isleyici).dosya_indir("f", en_fazla_bayt=20_000) == b"x" * 10_000


# --- Döngü ---------------------------------------------------------------------------------


def test_dongu_hatali_mesajda_durmaz_ve_gunluge_icerik_yazmaz(capsys):
    from scripts import telegram_bot as calistirici

    class Api(SahteTelegram):
        def guncellemeler(self, offset, zaman_asimi):
            return [
                guncelleme(1, "GIZLI-ICERIK-1") | {"update_id": 7},
                guncelleme(1, "ikinci") | {"update_id": 8},
            ]

    class Bot:
        islenen: list[int] = []

        def guncellemeyi_isle(self, g):
            if g["update_id"] == 7:
                raise ValueError(g["message"]["text"])
            self.islenen.append(g["update_id"])

        def bildirimleri_gonder(self):
            return 0

    bot = Bot()
    assert calistirici.tur(Api(), bot, None) == 9  # hatalı mesaj tekrar alınmaz
    assert bot.islenen == [8]  # sonraki mesaj yine işlenir
    cikti = capsys.readouterr()
    assert "GIZLI-ICERIK" not in cikti.out + cikti.err
    assert "mesaj 7 işlenemedi: ValueError (test_telegram.py:" in cikti.out


# --- Web uç noktaları ------------------------------------------------------------------------


def test_web_kod_durum_ve_baglanti_silme(istemci, conn, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_KULLANICI_ADI", "andon_test_bot")
    durum = istemci.get("/telegram/durum").json()
    assert durum == {
        "bagli": False,
        "bot_kullanici_adi": "andon_test_bot",
        "bildirim_ayrintisi": "ayrintili",
        "fotograf_saklama_gun": 90,
    }
    kod = istemci.post("/telegram/kod").json()
    assert kod["gecerlilik_dk"] == 10
    assert kod["baglanti"] == f"https://t.me/andon_test_bot?start={kod['kod']}"
    assert tb.eslestir(conn, kod["kod"], BAKIM_SOHBETI, datetime.now(TZ)) == "bakim"
    assert istemci.get("/telegram/durum").json()["bagli"] is True
    assert istemci.get("/telegram/durum", headers=yetki(OPERATOR)).json()["bagli"] is False

    assert istemci.delete("/telegram/baglanti").status_code == 204
    assert istemci.get("/telegram/durum").json()["bagli"] is False


def test_talep_fotografi_yalnizca_bakima_ve_raporda_isaretli(istemci, conn, test_verisi):
    talep_id = test_verisi["bakim_talepleri"][-1]["id"]
    assert istemci.get(f"/talepler/{talep_id}/fotograf").status_code == 404
    conn.execute(
        "INSERT INTO talep_fotograflari (talep_id, icerik, mime) VALUES (%s, %s, 'image/jpeg')",
        [talep_id, b"\xff\xd8foto"],
    )
    cevap = istemci.get(f"/talepler/{talep_id}/fotograf")
    assert cevap.status_code == 200 and cevap.content == b"\xff\xd8foto"
    assert cevap.headers["content-type"] == "image/jpeg"
    assert cevap.headers["cache-control"] == "no-store"
    assert istemci.get(f"/talepler/{talep_id}/fotograf", headers=yetki(OPERATOR)).status_code == 403
    assert istemci.get("/talepler/0/fotograf").status_code == 422

    # En yeni, yüksek öncelikli açık talep raporda ilk sıradadır.
    yeni = sorgular.bakim_talebi_ekle(
        conn, makine_id=1, aciklama="Fotoğraflı deneme", oncelik="yuksek", olusturan="test"
    )
    ilk = istemci.post("/rapor/vardiya").json()["acik_talepler"][0]
    assert (ilk["id"], ilk["fotograf_var"]) == (yeni, False)
    conn.execute(
        "INSERT INTO talep_fotograflari (talep_id, icerik, mime) VALUES (%s, %s, 'image/jpeg')",
        [yeni, b"x"],
    )
    ilk = istemci.post("/rapor/vardiya").json()["acik_talepler"][0]
    assert (ilk["id"], ilk["fotograf_var"]) == (yeni, True)
