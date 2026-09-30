# Andon

Fabrika verisi ve bakım kılavuzları üzerinde çalışan bir yapay zekâ asistanı.

Operatör ya da bakım mühendisi sohbet ekranına şöyle bir soru yazar:

> Pres 3 hattında geçen ay kaç arıza oldu, bu tip arızada ilk neye bakmalıyım?

Asistan sorunun ilk kısmını veritabanından (PostgreSQL) sayarak, ikinci kısmını bakım
kılavuzlarında (pgvector ile anlamsal arama) arayarak cevaplar ve kaynağını gösterir.

> Andon, fabrikalarda bir hatta sorun olduğunda yanan uyarı ışığı sisteminin adıdır.

## Durum

Geliştirme aşamasında. Haftalık plan:

- [x] Hafta 0: Kurulum
- [ ] Hafta 1: Veritabanı ve sahte veri
- [ ] Hafta 2: API
- [ ] Hafta 3: RAG
- [ ] Hafta 4: LLM ve agent
- [ ] Hafta 5: Güvenlik ve kalite
- [ ] Hafta 6: Arayüz ve sunum

## Geliştirme ortamı

Gerekenler: Python 3.12, Git, Docker Desktop.

```bash
py -3.12 -m venv .venv
.venv\Scripts\activate        # Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
```

Kontroller:

```bash
ruff check .
ruff format --check .
pytest
```

Her iş kendi branch'inde yapılır ve `main`'e pull request ile birleşir.

## Veritabanı

PostgreSQL 17 ve pgvector Docker içinde çalışır. Ayarları değiştirmek istersen
`.env.example` dosyasını `.env` adıyla kopyala.

```bash
docker compose up -d                              # veritabanını başlat (localhost:5432)
python scripts/seed.py                            # tabloları kur, 6 aylık sahte veri üret
docker compose exec db psql -U andon -d andon     # SQL konsolu
```

`seed.py` her çalıştığında tabloları silip yeniden kurar. Aynı veriyi tekrar üretmek için
bitiş anını sabitle: `python scripts/seed.py --son "2026-09-30 12:00"`.

| Tablo | İçerik |
|---|---|
| `hatlar` | Üretim hatları: Pres 1-3, Kaynak 1-2, Montaj 1, Boya 1 |
| `makineler` | Hatlardaki makineler (örn. `P3-HP`: Pres 3 hidrolik presi) |
| `ariza_kayitlari` | Makine arızaları: başlangıç/bitiş, tip, önem, hattı durdurup durdurmadığı |
| `stok` | Yedek parça stoku ve minimum seviyeleri |
| `is_emirleri` | Arıza müdahaleleri ve periyodik bakımlar, kullanılan parça |
| `bakim_talepleri` | Operatörlerin açtığı bakım talepleri; agent da buraya yazacak |

Şema [`sql/schema.sql`](sql/schema.sql) dosyasında. Arıza, iş emri ve bakım talebi
kayıtları hatta değil makineye bağlıdır; hatta `makineler.hat_id` üzerinden ulaşılır.
Böylece bir kaydın makinesi ile hattı birbiriyle çelişemez.

Elle yazılmış örnek sorgular: [`sql/sorular.sql`](sql/sorular.sql).
