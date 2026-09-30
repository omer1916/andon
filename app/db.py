"""Veritabanı bağlantısı."""

import os
from zoneinfo import ZoneInfo

import psycopg
from psycopg_pool import ConnectionPool

VARSAYILAN_URL = "postgresql://andon:andon@localhost:5432/andon"

# Fabrikanın saat dilimi: "geçen ay", "bugün" gibi sınırlar buna göre hesaplanır.
TZ = ZoneInfo("Europe/Istanbul")

# Sunucu cevap vermezse bağlantı denemesi en fazla bu kadar saniye sürsün. Verilmezse
# (örneğin güvenlik duvarı paketleri sessizce düşürdüğünde) deneme dakikalarca asılı kalabilir.
BAGLANTI_ZAMAN_ASIMI = 5


def veritabani_url() -> str:
    return os.environ.get("DATABASE_URL", VARSAYILAN_URL)


def baglan() -> psycopg.Connection:
    return psycopg.connect(veritabani_url(), connect_timeout=BAGLANTI_ZAMAN_ASIMI)


def havuz_olustur() -> ConnectionPool:
    """API için bağlantı havuzu. Veritabanı yoksa istek 5 saniye bekleyip hata verir."""
    return ConnectionPool(
        veritabani_url(),
        kwargs={"connect_timeout": BAGLANTI_ZAMAN_ASIMI},
        min_size=1,
        max_size=10,
        timeout=5,
        open=False,
    )
