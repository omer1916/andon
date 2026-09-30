"""Veritabanı sorguları. API uç noktaları ve agent araçları bu fonksiyonları kullanır.

Kullanıcıdan (ya da LLM'den) gelen her değer parametre olarak geçer, SQL metnine hiçbir zaman
eklenmez.
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


def _ariza_kaynagi(
    hat: str | None, baslangic: date | None, bitis: date | None, ariza_tipi: str | None
) -> tuple[sql.Composed, dict]:
    """Arıza sorgularının ortak FROM/WHERE kısmı ve parametreleri.

    `baslangic` ve `bitis` gün olarak verilir ve ikisi de dahildir; arızanın başladığı
    ana göre, Türkiye saatiyle filtrelenir.
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
    return kaynak, parametreler


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
    """Filtreye uyan arızaların toplam sayısını ve istenen sayfasını döner (yeniden eskiye)."""
    kaynak, parametreler = _ariza_kaynagi(hat, baslangic, bitis, ariza_tipi)
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


def ariza_ozeti(
    conn: psycopg.Connection,
    *,
    hat: str | None = None,
    baslangic: date | None = None,
    bitis: date | None = None,
    ariza_tipi: str | None = None,
) -> dict:
    """Filtreye uyan arızaların sayısı, tiplere ve makinelere göre dağılımı."""
    kaynak, parametreler = _ariza_kaynagi(hat, baslangic, bitis, ariza_tipi)
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("SELECT a.ariza_tipi, count(*) ")
            + kaynak
            + sql.SQL("GROUP BY a.ariza_tipi ORDER BY count(*) DESC, a.ariza_tipi"),
            parametreler,
        )
        tiplere_gore = dict(cur.fetchall())
        cur.execute(
            sql.SQL("SELECT m.kod, count(*) ")
            + kaynak
            + sql.SQL("GROUP BY m.kod ORDER BY count(*) DESC, m.kod"),
            parametreler,
        )
        makinelere_gore = dict(cur.fetchall())
    return {
        "toplam": sum(tiplere_gore.values()),
        "tiplere_gore": tiplere_gore,
        "makinelere_gore": makinelere_gore,
    }


def stok_getir(
    conn: psycopg.Connection, *, parca_kodu: str | None = None, sadece_kritik: bool = False
) -> list[dict]:
    """Yedek parça stoku. `sadece_kritik`: yalnızca minimum seviyenin altındakiler."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT parca_kodu, ad, kategori, miktar, min_miktar, birim, konum,
                   miktar < min_miktar AS kritik
            FROM stok
            WHERE (%(kod)s::text IS NULL OR parca_kodu = upper(%(kod)s::text))
              AND (NOT %(kritik)s OR miktar < min_miktar)
            ORDER BY parca_kodu
            """,
            {"kod": parca_kodu.strip() if parca_kodu else None, "kritik": sadece_kritik},
        )
        return cur.fetchall()


def makine_bul(conn: psycopg.Connection, kod: str) -> dict | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT m.id, m.kod, m.ad, h.ad AS hat
            FROM makineler m JOIN hatlar h ON h.id = m.hat_id
            WHERE m.kod = upper(%s)
            """,
            [kod.strip()],
        )
        return cur.fetchone()


def makine_kodlari(conn: psycopg.Connection) -> list[str]:
    return [satir[0] for satir in conn.execute("SELECT kod FROM makineler ORDER BY kod")]


def kullanici_getir(conn: psycopg.Connection, kullanici_adi: str) -> dict | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT kullanici_adi, ad_soyad, rol, parola_hash FROM kullanicilar "
            "WHERE kullanici_adi = %s",
            [kullanici_adi.strip().lower()],
        )
        return cur.fetchone()


def llm_kullanim_ozeti(conn: psycopg.Connection) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT count(*)                                  AS istek_sayisi,
                   count(*) FILTER (WHERE hata IS NOT NULL)  AS hatali_istek,
                   coalesce(sum(girdi_token), 0)             AS toplam_girdi_token,
                   coalesce(sum(cikti_token), 0)             AS toplam_cikti_token,
                   sum(maliyet_usd)::float                   AS toplam_maliyet_usd,
                   round(avg(sure_ms))::int                  AS ortalama_sure_ms,
                   round(percentile_cont(0.95) WITHIN GROUP (ORDER BY sure_ms))::int
                                                             AS p95_sure_ms
            FROM llm_istekleri
            """
        )
        return cur.fetchone()


def bakim_talebi_ekle(
    conn: psycopg.Connection, *, makine_id: int, aciklama: str, oncelik: str, olusturan: str
) -> int:
    satir = conn.execute(
        """
        INSERT INTO bakim_talepleri (makine_id, aciklama, oncelik, olusturan)
        VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        [makine_id, aciklama, oncelik, olusturan],
    ).fetchone()
    return satir[0]
