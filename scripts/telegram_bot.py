"""Andon Telegram botunu çalıştırır (uzun yoklama; dışarıya açık bir adres gerekmez).

Kullanım:
    python scripts/telegram_bot.py
    docker compose --profile telegram up -d   # Docker'da, API'nin yanında

Ön koşul: .env'de TELEGRAM_BOT_TOKEN (Telegram'da @BotFather'dan). Veritabanı hazır olmalı
(seed + ingest; Docker'da API servisi açılışta hazırlar).

Döngü: Telegram'dan en fazla ZAMAN_ASIMI saniye yeni mesaj beklenir, gelenler işlenir, ardından
yeni arızalar bildirilir. Yani bir arıza en geç ~ZAMAN_ASIMI saniye sonra bildirilir. Saatte bir
saklama süresi dolan veriler silinir. Günlüğe mesaj içeriği ve token yazılmaz.
"""

import os
import sys
import time
import traceback

import psycopg

from app.ayarlar import ayarlar
from app.db import baglan
from app.embedding import varsayilan_embedder
from app.llm import LLMAyarHatasi, llm_olustur
from app.telegram_api import TelegramAPI, TelegramHatasi
from app.telegram_bot import Bot

ZAMAN_ASIMI = 10  # saniye; arıza bildiriminin en uzun gecikmesi de budur
TEMIZLIK_ARALIGI = 3600  # saniye


def llm_getir():
    try:
        return llm_olustur(ayarlar())
    except LLMAyarHatasi:
        return None


def gunluk(mesaj: str) -> None:
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {mesaj}", flush=True)


def tur(api: TelegramAPI, bot: Bot, offset: int | None) -> int | None:
    """Bir döngü turu: mesajları işle, bildirimleri gönder. Yeni offset'i döner."""
    for guncelleme in api.guncellemeler(offset, ZAMAN_ASIMI):
        offset = guncelleme["update_id"] + 1  # işlenemese bile tekrar alınmasın
        try:
            bot.guncellemeyi_isle(guncelleme)
        except Exception as hata:  # tek bir mesaj botu düşürmesin
            # Hata mesajı kullanıcının yazdığını içerebilir (ör. veritabanı hatası); günlüğe
            # yalnızca hata türü ve kodun neresinde olduğu yazılır.
            yer = traceback.extract_tb(hata.__traceback__)[-1]
            gunluk(
                f"mesaj {guncelleme['update_id']} işlenemedi: {type(hata).__name__} "
                f"({os.path.basename(yer.filename)}:{yer.lineno})"
            )
    gonderilen = bot.bildirimleri_gonder()
    if gonderilen:
        gunluk(f"{gonderilen} arıza bildirimi gönderildi")
    return offset


def main() -> None:
    a = ayarlar()
    if not a.telegram_bot_token:
        sys.exit(
            "TELEGRAM_BOT_TOKEN tanımlı değil. Telegram'da @BotFather'a /newbot yazıp aldığın "
            "token'ı .env dosyasına ekle (bkz. README, Telegram botu)."
        )
    api = TelegramAPI(a.telegram_bot_token)
    try:
        ben = api.ben()
    except TelegramHatasi as hata:
        sys.exit(f"Telegram'a bağlanılamadı ya da token geçersiz: {hata}")
    gunluk(f"@{ben['username']} çalışıyor (bildirim: {a.telegram_bildirim_ayrintisi})")

    try:
        conn = baglan()
    except psycopg.OperationalError as hata:
        sys.exit(f"Veritabanına bağlanılamadı. 'docker compose up -d' çalıştı mı?\n{hata}")
    conn.autocommit = True
    bot = Bot(
        api,
        conn,
        varsayilan_embedder(),
        llm_getir,
        bildirim_ayrintisi=a.telegram_bildirim_ayrintisi,
        fotograf_saklama_gun=a.telegram_fotograf_saklama_gun,
    )
    offset, son_temizlik = None, 0.0
    while True:
        try:
            offset = tur(api, bot, offset)
            if time.monotonic() - son_temizlik > TEMIZLIK_ARALIGI:
                kod, foto = bot.eski_verileri_temizle()
                if kod or foto:
                    gunluk(f"temizlik: {kod} eski kod, {foto} eski fotoğraf silindi")
                son_temizlik = time.monotonic()
        except TelegramHatasi as hata:
            gunluk(f"Telegram hatası: {hata}; 5 sn sonra tekrar")
            time.sleep(5)
        except psycopg.OperationalError:
            gunluk("veritabanı bağlantısı koptu; 5 sn sonra yeniden bağlanılıyor")
            time.sleep(5)
            bot.conn = conn = baglan()
            conn.autocommit = True


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
