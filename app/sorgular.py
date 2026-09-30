"""Veritabanı sorguları. API uç noktaları ve agent araçları bu fonksiyonları kullanır.

Kullanıcıdan gelen her değer parametre olarak geçer, SQL metnine hiçbir zaman eklenmez.
"""

from datetime import date, datetime, time, timedelta

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from app.db import TZ


def _gun_basi(gun: date) -> datetime:
    return datetime.combine(gun, time(), TZ)


def hatlari_getir(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT h.id, h.ad, h.tip, count(m.id) AS makine_sayisi
            FROM hatlar h
            LEFT JOIN makineler m ON m.hat_id = h.id
            GROUP BY h.id
            ORDER BY h.id
            """
        )
        return cur.fetchall()


def hat_adini_bul(conn: psycopg.Connection, ad: str) -> str | None:
    """Hattın veritabanındaki adını döner ("pres 3" -> "Pres 3"); yoksa None."""
    satir = conn.execute(
        "SELECT ad FROM hatlar WHERE lower(ad) = lower(%s)", [ad.strip()]
    ).fetchone()
    return satir[0] if satir else None


def arizalari_getir(
    conn: psycopg.Connection,
    *,
    hat: str | None = None,
    baslangic: date | None = None,
    bitis: date | None = None,
    ariza_tipi: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[int, list[dict]]:
    """Filtreye uyan arızaların toplam sayısını ve istenen sayfasını döner (yeniden eskiye).

    `baslangic` ve `bitis` gün olarak verilir ve ikisi de dahildir; arızanın başladığı
    ana göre filtrelenir.
    """
    kosullar = []
    parametreler: dict = {}
    if hat is not None:
        kosullar.append(sql.SQL("lower(h.ad) = lower(%(hat)s)"))
        parametreler["hat"] = hat.strip()
    if baslangic is not None:
        kosullar.append(sql.SQL("a.baslangic >= %(alt)s"))
        parametreler["alt"] = _gun_basi(baslangic)
    if bitis is not None:
        kosullar.append(sql.SQL("a.baslangic < %(ust)s"))
        parametreler["ust"] = _gun_basi(bitis + timedelta(days=1))
    if ariza_tipi is not None:
        kosullar.append(sql.SQL("a.ariza_tipi = %(ariza_tipi)s"))
        parametreler["ariza_tipi"] = ariza_tipi
    where = sql.SQL(" AND ").join(kosullar) if kosullar else sql.SQL("TRUE")

    kaynak = sql.SQL(
        """
        FROM ariza_kayitlari a
        JOIN makineler m ON m.id = a.makine_id
        JOIN hatlar h    ON h.id = m.hat_id
        WHERE {}
        """
    ).format(where)

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql.SQL("SELECT count(*) AS toplam ") + kaynak, parametreler)
        toplam = cur.fetchone()["toplam"]

        cur.execute(
            sql.SQL(
                """
                SELECT a.id,
                       h.ad  AS hat,
                       m.kod AS makine_kodu,
                       m.ad  AS makine_adi,
                       a.baslangic,
                       a.bitis,
                       round(extract(epoch FROM a.bitis - a.baslangic) / 60)::int AS sure_dk,
                       a.ariza_tipi,
                       a.onem,
                       a.hat_durdu,
                       a.aciklama
                """
            )
            + kaynak
            + sql.SQL("ORDER BY a.baslangic DESC, a.id DESC LIMIT %(limit)s OFFSET %(offset)s"),
            {**parametreler, "limit": limit, "offset": offset},
        )
        return toplam, cur.fetchall()
