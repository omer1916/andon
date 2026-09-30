"""Kılavuz aramasının isabetini gerçek embedding modeliyle ölçer.

Kullanım:
    python scripts/arama_olc.py            # ilk 3 sonuca bakar
    python scripts/arama_olc.py --k 5
    python scripts/arama_olc.py --turkce-karaktersiz   # "ışık" yerine "isik" yazılmış gibi

eval/arama_sorulari.jsonl'deki her soru için arama yapılır ve doğru sayfanın (doküman kodu +
sayfa numarası) ilk k sonuç içinde kaçıncı sırada çıktığına bakılır. Bir soru için birden
fazla sayfa doğru kabul edilebilir. Ön koşul: scripts/ingest.py çalışmış olmalı.

Ölçütler:
- isabet@1: doğru sayfa ilk sırada çıkan soruların oranı
- isabet@k: doğru sayfa ilk k sonuç içinde çıkan soruların oranı
- MRR: doğru sonucun sırasının tersinin ortalaması (1. sıra 1, 2. sıra 0,5, çıkmadıysa 0)
"""

import argparse
import json
from pathlib import Path

from app.db import baglan
from app.embedding import varsayilan_embedder
from app.rag import dokuman_ara

SORU_DOSYASI = Path(__file__).resolve().parent.parent / "eval" / "arama_sorulari.jsonl"
TURKCE_KARAKTERSIZ = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")


def dogru_sirasi(sonuclar: list[dict], dogru: list[str]) -> int | None:
    """Doğru sayfanın 1'den başlayan sırası; ilk k içinde yoksa None."""
    for sira, sonuc in enumerate(sonuclar, start=1):
        if f"{sonuc['dokuman_kodu']}:{sonuc['sayfa']}" in dogru:
            return sira
    return None


def main() -> None:
    ayrac = argparse.ArgumentParser(description="Kılavuz aramasının isabetini ölçer.")
    ayrac.add_argument("--k", type=int, default=3, help="Kaç sonuca bakılsın (varsayılan 3)")
    ayrac.add_argument(
        "--turkce-karaktersiz",
        action="store_true",
        help="Soruları Türkçe karakterleri olmadan (ı->i, ş->s ...) sor",
    )
    args = ayrac.parse_args()

    sorular = [json.loads(s) for s in SORU_DOSYASI.read_text(encoding="utf-8").splitlines()]
    if args.turkce_karaktersiz:
        for soru in sorular:
            soru["soru"] = soru["soru"].translate(TURKCE_KARAKTERSIZ)
    embedder = varsayilan_embedder()
    siralar: list[int | None] = []
    with baglan() as conn:
        for soru in sorular:
            sonuclar = dokuman_ara(conn, embedder, soru["soru"], args.k)
            sira = dogru_sirasi(sonuclar, soru["dogru"])
            siralar.append(sira)
            bulunan = ", ".join(f"{s['dokuman_kodu']}:{s['sayfa']}" for s in sonuclar)
            print(f"{'✓' if sira else '✗'} {sira or '-'}  {soru['soru']}")
            if sira != 1:
                print(f"      doğru: {', '.join(soru['dogru'])}   bulunan: {bulunan}")

    n = len(siralar)
    isabet_1 = sum(s == 1 for s in siralar) / n
    isabet_k = sum(s is not None for s in siralar) / n
    mrr = sum(1 / s for s in siralar if s) / n
    print(
        f"\n{n} soru   isabet@1: {isabet_1:.0%}   isabet@{args.k}: {isabet_k:.0%}   MRR: {mrr:.2f}"
    )


if __name__ == "__main__":
    main()
