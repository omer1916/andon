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
- [x] Hafta 1: Veritabanı ve sahte veri
- [x] Hafta 2: API
- [x] Hafta 3: RAG
- [ ] Hafta 4: LLM ve agent
- [ ] Hafta 5: Güvenlik ve kalite
- [ ] Hafta 6: Arayüz ve sunum

## Geliştirme ortamı

Gerekenler: Python 3.12, Git, Docker Desktop.

```bash
py -3.12 -m venv .venv
.venv\Scripts\activate        # Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"      # PyTorch (CPU) dahil, ilk kurulum birkaç dakika sürer
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

## API

```bash
uvicorn app.main:app --reload
```

Uç noktalar http://localhost:8000/docs adresinden denenebilir.

| Uç nokta | Ne döner |
|---|---|
| `GET /saglik` | Servis ve veritabanı durumu; veritabanına ulaşılamıyorsa 503 |
| `GET /hatlar` | Üretim hatları ve her hattaki makine sayısı |
| `GET /arizalar` | Arızalar, yeniden eskiye; `hat`, `baslangic`, `bitis`, `ariza_tipi`, `limit`, `offset` ile filtrelenir |

Demo sorusunun ilk yarısı ("Pres 3 hattında geçen ay kaç arıza oldu?"):

```
GET /arizalar?hat=Pres 3&baslangic=2026-08-01&bitis=2026-08-31
```

- Tarihler gün olarak verilir, iki uç da dahildir ve Türkiye saatine göre hesaplanır.
- Hat adında büyük/küçük harf fark etmez. Olmayan bir hat 404 döner ve cevapta geçerli
  hatlar listelenir; ileride LLM yanlış hat adı verirse bu mesajdan düzeltebilecek.
- Tanımsız parametre, geçersiz tarih ya da ters aralık 422 döner.

API testleri `andon_test` adında ayrı bir veritabanı kurup sabit bir tarihle üretilen veriyle
doldurur. Beklenen sonuçlar aynı veriden Python'da hesaplanıp API'nin cevabıyla
karşılaştırılır. Veritabanı kapalıysa bu testler atlanır.

## Kılavuzlarda arama (RAG)

`data/kilavuzlar/` altında 4 kılavuz var (toplam 20 sayfa). **Hepsi bu proje için yazılmış
kurgusal dokümanlardır**; gerçek bir ekipmana veya firmaya ait değildir. Metinleri
`data/kilavuzlar/kaynak/*.md` dosyalarında, PDF'ler `python scripts/kilavuz_pdf.py` ile üretilir.
Uygulama yalnızca PDF'leri okur.

| Kod | Başlık | Erişim | Sayfa |
|---|---|---|---|
| PRES-OT-01 | Pres Hattı Operatör Talimatı | Operasyon | 3 |
| PRES-BK-01 | Pres Hattı Bakım ve Arıza Giderme Kılavuzu | Bakım | 9 |
| KR-BK-01 | Kaynak Robotu Bakım Kılavuzu | Bakım | 4 |
| KAL-PR-01 | Kalite Kontrol Prosedürü | Operasyon | 4 |

Kılavuzlarda veritabanındaki makine kodları (`P3-HP`) ve stok kodları (`SNS-002`) geçer; agent
bir cevapta iki kaynağı birleştirebilir. Erişim seviyesi 5. haftada rol bazlı yetki için
kullanılacak.

```bash
python scripts/ingest.py      # PDF'leri oku, parçala, vektöre çevir, pgvector'a yaz
python scripts/arama_olc.py   # 20 soruluk setle isabeti ölç
```

İlk çalıştırmada embedding modeli (`intfloat/multilingual-e5-small`, ~470 MB) indirilir.

```
GET /ara?soru=pres hattı arıza ilk kontrol
→ PRES-BK-01, sayfa 4, "4. HİDROLİK ARIZALARDA İLK KONTROL > 4.2 İlk kontrol sırası"
```

Nasıl çalışıyor:

1. **Okuma:** pypdf her sayfanın metnini çıkarır. Sayfaların çoğunda aynen tekrar eden satırlar
   (üst bilgi) ve "Sayfa 4 / 9" satırları atılır.
2. **Parçalama:** Metin numaralı başlıklara göre bölünür, uzun bölümler 120 kelimelik ve 30
   kelime örtüşen pencerelere ayrılır. Bir parça sayfa sınırını aşmaz, böylece her parçanın tek
   bir sayfa numarası olur. Her parça başlık yolunu taşır (`4. HİDROLİK ... > 4.1 Genel yaklaşım`).
3. **Vektör:** Parça, doküman ve bölüm başlığıyla birlikte 384 boyutlu vektöre çevrilir.
   "Filtre değiştirilir" gibi kısa bir cümle ancak başlıkla birlikte hangi makineden
   bahsettiğini söyler.
4. **Arama:** Soru da vektöre çevrilir; pgvector'da kosinüs mesafesine göre en yakın k parça
   döner. Vektör indeksi bilerek yok: 67 parçada tam tarama hem hızlı hem kesin.

### Ölçüm

[`eval/arama_sorulari.jsonl`](eval/arama_sorulari.jsonl): 20 soru. Sorular kılavuzdaki
cümleler kopyalanmadan, kullanıcının soracağı gibi yazıldı (kılavuzda "ışık bariyeri",
soruda "ışık perdesi"). Doğru cevap doküman kodu + sayfa numarasıdır.

| Soru biçimi | isabet@1 | isabet@3 | MRR |
|---|---|---|---|
| Türkçe karakterli | %95 | **%100** | 0,97 |
| Türkçe karaktersiz ("isik", "yag") | %75 | %95 | 0,82 |

Bu sayılar iyimserdir: kılavuzları ve soruları aynı kişi yazdı, koleksiyon küçük (67 parça) ve
her sorunun cevabı kılavuzlarda var. Türkçe karaktersiz sorulardaki düşüş gerçek bir zayıflık:
"sari ve kirmizi isik" sorusu hiç bulunamıyor. Çözüm adayı, vektör aramasını PostgreSQL tam
metin araması + `unaccent` ile birleştiren hibrit arama.

Testler gerçek model yerine kelime eşleşmesine dayalı sahte bir embedder kullanır. Böylece model
indirmeden arama akışını ve SQL'i test ederler; anlamsal kaliteyi `arama_olc.py` ölçer.
