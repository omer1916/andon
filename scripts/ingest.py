"""Kılavuz PDF'lerini okur, parçalara böler, vektöre çevirir ve veritabanına yazar.

Kullanım:
    python scripts/ingest.py

data/kilavuzlar/kilavuzlar.json'daki her kılavuz için data/kilavuzlar/<kod>.pdf okunur.
Doküman tabloları her çalıştırmada silinip yeniden kurulur. İlk çalıştırmada embedding
modeli indirilir (~470 MB).
"""

import json
import sys
import time
from pathlib import Path

import psycopg

from app.db import baglan
from app.embedding import Embedder, varsayilan_embedder
from app.rag import embedding_metni, parcala, pdf_sayfalari, vektor_metni

KOK = Path(__file__).resolve().parent.parent
KILAVUZ_KLASORU = KOK / "data" / "kilavuzlar"
SEMA_DOSYASI = KOK / "sql" / "dokumanlar.sql"


def kilavuzlari_oku(klasor: Path = KILAVUZ_KLASORU) -> list[dict]:
    """Kılavuz listesini okur; her kılavuza PDF'ten çıkan parçaları ekler."""
    kilavuzlar = json.loads((klasor / "kilavuzlar.json").read_text(encoding="utf-8"))
    for kilavuz in kilavuzlar:
        kilavuz["dosya"] = f"{kilavuz['kod']}.pdf"
        sayfalar = pdf_sayfalari(klasor / kilavuz["dosya"])
        kilavuz["sayfa_sayisi"] = len(sayfalar)
        kilavuz["parcalar"] = parcala(sayfalar)
    return kilavuzlar


def dokumanlari_yaz(conn: psycopg.Connection, kilavuzlar: list[dict], embedder: Embedder) -> None:
    """Parçaları vektöre çevirir, sonra doküman tablolarını tek transaction'da yeniden kurar."""
    vektorler = {
        k["kod"]: embedder.pasajlari_vektorle(
            [embedding_metni(k["baslik"], p) for p in k["parcalar"]]
        )
        for k in kilavuzlar
    }
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(SEMA_DOSYASI.read_text(encoding="utf-8"))
        for kilavuz in kilavuzlar:
            dokuman_id = cur.execute(
                """
                INSERT INTO dokumanlar (kod, baslik, dosya, erisim, sayfa_sayisi)
                VALUES (%(kod)s, %(baslik)s, %(dosya)s, %(erisim)s, %(sayfa_sayisi)s)
                RETURNING id
                """,
                kilavuz,
            ).fetchone()[0]
            cur.executemany(
                """
                INSERT INTO dokuman_parcalari (dokuman_id, sayfa, bolum, icerik, embedding)
                VALUES (%s, %s, %s, %s, %s::vector)
                """,
                [
                    (dokuman_id, p.sayfa, p.bolum, p.icerik, vektor_metni(v))
                    for p, v in zip(kilavuz["parcalar"], vektorler[kilavuz["kod"]], strict=True)
                ],
            )


def main() -> None:
    baslangic = time.perf_counter()
    kilavuzlar = kilavuzlari_oku()
    print("Embedding modeli yükleniyor...")
    embedder = varsayilan_embedder()
    try:
        with baglan() as conn:
            dokumanlari_yaz(conn, kilavuzlar, embedder)
    except psycopg.OperationalError as hata:
        sys.exit(f"Veritabanına bağlanılamadı. 'docker compose up -d' çalıştı mı?\n{hata}")

    for k in kilavuzlar:
        print(f"  {k['kod']:<11} {k['sayfa_sayisi']:>2} sayfa  {len(k['parcalar']):>3} parça")
    print(f"Tamamlandı ({time.perf_counter() - baslangic:.1f} sn).")


if __name__ == "__main__":
    main()
