"""Asistana komut satırından soru sorar; API'yi çalıştırmaya gerek yoktur.

Kullanım:
    python scripts/sor.py "Pres 3 hattında geçen ay kaç arıza oldu, ilk neye bakmalıyım?"
    python scripts/sor.py --ayrinti "..."    # araçlara giden ve gelen her şeyi de göster

İstek, API'deki gibi llm_istekleri tablosuna kaydedilir.
"""

import argparse
import json
import os
import sys

from app.agent import SohbetHatasi, kaydet, sohbet
from app.auth import Kullanici
from app.ayarlar import ayarlar
from app.db import baglan
from app.embedding import TembelEmbedder
from app.llm import LLMAyarHatasi, llm_olustur
from app.tools import AracBaglami

KULLANICI = "komut-satiri"


def main() -> None:
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    ayrac = argparse.ArgumentParser(description="Asistana soru sorar.")
    ayrac.add_argument("soru")
    ayrac.add_argument(
        "--rol", choices=["operator", "bakim"], default="bakim", help="Kimin gözünden sorulsun"
    )
    ayrac.add_argument("--ayrinti", action="store_true", help="Araç girdi/çıktılarını göster")
    args = ayrac.parse_args()
    kullanici = Kullanici(KULLANICI, f"Komut satırı ({args.rol})", args.rol)

    try:
        llm = llm_olustur(ayarlar())
    except LLMAyarHatasi as hata:
        sys.exit(str(hata))

    with baglan() as conn:
        conn.autocommit = True
        baglam = AracBaglami(conn=conn, embedder=TembelEmbedder(), kullanici=kullanici)
        try:
            sonuc = sohbet(args.soru, llm, baglam)
        except SohbetHatasi as hata:
            kaydet(conn, args.soru, KULLANICI, llm.saglayici, hata.sonuc)
            sys.exit(f"Hata: {hata.sonuc.hata}")
        kaydet(conn, args.soru, KULLANICI, llm.saglayici, sonuc)

    if args.ayrinti:
        for mesaj in sonuc.mesajlar[1:]:
            print(f"--- {mesaj['role']} ---")
            print(json.dumps(mesaj, ensure_ascii=False, indent=2)[:2000])
        print()

    print(sonuc.cevap)
    print("\nAraç çağrıları:")
    for cagri in sonuc.arac_cagrilari:
        durum = f"  HATA: {cagri['hata']}" if cagri["hata"] else ""
        print(f"  - {cagri['ad']}({json.dumps(cagri['argumanlar'], ensure_ascii=False)}){durum}")
    maliyet = f"${sonuc.maliyet_usd:.5f}" if sonuc.maliyet_usd is not None else "bilinmiyor"
    print(  # secscope: ignore SAST-LOG-001 (token sayısı, token değil)
        f"\n{sonuc.model} | {sonuc.adim_sayisi} adım | {sonuc.girdi_token} girdi + "
        f"{sonuc.cikti_token} çıktı token | {maliyet} | {sonuc.sure_ms / 1000:.1f} sn"
    )


if __name__ == "__main__":
    main()
