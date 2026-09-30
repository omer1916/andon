"""Ortak test hazırlıkları.

API testleri gerçek bir PostgreSQL'e karşı çalışır: `andon_test` veritabanı oluşturulur ve
sabit bir anla üretilen sahte veriyle doldurulur. Beklenen sonuçlar aynı veriden Python'da
hesaplanıp API'nin cevabıyla karşılaştırılır.

Veritabanına ulaşılamazsa bu testler atlanır. ANDON_DB_ZORUNLU=1 verilirse atlanmak yerine
hata verir; CI'da testlerin sessizce atlanmaması için.
"""

import os
from datetime import datetime

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from app.db import BAGLANTI_ZAMAN_ASIMI, TZ
from app.main import uygulama_olustur
from scripts.seed import veri_uret, veritabanina_yaz

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://andon:andon@localhost:5432/andon_test"
)
SABIT_AN = datetime(2026, 9, 30, 12, 0, tzinfo=TZ)


def _veritabanini_olustur(url: str) -> None:
    ad = conninfo_to_dict(url)["dbname"]
    yonetim_url = make_conninfo(url, dbname="postgres", connect_timeout=BAGLANTI_ZAMAN_ASIMI)
    with psycopg.connect(yonetim_url, autocommit=True) as conn:
        if conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", [ad]).fetchone() is None:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(ad)))


@pytest.fixture(scope="session")
def test_verisi():
    return veri_uret(SABIT_AN)


@pytest.fixture(scope="session")
def test_veritabani(test_verisi):
    try:
        _veritabanini_olustur(TEST_DB_URL)
        with psycopg.connect(TEST_DB_URL) as conn:
            veritabanina_yaz(conn, test_verisi)
    except psycopg.OperationalError as hata:
        if os.environ.get("ANDON_DB_ZORUNLU") == "1":
            raise
        pytest.skip(f"Test veritabanına ulaşılamadı, veritabanı testleri atlandı: {hata}")
    return TEST_DB_URL


@pytest.fixture(scope="session")
def istemci(test_veritabani):
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("DATABASE_URL", test_veritabani)
        with TestClient(uygulama_olustur()) as istemci:
            yield istemci
