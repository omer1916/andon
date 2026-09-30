"""Veritabanı bağlantısı."""

import os

import psycopg

VARSAYILAN_URL = "postgresql://andon:andon@localhost:5432/andon"


def veritabani_url() -> str:
    return os.environ.get("DATABASE_URL", VARSAYILAN_URL)


def baglan() -> psycopg.Connection:
    return psycopg.connect(veritabani_url())
