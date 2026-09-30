"""Veritabanını 6 aylık sahte fabrika verisiyle doldurur.

Kullanım:
    python scripts/seed.py                            # bugüne kadarki 6 ay
    python scripts/seed.py --son "2026-09-30 12:00"   # sabit bitiş: her seferinde aynı veri

Tabloları silip yeniden kurar; eski veri kaybolur.

Veride bilerek bırakılmış desenler var, sorgu yazarken bunları bulabilmelisin:
- Pres 3 en çok arıza veren hat, orada en sık arıza tipi hidrolik.
- Pres 3'ün hidrolik presinde (P3-HP) son iki ayda arızalar artıyor.
- Hafta sonu, özellikle pazar, üretim az olduğu için arıza da az.
- Birkaç yedek parça minimum stok seviyesinin altında.
"""

import argparse
import math
import random
import sys
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg
from faker import Faker
from psycopg import sql

from app.db import baglan

TZ = ZoneInfo("Europe/Istanbul")
SEMA_DOSYASI = Path(__file__).resolve().parent.parent / "sql" / "schema.sql"
GUN_SAYISI = 183  # yaklaşık 6 ay

# (ad, tip, arıza çarpanı): çarpan 1'den büyükse hat ortalamadan sık arıza verir.
HATLAR = [
    ("Pres 1", "pres", 1.0),
    ("Pres 2", "pres", 0.9),
    ("Pres 3", "pres", 2.2),
    ("Kaynak 1", "kaynak", 1.0),
    ("Kaynak 2", "kaynak", 1.4),
    ("Montaj 1", "montaj", 0.8),
    ("Boya 1", "boya", 1.1),
]

# Hat tipine göre makineler: (kod eki, ad). Makine kodu hat kısaltmasıyla birleşir: P3-HP.
MAKINELER = {
    "pres": [("HP", "Hidrolik Pres"), ("RB", "Rulo Besleme Ünitesi"), ("TR", "Transfer Robotu")],
    "kaynak": [
        ("KR1", "Kaynak Robotu 1"),
        ("KR2", "Kaynak Robotu 2"),
        ("FK", "Fikstür İstasyonu"),
    ],
    "montaj": [("KN", "Konveyör"), ("TT", "Tork Tabancası İstasyonu"), ("TS", "Test Tezgâhı")],
    "boya": [("OI", "Ön İşlem Havuzu"), ("BK", "Boya Kabini"), ("FR", "Kurutma Fırını")],
}

ARIZA_TIPI_AGIRLIKLARI = {
    "pres": {"hidrolik": 40, "mekanik": 25, "elektrik": 15, "sensor": 15, "yazilim": 5},
    "kaynak": {"mekanik": 20, "elektrik": 30, "sensor": 15, "yazilim": 25, "pnomatik": 10},
    "montaj": {"mekanik": 35, "elektrik": 20, "sensor": 20, "yazilim": 10, "pnomatik": 15},
    "boya": {"mekanik": 20, "elektrik": 25, "sensor": 25, "yazilim": 5, "pnomatik": 25},
}

ARIZA_ACIKLAMALARI = {
    "hidrolik": [
        "Hidrolik basınç set değerinin altına düştü",
        "Hidrolik yağ kaçağı tespit edildi",
        "Hidrolik pompa aşırı ısındı",
        "Hidrolik yağ seviyesi düşük",
        "Oransal valf komuta tepki vermiyor",
    ],
    "mekanik": [
        "Kalıp sıkıştı",
        "Rulmandan ses geliyor",
        "Kayış koptu",
        "Zincir dişliden atladı",
        "Bağlantı cıvataları gevşedi",
        "Aşırı titreşim",
    ],
    "elektrik": [
        "Motor sürücüsü arıza verdi",
        "Sigorta attı",
        "Kablo hasarı",
        "Kontaktör yapıştı",
        "Acil stop devresi açık kaldı",
    ],
    "sensor": [
        "Endüktif sensör sinyal vermiyor",
        "Işık bariyeri sebepsiz devreye girdi",
        "Basınç sensörü hatalı değer okuyor",
        "Sıcaklık sensörü kopuk görünüyor",
        "Enkoder hatası",
    ],
    "yazilim": [
        "PLC programı durdu",
        "Robot pozisyon hatası verdi",
        "Operatör paneli (HMI) dondu",
        "Reçete yüklenemedi",
    ],
    "pnomatik": [
        "Hava basıncı düşük",
        "Pnömatik silindir kaçak yapıyor",
        "Valf adası arızası",
        "Vantuz vakum oluşturmuyor",
    ],
}

ONEM_AGIRLIKLARI = {"dusuk": 50, "orta": 35, "yuksek": 15}
ONEM_SURE_MEDYAN_DK = {"dusuk": 20, "orta": 60, "yuksek": 180}
HAT_DURMA_OLASILIGI = {"dusuk": 0.15, "orta": 0.6, "yuksek": 1.0}

TEMEL_ARIZA_ORANI = 0.12  # hafta içi, makine başına günlük beklenen arıza sayısı
GUN_CARPANI = {5: 0.6, 6: 0.2}  # cumartesi, pazar

# (parça kodu, ad, kategori, miktar, min. miktar, birim, konum)
STOK = [
    ("HYD-001", "Hidrolik yağ filtresi", "hidrolik", 14, 6, "adet", "Depo A-1"),
    ("HYD-002", "Hidrolik yağı ISO VG 46", "hidrolik", 180, 200, "litre", "Depo A-1"),
    ("HYD-003", "Oransal valf", "hidrolik", 2, 2, "adet", "Depo A-2"),
    ("HYD-004", "Hidrolik pompa conta seti", "hidrolik", 5, 3, "adet", "Depo A-2"),
    ("HYD-005", "Hidrolik hortum 1/2 inç", "hidrolik", 12, 8, "metre", "Depo A-3"),
    ("MEK-001", "Rulman 6205", "mekanik", 40, 20, "adet", "Depo B-1"),
    ("MEK-002", "Konveyör zinciri", "mekanik", 25, 10, "metre", "Depo B-1"),
    ("MEK-003", "V kayışı SPZ 1250", "mekanik", 3, 6, "adet", "Depo B-2"),
    ("MEK-004", "Kalıp yayı", "mekanik", 30, 15, "adet", "Depo B-2"),
    ("MEK-005", "Cıvata seti M12", "mekanik", 60, 25, "adet", "Depo B-3"),
    ("ELK-001", "Kontaktör 24V", "elektrik", 8, 5, "adet", "Depo C-1"),
    ("ELK-002", "Sigorta 16A", "elektrik", 50, 30, "adet", "Depo C-1"),
    ("ELK-003", "Motor sürücü kartı", "elektrik", 1, 2, "adet", "Depo C-2"),
    ("ELK-004", "Güç kablosu 3x2,5", "elektrik", 100, 50, "metre", "Depo C-3"),
    ("SNS-001", "Endüktif sensör M18", "sensor", 15, 8, "adet", "Depo D-1"),
    ("SNS-002", "Basınç sensörü 0-250 bar", "sensor", 1, 4, "adet", "Depo D-1"),
    ("SNS-003", "Işık bariyeri alıcısı", "sensor", 4, 2, "adet", "Depo D-2"),
    ("SNS-004", "PT100 sıcaklık sensörü", "sensor", 6, 4, "adet", "Depo D-2"),
    ("SNS-005", "Artımlı enkoder", "sensor", 3, 2, "adet", "Depo D-3"),
    ("PNO-001", "Pnömatik silindir Ø50", "pnomatik", 4, 2, "adet", "Depo E-1"),
    ("PNO-002", "Solenoid valf 5/2", "pnomatik", 2, 4, "adet", "Depo E-1"),
    ("PNO-003", "Vakum vantuzu", "pnomatik", 40, 20, "adet", "Depo E-2"),
    ("PNO-004", "Şartlandırıcı (filtre-regülatör)", "pnomatik", 5, 3, "adet", "Depo E-2"),
]

BAKIM_TALEBI_ACIKLAMALARI = [
    "Makineden alışılmadık bir ses geliyor, kontrol edilmeli",
    "Zeminde yağ lekesi var, kaçak olabilir",
    "Periyodik bakım tarihi geçti",
    "Sensör ara ara sinyal kaybediyor",
    "Çevrim süresi uzadı",
    "Koruma kapağının kilidi zor kapanıyor",
    "Panelde tekrar eden uyarı mesajı var",
    "Gövdede aşırı ısınma hissediliyor",
    "Titreşim arttı",
    "Acil stop butonu sıkışıyor",
]

TABLOLAR = ["hatlar", "makineler", "stok", "ariza_kayitlari", "is_emirleri", "bakim_talepleri"]

Kayit = dict[str, object]


def _poisson(rng: random.Random, beklenen: float) -> int:
    """Poisson dağılımından sayı çeker (Knuth yöntemi, küçük değerler için yeterli)."""
    esik = math.exp(-beklenen)
    k, p = 0, rng.random()
    while p > esik:
        k += 1
        p *= rng.random()
    return k


def _agirlikli_sec(rng: random.Random, agirliklar: dict[str, float]) -> str:
    return rng.choices(list(agirliklar), weights=list(agirliklar.values()))[0]


def _numarala(kayitlar: list[Kayit], sira_alani: str) -> list[Kayit]:
    """Kayıtları zamana göre sıralar ve 1'den başlayan id verir."""
    kayitlar.sort(key=lambda k: k[sira_alani])
    return [{"id": i, **k} for i, k in enumerate(kayitlar, start=1)]


def veri_uret(son_an: datetime, tohum: int = 42) -> dict[str, list[Kayit]]:
    """`son_an`'da biten 6 aylık sahte veriyi üretir. Aynı girdiler aynı veriyi verir."""
    rng = random.Random(tohum)
    fake = Faker("tr_TR")
    fake.seed_instance(tohum)
    teknisyenler = [f"{fake.first_name()} {fake.last_name()}" for _ in range(8)]
    operatorler = [f"{fake.first_name()} {fake.last_name()}" for _ in range(12)]

    hatlar: list[Kayit] = []
    makineler: list[Kayit] = []
    hat_carpani: dict[int, float] = {}
    hat_tipi: dict[int, str] = {}
    for hat_id, (ad, tip, carpan) in enumerate(HATLAR, start=1):
        hatlar.append({"id": hat_id, "ad": ad, "tip": tip})
        hat_carpani[hat_id], hat_tipi[hat_id] = carpan, tip
        kisaltma = ad[0] + ad.split()[-1]  # "Pres 3" -> "P3"
        for ek, makine_adi in MAKINELER[tip]:
            makineler.append(
                {
                    "id": len(makineler) + 1,
                    "hat_id": hat_id,
                    "kod": f"{kisaltma}-{ek}",
                    "ad": makine_adi,
                    "kurulum_yili": 2009 if ad == "Pres 3" else rng.randint(2011, 2022),
                }
            )

    stok = [
        {
            "id": i,
            "parca_kodu": kod,
            "ad": ad,
            "kategori": kategori,
            "miktar": miktar,
            "min_miktar": min_miktar,
            "birim": birim,
            "konum": konum,
        }
        for i, (kod, ad, kategori, miktar, min_miktar, birim, konum) in enumerate(STOK, start=1)
    ]
    kategori_parcalari: dict[str, list[int]] = {}
    for parca in stok:
        kategori_parcalari.setdefault(parca["kategori"], []).append(parca["id"])

    ilk_gun = (son_an - timedelta(days=GUN_SAYISI - 1)).date()

    arizalar: list[Kayit] = []
    for gun_no in range(GUN_SAYISI):
        gun = ilk_gun + timedelta(days=gun_no)
        gun_basi = datetime.combine(gun, time(), TZ)
        for makine in makineler:
            oran = (
                TEMEL_ARIZA_ORANI
                * hat_carpani[makine["hat_id"]]
                * GUN_CARPANI.get(gun.weekday(), 1.0)
            )
            tipler = dict(ARIZA_TIPI_AGIRLIKLARI[hat_tipi[makine["hat_id"]]])
            if makine["kod"] == "P3-HP" and gun_no >= GUN_SAYISI - 60:
                oran *= 1.8
                tipler["hidrolik"] *= 2.5

            for _ in range(_poisson(rng, oran)):
                baslangic = gun_basi + timedelta(minutes=rng.randrange(24 * 60))
                if baslangic > son_an:
                    continue
                onem = _agirlikli_sec(rng, ONEM_AGIRLIKLARI)
                tip = _agirlikli_sec(rng, tipler)
                sure_dk = rng.lognormvariate(math.log(ONEM_SURE_MEDYAN_DK[onem]), 0.6)
                bitis = baslangic + timedelta(minutes=max(5, round(sure_dk)))
                arizalar.append(
                    {
                        "makine_id": makine["id"],
                        "baslangic": baslangic,
                        "bitis": bitis if bitis <= son_an else None,
                        "ariza_tipi": tip,
                        "onem": onem,
                        "hat_durdu": rng.random() < HAT_DURMA_OLASILIGI[onem],
                        "aciklama": rng.choice(ARIZA_ACIKLAMALARI[tip]),
                    }
                )
    arizalar = _numarala(arizalar, "baslangic")

    is_emirleri: list[Kayit] = []

    def is_emri_ekle(makine_id, ariza_id, tip, aciklama, acilis, bitis, parca_id, parca_adet):
        # `bitis`: işin fiilen bittiği an; son_an'dan sonraysa iş hâlâ sürüyor demektir.
        if bitis is not None and bitis <= son_an:
            durum, kapanis = "kapali", bitis
        else:
            durum, kapanis = rng.choice(["acik", "devam"]), None
        is_emirleri.append(
            {
                "makine_id": makine_id,
                "ariza_id": ariza_id,
                "tip": tip,
                "aciklama": aciklama,
                "durum": durum,
                "atanan": rng.choice(teknisyenler),
                "acilis": acilis,
                "kapanis": kapanis,
                "parca_id": parca_id,
                "parca_adet": parca_adet,
            }
        )

    for ariza in arizalar:
        if ariza["onem"] == "dusuk" and rng.random() > 0.3:
            continue  # küçük arızaların çoğu iş emri açılmadan operatörce giderilir
        acilis = ariza["baslangic"] + timedelta(minutes=rng.randint(5, 20))
        if acilis > son_an:
            continue
        bitis = None
        if ariza["bitis"] is not None:
            bitis = max(ariza["bitis"], acilis) + timedelta(minutes=rng.randint(10, 60))
        parca_id = parca_adet = None
        parcalar = kategori_parcalari.get(ariza["ariza_tipi"])  # yazılım arızasında parça yok
        if parcalar and rng.random() < 0.5:
            parca_id, parca_adet = rng.choice(parcalar), rng.randint(1, 2)
        is_emri_ekle(
            ariza["makine_id"],
            ariza["id"],
            "ariza",
            f"Arıza müdahalesi: {ariza['aciklama']}",
            acilis,
            bitis,
            parca_id,
            parca_adet,
        )

    for makine in makineler:
        for gun_no in range(rng.randrange(30), GUN_SAYISI, 30):
            gun = ilk_gun + timedelta(days=gun_no)
            if gun.weekday() == 6:
                gun += timedelta(days=1)  # pazar bakım yapılmaz
            acilis = datetime.combine(gun, time(8), TZ)
            if acilis > son_an:
                continue
            bitis = acilis + timedelta(hours=rng.randint(2, 4))
            is_emri_ekle(
                makine["id"], None, "periyodik", "Aylık periyodik bakım", acilis, bitis, None, None
            )
    is_emirleri = _numarala(is_emirleri, "acilis")

    bakim_talepleri: list[Kayit] = []
    makine_agirliklari = [3 if m["kod"].startswith("P3") else 1 for m in makineler]
    for _ in range(30):
        olusturma = son_an - timedelta(minutes=rng.randrange(GUN_SAYISI * 24 * 60))
        if (son_an - olusturma).days < 14:
            durum = _agirlikli_sec(rng, {"acik": 70, "onaylandi": 30})
        else:
            durum = _agirlikli_sec(rng, {"tamamlandi": 60, "onaylandi": 15, "reddedildi": 25})
        bakim_talepleri.append(
            {
                "makine_id": rng.choices(makineler, weights=makine_agirliklari)[0]["id"],
                "aciklama": rng.choice(BAKIM_TALEBI_ACIKLAMALARI),
                "oncelik": _agirlikli_sec(rng, ONEM_AGIRLIKLARI),
                "durum": durum,
                "olusturan": rng.choice(operatorler),
                "olusturma": olusturma,
            }
        )
    bakim_talepleri = _numarala(bakim_talepleri, "olusturma")

    return {
        "hatlar": hatlar,
        "makineler": makineler,
        "stok": stok,
        "ariza_kayitlari": arizalar,
        "is_emirleri": is_emirleri,
        "bakim_talepleri": bakim_talepleri,
    }


def veritabanina_yaz(conn: psycopg.Connection, veri: dict[str, list[Kayit]]) -> None:
    """Şemayı sıfırdan kurar ve veriyi tek transaction içinde yazar."""
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(SEMA_DOSYASI.read_text(encoding="utf-8"))
        for tablo in TABLOLAR:
            kayitlar = veri[tablo]
            kolonlar = list(kayitlar[0])
            ekle = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                sql.Identifier(tablo),
                sql.SQL(", ").join(map(sql.Identifier, kolonlar)),
                sql.SQL(", ").join(map(sql.Placeholder, kolonlar)),
            )
            cur.executemany(ekle, kayitlar)
            # id'leri biz yazdık; sıradaki kayıt (örn. agent'ın açtığı talep) çakışmasın diye
            # kimlik sayacını en büyük id'ye taşı.
            cur.execute(
                sql.SQL(
                    "SELECT setval(pg_get_serial_sequence(%s, 'id'), (SELECT max(id) FROM {}))"
                ).format(sql.Identifier(tablo)),
                [tablo],
            )


def main() -> None:
    ayrac = argparse.ArgumentParser(description="Veritabanını sahte fabrika verisiyle doldurur.")
    ayrac.add_argument(
        "--son", help='Verinin bittiği an, örn. "2026-09-30 12:00". Varsayılan: şimdi'
    )
    ayrac.add_argument("--tohum", type=int, default=42, help="Rastgele sayı tohumu (varsayılan 42)")
    args = ayrac.parse_args()

    if args.son:
        son_an = datetime.fromisoformat(args.son).replace(tzinfo=TZ)
    else:
        son_an = datetime.now(TZ).replace(second=0, microsecond=0)

    veri = veri_uret(son_an, args.tohum)
    try:
        with baglan() as conn:
            veritabanina_yaz(conn, veri)
    except psycopg.OperationalError as hata:
        sys.exit(f"Veritabanına bağlanılamadı. 'docker compose up -d' çalıştı mı?\n{hata}")

    print(f"Veri {son_an:%Y-%m-%d %H:%M} anında bitecek şekilde yazıldı:")
    for tablo in TABLOLAR:
        print(f"  {tablo:<16} {len(veri[tablo]):>5} kayıt")


if __name__ == "__main__":
    main()
