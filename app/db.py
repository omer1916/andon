"""Veritabanı bağlantısı."""

from zoneinfo import ZoneInfo

import psycopg
from psycopg_pool import ConnectionPool

from app.ayarlar import ayarlar

# Fabrikanın saat dilimi: "geçen ay", "bugün" gibi sınırlar buna göre hesaplanır.
TZ = ZoneInfo("Europe/Istanbul")

# Sunucu cevap vermezse bağlantı denemesi en fazla bu kadar saniye sürsün. Verilmezse
# (örneğin güvenlik duvarı paketleri sessizce düşürdüğünde) deneme dakikalarca asılı kalabilir.
BAGLANTI_ZAMAN_ASIMI = 5


def veritabani_url() -> str:
    return ayarlar().database_url


def baglan() -> psycopg.Connection:
    return psycopg.connect(veritabani_url(), connect_timeout=BAGLANTI_ZAMAN_ASIMI)


def havuz_olustur() -> ConnectionPool:
    """API için bağlantı havuzu. Veritabanı yoksa istek 5 saniye bekleyip hata verir.

    Bağlantılar autocommit modunda: her sorgu kendi transaction'ında çalışır. Agent bir
    isteği cevaplarken LLM'i saniyelerce bekler; bu sırada açık bir transaction tutulmaz ve
    agent'ın açtığı bakım talebi, istek sonradan hata verse bile kaydedilmiş olur.
    """
    return ConnectionPool(
        veritabani_url(),
        kwargs={"connect_timeout": BAGLANTI_ZAMAN_ASIMI, "autocommit": True},
        min_size=1,
        max_size=10,
        timeout=5,
        open=False,
    )
