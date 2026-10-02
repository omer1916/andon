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


def _uretim_kosullari(
    hat: str | None, baslangic: date | None, bitis: date | None
) -> tuple[sql.Composable, dict]:
    """Vardiya sorgularının WHERE koşulu (v: vardiya_uretimi, h: hatlar). Vardiya, başladığı
    güne sayılır; gece vardiyası (23-07) başladığı günün vardiyasıdır."""
    kosullar = []
    parametreler: dict = {}
    if hat is not None:
        kosullar.append(sql.SQL("lower(h.ad) = lower(%(hat)s)"))
        parametreler["hat"] = hat.strip()
    if baslangic is not None:
        kosullar.append(sql.SQL("v.baslangic >= %(alt)s"))
        parametreler["alt"] = _gun_basi(baslangic)
    if bitis is not None:
        kosullar.append(sql.SQL("v.baslangic < %(ust)s"))
        parametreler["ust"] = _gun_basi(bitis + timedelta(days=1))
    return (sql.SQL(" AND ").join(kosullar) if kosullar else sql.SQL("TRUE")), parametreler


# OEE'nin gruplanabileceği alanlar: (SELECT'e eklenen kolon, GROUP BY ifadesi). Sabit bir
# eşleme; kullanıcı girdisi SQL metnine hiç girmez. Gün, Türkiye saatine göre ayrılır.
_GUN = "timezone(%(tz)s, v.baslangic)::date"
OEE_GRUPLARI = {
    "toplam": None,
    "hat": (sql.SQL("h.ad AS hat"), sql.SQL("v.hat_id, h.ad")),
    "vardiya": (sql.SQL("v.vardiya"), sql.SQL("v.vardiya")),
    "gun": (sql.SQL(f"{_GUN} AS gun"), sql.SQL(_GUN)),
}


def oee_degerleri(satir: dict) -> dict:
    """Süreler ve adetlerden OEE ve bileşenleri.

    Oranlar süre üzerinden tanımlanır:
      kullanılabilirlik = çalışma süresi / planlı süre          (çalışma = planlı - duruş)
      performans        = net süre / çalışma süresi             (net = Σ adet x ideal çevrim)
      kalite            = değerli süre / net süre               (değerli = Σ sağlam x ideal)
      OEE               = değerli süre / planlı süre = A x P x Q
    Tek bir hatta kalite, sağlam adet / toplam adet ile aynıdır. Hatlar birleştirilince kalite
    süreyle ağırlıklanır: 6 saniyelik bir pres parçası 55 saniyelik bir montaj parçasıyla aynı
    ağırlıkta sayılmaz ve fabrika OEE'si hâlâ A x P x Q'ya eşit olur.
    """
    planli, durus = satir["planli_sure_dk"], satir["durus_dk"]
    calisma, net, degerli = planli - durus, satir["net_sure_dk"], satir["degerli_sure_dk"]
    return {
        "vardiya_sayisi": satir["vardiya_sayisi"],
        "planli_sure_dk": planli,
        "durus_dk": durus,
        "toplam_adet": satir["toplam_adet"],
        "hurda_adet": satir["hurda_adet"],
        "kullanilabilirlik": round(calisma / planli, 4) if planli else None,
        "performans": round(net / calisma, 4) if calisma else None,
        "kalite": round(degerli / net, 4) if net else None,
        "oee": round(degerli / planli, 4) if planli else None,
    }


def oee_hesapla(
    conn: psycopg.Connection,
    *,
    hat: str | None = None,
    baslangic: date | None = None,
    bitis: date | None = None,
    grup: str = "toplam",
) -> list[dict]:
    """OEE ve bileşenleri; `grup` ile hatlara, vardiyalara ya da günlere göre ayrılır."""
    where, parametreler = _uretim_kosullari(hat, baslangic, bitis)
    secim = gruplama = sql.SQL("")
    if OEE_GRUPLARI[grup] is not None:
        kolon, ifade = OEE_GRUPLARI[grup]
        secim = kolon + sql.SQL(",")
        gruplama = sql.SQL("GROUP BY {0} ORDER BY {0}").format(ifade)
    if grup == "gun":
        parametreler["tz"] = TZ.key
    sorgu = sql.SQL(
        """
        SELECT {secim}
               count(*)                                                   AS vardiya_sayisi,
               coalesce(sum(v.planli_sure_dk), 0)::int                    AS planli_sure_dk,
               coalesce(sum(d.durus_dk), 0)::int                          AS durus_dk,
               coalesce(sum(v.toplam_adet), 0)::int                       AS toplam_adet,
               coalesce(sum(v.hurda_adet), 0)::int                        AS hurda_adet,
               coalesce(sum(v.toplam_adet * h.ideal_cevrim_sn), 0)::float / 60 AS net_sure_dk,
               coalesce(sum((v.toplam_adet - v.hurda_adet) * h.ideal_cevrim_sn), 0)::float / 60
                                                                          AS degerli_sure_dk
        FROM vardiya_uretimi v
        JOIN hatlar h ON h.id = v.hat_id
        LEFT JOIN (
            SELECT vardiya_id, sum(sure_dk) AS durus_dk
            FROM vardiya_duruslari GROUP BY vardiya_id
        ) d ON d.vardiya_id = v.id
        WHERE {where}
        {gruplama}
        """
    ).format(secim=secim, where=where, gruplama=gruplama)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sorgu, parametreler)
        satirlar = cur.fetchall()
    sonuc = []
    for satir in satirlar:
        anahtar = {k: satir[k] for k in ("hat", "vardiya", "gun") if k in satir}
        sonuc.append({**anahtar, **oee_degerleri(satir)})
    return sonuc


def uretim_araligi(conn: psycopg.Connection) -> tuple[date, date] | None:
    """Vardiya kayıtlarının ilk ve son günü (Türkiye saati); kayıt yoksa None."""
    ilk, son = conn.execute(
        "SELECT min(timezone(%(tz)s, baslangic))::date, max(timezone(%(tz)s, baslangic))::date "
        "FROM vardiya_uretimi",
        {"tz": TZ.key},
    ).fetchone()
    return None if ilk is None else (ilk, son)


def durus_pareto(
    conn: psycopg.Connection,
    *,
    hat: str | None = None,
    baslangic: date | None = None,
    bitis: date | None = None,
) -> list[dict]:
    """Duruş nedenleri, süreye göre büyükten küçüğe (Pareto). Arızalar tipine göre ayrılır.

    `adet`: arızada farklı arıza sayısı (iki vardiyaya taşan arıza bir kez sayılır), diğer
    nedenlerde olay sayısı.
    """
    where, parametreler = _uretim_kosullari(hat, baslangic, bitis)
    sorgu = sql.SQL(
        """
        SELECT d.neden,
               a.ariza_tipi,
               (count(DISTINCT d.ariza_id) + count(*) FILTER (WHERE d.ariza_id IS NULL))::int
                                       AS adet,
               sum(d.sure_dk)::int     AS sure_dk
        FROM vardiya_duruslari d
        JOIN vardiya_uretimi v ON v.id = d.vardiya_id
        JOIN hatlar h          ON h.id = v.hat_id
        LEFT JOIN ariza_kayitlari a ON a.id = d.ariza_id
        WHERE {}
        GROUP BY d.neden, a.ariza_tipi
        ORDER BY sum(d.sure_dk) DESC, d.neden, a.ariza_tipi
        """
    ).format(where)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sorgu, parametreler)
        satirlar = cur.fetchall()
    toplam = sum(s["sure_dk"] for s in satirlar)
    birikimli = 0
    for satir in satirlar:
        birikimli += satir["sure_dk"]
        satir["pay"] = round(satir["sure_dk"] / toplam, 4)
        satir["kumulatif_pay"] = round(birikimli / toplam, 4)
    return satirlar


def durduran_makineler(
    conn: psycopg.Connection,
    *,
    hat: str | None = None,
    baslangic: date | None = None,
    bitis: date | None = None,
    limit: int = 5,
) -> list[dict]:
    """Arızasıyla hattı en uzun süre durduran makineler."""
    where, parametreler = _uretim_kosullari(hat, baslangic, bitis)
    sorgu = sql.SQL(
        """
        SELECT m.kod AS makine_kodu, m.ad AS makine_adi, h.ad AS hat,
               count(DISTINCT d.ariza_id)::int AS ariza_sayisi,
               sum(d.sure_dk)::int AS sure_dk
        FROM vardiya_duruslari d
        JOIN vardiya_uretimi v  ON v.id = d.vardiya_id
        JOIN hatlar h           ON h.id = v.hat_id
        JOIN ariza_kayitlari a  ON a.id = d.ariza_id
        JOIN makineler m        ON m.id = a.makine_id
        WHERE {}
        GROUP BY m.kod, m.ad, h.ad
        ORDER BY sum(d.sure_dk) DESC, m.kod
        LIMIT %(limit)s
        """
    ).format(where)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sorgu, {**parametreler, "limit": limit})
        return cur.fetchall()


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


def dokuman_getir(conn: psycopg.Connection, kod: str) -> dict | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT kod, baslik, dosya, erisim FROM dokumanlar WHERE kod = %s", [kod])
        return cur.fetchone()


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
