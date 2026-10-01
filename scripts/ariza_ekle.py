"""Demo için şu an başlayan, hattı durduran bir arıza ekler; Telegram bildirimini denemek için.

Kullanım:
    python scripts/ariza_ekle.py                                   # P3-HP, hidrolik, yüksek
    python scripts/ariza_ekle.py K2-KR1 yazilim orta "Robot pozisyon hatası verdi"

Gerçek bir fabrikada bu kaydı MES (ör. Verimot) yazar. Bot çalışıyorsa ~10 saniye içinde
eşleşmiş Telegram hesaplarına bildirim gider.
"""

import argparse
import sys

import psycopg

from app.db import baglan
from app.models import ArizaTipi, Onem

TIPLER = ArizaTipi.__args__
ONEMLER = Onem.__args__


def main() -> None:
    ayrac = argparse.ArgumentParser(description="Hattı durduran bir demo arızası ekler.")
    ayrac.add_argument("makine", nargs="?", default="P3-HP")
    ayrac.add_argument("tip", nargs="?", default="hidrolik", choices=TIPLER)
    ayrac.add_argument("onem", nargs="?", default="yuksek", choices=ONEMLER)
    ayrac.add_argument("aciklama", nargs="?", default="Hidrolik basınç set değerinin altına düştü")
    a = ayrac.parse_args()
    try:
        with baglan() as conn:
            satir = conn.execute(
                """
                INSERT INTO ariza_kayitlari (makine_id, baslangic, ariza_tipi, onem, hat_durdu,
                                             aciklama)
                SELECT id, now(), %s, %s, true, %s FROM makineler WHERE kod = upper(%s)
                RETURNING id
                """,
                [a.tip, a.onem, a.aciklama, a.makine],
            ).fetchone()
    except psycopg.OperationalError as hata:
        sys.exit(f"Veritabanına bağlanılamadı: {hata}")
    if satir is None:
        sys.exit(f"'{a.makine}' kodlu makine yok.")
    print(f"Arıza #{satir[0]} eklendi: {a.makine.upper()}, {a.tip}, {a.onem}, hattı durdurdu.")


if __name__ == "__main__":
    main()
