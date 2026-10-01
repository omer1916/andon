# Andon

Fabrika verisi ve bakım kılavuzları üzerinde çalışan bir yapay zekâ asistanı. Operatör ya da bakım
mühendisi sohbet ekranına şöyle bir soru yazar:

> Pres 3 hattında geçen ay kaç arıza oldu, bu tip arızada ilk neye bakmalıyım?

Asistan sorunun ilk yarısını veritabanında sayarak, ikinci yarısını bakım kılavuzlarında arayarak
cevaplar ve kılavuzdan aldığı her bilginin kaynağını sayfa numarasıyla gösterir:

![Demo sorusunun gerçek cevabı](docs/demo.jpg)

*Gerçek çıktı: `gemini-3.5-flash-lite`, 3 adım, 3,1 saniye, $0,0022. Sayılar veritabanıyla birebir
aynı (25 arıza, 13 hidrolik).*

Kaynağa tıklayınca kılavuzun PDF'i o sayfada açılır. Operatör yalnızca operasyon dokümanlarını,
bakım mühendisi bütün kılavuzları görür.

**OEE paneli** hatların vardiya verisinden OEE'yi (kullanılabilirlik × performans × kalite),
günlük seyrini, duruş nedenlerinin Pareto'sunu ve hattı en uzun durduran makineleri gösterir.
Renkler andon ışıklarıyla aynıdır: %85 ve üstü yeşil (dünya standardı), %65–85 sarı, altı
kırmızı. "Asistana sor" düğmesi paneldeki hat ve tarih aralığıyla asistana "OEE neden bu
seviyede?" diye sorar; asistan aynı sayıları `oee_hesapla` aracından alır.

> Andon, fabrikalarda bir hatta sorun olduğunda yanan uyarı ışığı sisteminin adıdır.
> **Bu projedeki bütün veriler ve kılavuzlar kurgusaldır**; gerçek bir firmaya veya ekipmana ait
> değildir.

## Nasıl çalışıyor

1. Kullanıcı soruyu yazar; istek JWT ile FastAPI'ye gelir.
2. API soruyu LLM'e, kullanabileceği araçların listesiyle birlikte gönderir.
3. LLM sorunun iki parçalı olduğunu anlar ve `ariza_say(hat="Pres 3", baslangic="2026-08-01",
   bitis="2026-08-31")` ile `dokuman_ara("hidrolik arızada ilk kontrol")` araçlarını çağırır.
4. İlk araç parametreli bir SQL sorgusu çalıştırır. İkincisi soruyu vektöre çevirir ve pgvector'da,
   yalnızca kullanıcının rolünün görebildiği kılavuzlarda en yakın parçaları bulur.
5. LLM iki sonucu birleştirip kaynak göstererek cevap verir. İsteğin token'ı, maliyeti ve süresi
   kaydedilir.

```mermaid
flowchart LR
    K["Tarayıcı<br/>(vanilla JS)"] -->|JWT| API["FastAPI<br/>/chat · /ara · /arizalar · /oee"]
    API --> AG["Agent döngüsü<br/>(en fazla 6 adım)"]
    AG <-->|"araç çağrıları"| LLM["Gemini / Ollama<br/>OpenAI uyumlu API"]
    AG --> T1["ariza_say · oee_hesapla<br/>stok_sorgula · bakim_talebi_olustur"]
    AG --> T2["dokuman_ara"]
    T1 -->|"parametreli SQL"| PG[("PostgreSQL<br/>+ pgvector")]
    T2 -->|"rol filtreli<br/>vektör araması"| PG
    T2 --- EMB["multilingual-e5-small"]
    ING["ingest.py<br/>PDF → parça → vektör"] --> PG
    AG -->|"token · maliyet · süre"| PG
```

## Hızlı başlangıç

Gerekenler: Docker Desktop ve bir Gemini API anahtarı ([Google AI Studio](https://aistudio.google.com/apikey),
ücretsiz katman yeterli).

```bash
cp .env.example .env          # sonra .env'deki GEMINI_API_KEY satırını doldur
docker compose up --build
```

İlk açılışta veritabanı 6 aylık sahte veriyle doldurulur, kılavuzlar işlenir ve embedding modeli
indirilir (~470 MB, birkaç dakika). Ardından http://localhost:8000 adresinden `operator` ya da
`bakim` kullanıcısıyla giriş yapılır (parola: `.env`'deki `DEMO_PAROLA`). API belgeleri
http://localhost:8000/docs adresindedir.

## Teknolojiler

| Katman | Kullanılan |
|---|---|
| API | Python 3.12, FastAPI, Pydantic |
| Veritabanı | PostgreSQL 17, pgvector, psycopg 3 (bağlantı havuzu) |
| Kılavuz arama | pypdf, sentence-transformers (`intfloat/multilingual-e5-small`) |
| LLM | Gemini (`gemini-3.5-flash-lite`), OpenAI uyumlu uç noktası üzerinden; Ollama isteğe bağlı |
| Güvenlik | JWT (PyJWT), argon2 (pwdlib) |
| Arayüz | HTML, CSS, vanilla JavaScript (dış bağımlılık yok) |
| Kalite | pytest (1989 test), Hypothesis, ruff, GitHub Actions |
| Çalıştırma | Docker Compose |

## Tasarım kararları

**LLM'e serbest SQL yazdırılmıyor.** LLM yalnızca beş parametreli aracı çağırabilir:

| Araç | Ne yapar |
|---|---|
| `ariza_say(hat, baslangic, bitis, ariza_tipi)` | Arıza sayısı; tiplere ve makinelere göre dağılım |
| `oee_hesapla(hat, baslangic, bitis)` | OEE ve bileşenleri (yüzde), vardiyalara göre OEE, en büyük duruş nedenleri, en çok durduran makineler |
| `dokuman_ara(soru, k)` | Kılavuzlarda anlamsal arama; doküman kodu ve sayfa numarasıyla |
| `stok_sorgula(parca_kodu, sadece_kritik)` | Yedek parça miktarı, yeri, kritik seviye |
| `bakim_talebi_olustur(makine_kodu, aciklama, oncelik)` | Bakım talebi açar |

- Veritabanına giden her değer SQL parametresidir. LLM ne yazarsa yazsın bir tabloyu silemez, başka
  bir tabloyu okuyamaz.
- Her aracın girdisi bir Pydantic modeliyle doğrulanır; LLM'e verilen JSON şeması da aynı modelden
  üretilir.
- Hatalar LLM'in düzeltebileceği mesajlar olarak döner ("'Pres 9' adında bir hat yok. Geçerli
  hatlar: ..."); LLM argümanı düzeltip yeniden dener.
- Yazma yapan tek araç bakım talebi açar. Sistem istemi onu yalnızca kullanıcı açıkça isterse
  çağırmasını söyler, kod da bir istekte en fazla bir talebe izin verir.

**Yetki aramanın içinde uygulanıyor.** Arama SQL'i `WHERE d.erisim = ANY(...)` ile çalışır;
operatörün göremeyeceği bir parça veritabanından hiç gelmez, dolayısıyla LLM'e de ulaşmaz. Erişim
listesi token'daki rolden gelir, LLM'in argümanlarıyla değiştirilemez. Arama fonksiyonunun
`erisim` parametresi bilerek zorunludur: yetkiyi unutan bir çağrı her şeyi döndürmek yerine hata
verir. PDF indirme uç noktası da aynı kurala uyar; yetkisiz rol için dokümanın varlığı bile
gizlenir (404).

**Her kılavuz parçasının tek bir sayfa numarası var.** PDF'ler önce numaralı başlıklara, sonra 120
kelimelik, 30 kelime örtüşen pencerelere bölünür; bir parça sayfa sınırını aşmaz. Her parça başlık
yolunu taşır (`4. HİDROLİK ... > 4.1 Genel yaklaşım`) ve vektöre doküman adıyla birlikte çevrilir.
"Filtre değiştirilir" gibi kısa bir cümle ancak başlıkla birlikte hangi makineden bahsettiğini
söyler. Her sayfada tekrar eden üst bilgi ve "Sayfa 4 / 9" satırları atılır.

**Sağlayıcıdan bağımsız LLM.** Gemini de Ollama da OpenAI'nin chat completions biçimini
desteklediği için tek bir kod yolu ikisiyle çalışır; `.env`'deki `LLM_SAGLAYICI` ile seçilir.
Modelin döndürdüğü asistan mesajı hiçbir alanı atılmadan geçmişe eklenir: Gemini'nin düşünme
modelleri araç çağrısına bir imza (thought signature) koyup sonraki turda geri bekler.

**Model ölçerek seçildi.** Başta `gemini-3.8-flash` kullanıldı; Eylül 2026'daki denemelerde
yoğunluk nedeniyle sık sık 503 döndürdü ve demo sorusu yeniden denemelerle 47 saniye sürdü.
`gemini-3.5-flash-lite` aynı araç seçimini LLM çağrısı başına ~0,7 saniyede ve yarı maliyetle
yapıyor. Demo sorusu arayüzden, Docker'daki uygulamada **3,1 saniyede, $0,0022'ye** (3 adım,
4.542 token) doğru cevaplandı. Model `.env`'deki `LLM_MODEL` ile değiştirilebilir.

**OEE süre üzerinden tanımlanıyor.** Vardiya kaydında planlı süre, üretilen ve hurda adet
tutulur; hattın ideal çevrim süresi `hatlar` tablosundadır.

| Bileşen | Tanım |
|---|---|
| Kullanılabilirlik | çalışma süresi / planlı süre (çalışma = planlı − duruş) |
| Performans | net süre / çalışma süresi (net = Σ adet × ideal çevrim) |
| Kalite | değerli süre / net süre (değerli = Σ sağlam adet × ideal çevrim) |
| OEE | değerli süre / planlı süre = kullanılabilirlik × performans × kalite |

Tek bir hatta kalite, sağlam adet / toplam adet ile aynıdır. Hatlar birleştirilince fark ortaya
çıkar: adetle hesaplansaydı 6 saniyelik bir pres parçası 55 saniyelik bir montaj parçasıyla aynı
ağırlıkta sayılırdı ve fabrika OEE'si A × P × Q'ya eşit olmazdı. Birden çok vardiyanın OEE'si de
vardiya OEE'lerinin ortalaması değil, toplam sürelerden hesaplanır; aksi hâlde planlı bakım
yüzünden kısalmış bir vardiya, tam bir vardiyayla aynı ağırlığı alırdı.

**Duruşun tek bir kaynağı var.** Vardiyanın duruşları `vardiya_duruslari` tablosundadır:
arıza, ürün değişimi (kalıp, fikstür, renk, model) ve malzeme bekleme. Arıza duruşu, arıza
kaydına bağlıdır; tipi ve makinesi oradan gelir, ayrıca tutulmaz. Vardiya kaydında "toplam
duruş" diye ayrı bir alan da yoktur: duruş her sorguda bu tablodan toplanır. Böylece Pareto'daki
dakikaların toplamı OEE'deki duruşla her zaman birebir aynıdır (testle de doğrulanır). Aynı anda
iki arıza hattı durdurduysa çakışan dakikalar önce başlayan arızaya yazılır; planlı bakımla
örtüşen dakikalar duruş sayılmaz. Gerçek bir MES'e (ör. Verimot) bağlanmak için vardiya özetini
ve duruş kayıtlarını bu iki tabloya aktarmak yeterlidir.

**LLM'e yüzdeler hazır veriliyor.** `oee_hesapla` oranları 0,7829 yerine 78,3 olarak döner;
model çarpma ya da yuvarlama yapmaz, sayıyı olduğu gibi aktarır. Panelin "Asistana sor"
düğmesi soruya tarih aralığını açıkça yazar: "son 30 gün"ü model takvim ayı olarak yorumlarsa
panelle asistan farklı sayılar verirdi (denemede %63,8'e karşı %63,6).

**Arıza kaydı makineye bağlı.** Arıza, iş emri ve bakım talebi hatta değil makineye bağlıdır; hatta
`makineler.hat_id` üzerinden ulaşılır. İki alan birden tutulsaydı bir kaydın makinesi bir hatta,
`hat_id`'si başka bir hatta görünebilirdi. Kurallar `CHECK` kısıtlarıyla veritabanındadır (arıza
bitişi başlangıçtan sonra, kapalı iş emrinin kapanış zamanı var ...).

**Her istek kayıt altında.** `llm_istekleri` tablosu kullanıcıyı, modeli, çağrılan araçları, adım
sayısını, girdi/çıktı token'ını, maliyeti ve süreyi tutar. İstek yarıda hata verse bile (kota, ağ)
o ana kadar harcanan token'lar kaydedilir. `GET /kullanim` toplamları, ortalama ve p95 süreyi döner.

## Ölçümler

### Kılavuz araması

[`eval/arama_sorulari.jsonl`](eval/arama_sorulari.jsonl): 20 soru, doğru cevap doküman kodu +
sayfa. Sorular kılavuzdaki cümleler kopyalanmadan, kullanıcının soracağı gibi yazıldı (kılavuzda
"ışık bariyeri", soruda "ışık perdesi").

| Soru biçimi | isabet@1 | isabet@3 | MRR |
|---|---|---|---|
| Türkçe karakterli | %95 | **%100** | 0,97 |
| Türkçe karaktersiz ("isik", "yag") | %75 | %95 | 0,82 |

```bash
python scripts/arama_olc.py                        # ya da --turkce-karaktersiz
```

### Agent değerlendirmesi

[`eval/sorular.jsonl`](eval/sorular.jsonl): agent'ı uçtan uca ölçen 30 soru.

| Kategori | Soru | Ne ölçülüyor |
|---|---|---|
| Sayısal | 10 | Doğru aracı çağırıp doğru sayıyı veriyor mu |
| Doküman | 10 | Doğru sayfayı bulup kaynak gösteriyor mu |
| Birleşik | 4 | Veritabanı ve kılavuz aynı cevapta (demo sorusu dahil) |
| Yetki | 3 | Operatöre bakım kılavuzundan bilgi sızıyor mu |
| Bilinmeyen | 2 | Kılavuzda olmayan bilgi, olmayan hat: uydurmadan "bilmiyorum" diyor mu |
| Yazma | 1 | İstenince doğru talebi açıyor mu |

Sayısal soruların beklenen cevabı sabit bir sayı değil, SQL'dir; her çalıştırmada veritabanından
hesaplanır. Talep beklenmeyen 29 soruda ayrıca istenmeden bakım talebi açılıp açılmadığına
bakılır. Değerlendiricinin kendisi de test edilir: doğru cevabı geçirir; yanlış sayıyı, kaynaksız
cevabı ve istenmeyen talebi yakalar.

```bash
python scripts/degerlendir.py      # rapor: eval/sonuclar.md
pytest -m eval                     # aynı set, her soru bir test
```

**Sonuç (`gemini-3.5-flash-lite`, Eylül 2026):**

| | İlk çalıştırma | Düzeltmelerden sonra |
|---|---|---|
| Geçen | 27/30 | **30/30** |
| Ortalama / p95 süre | 2,6 sn / - | 2,5 sn / 3,8 sn |
| Soru başına token | 2.867 | 3.180 |
| 30 sorunun maliyeti | $0,037 | $0,040 |

İlk çalıştırmada başarısız olan üç sorunun incelemesi:

- **s23 (gerçek hata):** "P3-HP'de kaç hidrolik arıza oldu, kök neden analizi gerekiyor mu?"
  Sayı doğruydu, ama "bir ayda üçten fazla aynı tip arızada kök neden analizi" kuralını içeren
  parça aramada 5. sıradaydı; agent ilk 3 parçayı alıyordu. Model uydurmak yerine "kılavuzda
  bulamadım" dedi. Agent'ın varsayılanı k=5 yapıldı (soru başına ~300 token daha).
- **s28, s29 (değerlendirici hatası):** Model doğru şekilde "bilgi bulunamamaktadır" ve "Pres 7
  adında bir hat bulunmamaktadır" dedi; değerlendirici ise "bulunamadı" gibi tam kelimeler
  arıyordu. Türkçe ekleri yakalayan kökler kullanıldı ("bulunam", "bulunmam"). Kökler olumlu
  biçimleri ("bulunmaktadır") yakalamayacak kadar uzun tutuldu ve bu da test edildi.

Düzeltmeler aynı setin sonuçlarına bakılarak yapıldığı için %100 iyimser bir sayıdır; bir
sonraki adım, düzeltmeler sırasında görülmemiş sorulardan oluşan ikinci bir set olmalı. İlk
çalıştırmanın ham raporu: [`eval/sonuclar_ilk_calistirma.md`](eval/sonuclar_ilk_calistirma.md),
son rapor: [`eval/sonuclar.md`](eval/sonuclar.md).

## Geliştirme ortamı

Gerekenler: Python 3.12, Docker Desktop.

```bash
py -3.12 -m venv .venv
.venv\Scripts\activate                  # Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"                 # PyTorch (CPU) dahil, ilk kurulum birkaç dakika sürer
cp .env.example .env

docker compose up -d db                 # yalnızca veritabanı (127.0.0.1:5432)
python scripts/seed.py                  # 6 aylık sahte veri + demo kullanıcılar
python scripts/ingest.py                # kılavuz PDF'lerini işle
uvicorn app.main:app --reload           # http://localhost:8000

python scripts/sor.py "Pres 3 hattında geçen ay kaç arıza oldu?"   # arayüzsüz soru
```

Kontroller ve testler:

```bash
ruff check . && ruff format --check .
pytest                                  # 1989 test (~45 sn); veritabanı kapalıysa DB testleri atlanır
```

Testler gerçek bir PostgreSQL'e karşı çalışır: `andon_test` veritabanı sabit bir tarihle üretilen
veriyle doldurulur ve beklenen sonuçlar aynı veriden Python'da hesaplanıp API'nin cevabıyla
karşılaştırılır. Embedding modeli ve LLM yerine sahte sürümleri kullanılır (kelime eşleşmeli
embedder, senaryolu LLM); böylece testler model indirmeden ve API anahtarı olmadan çalışır.

| Test dosyası | Test | Ne doğruluyor |
|---|---|---|
| `test_farkli_yoldan` | 611 | Her hat × ay × arıza tipi, her gün, her stok kodu ve makine için API ve araç sonucu, SQL kullanmadan Python'da hesaplanan sonuçla aynı |
| `test_oee` | 372 | 40 tohumda vardiya ve duruş kuralları ile OEE desenleri; planlı süre ve arıza duruşu dakika dakika kümelerle yeniden hesaplanıyor; her hat × ay ve rastgele aralıklar için API'nin OEE'si, günlük seyri, Pareto'su ve makine listesi SQL kullanmadan hesaplanan sonuçla aynı |
| `test_seed_ozellikleri` | 280 | 40 farklı rastgele tohumla üretilen veride şema kuralları ve veri desenleri tutuyor |
| `test_guvenlik_matrisi` | 161 | Her rol × uç nokta × token türü (süresi dolmuş, yanlış anahtar, `alg: none`, eksik alan, bilinmeyen rol...), yol oynamayla PDF, NUL baytı |
| `test_arama_butunlugu` | 118 | Her kılavuz parçası kendi metniyle ilk sırada bulunuyor; operatör 46 bakım parçasının hiçbirine birebir metniyle bile ulaşamıyor |
| `test_arayuz_metin` | 100 | Arayüzün HTML temizleyicisi (Node ile) 46 XSS yükünde izinli etiket dışında hiçbir şey, hiçbir öznitelik üretmiyor |
| `test_arac_girdileri` | 76 | LLM'in gönderebileceği bozuk argümanlar, bozuk JSON ve SQL injection denemeleri düzeltilebilir hata dönüyor, veri bozulmuyor |
| `test_api_dogrulama` | 55 | Geçersiz her istek 422, asla 500 değil |
| `test_degerlendirici` | 48 | Değerlendiricinin kendisi: sayı eşleştirme, Türkçe ekler, kaynak ve yetki kontrolü |
| `test_arayuz_oee` | 20 | OEE panelinin tarih aralıkları (ay ve yıl sınırı, artık yıl), yüzde biçimi ve andon rengi eşikleri (Node ile) |
| `test_ozellikler` | 10 | Hypothesis ile her biri 300 rastgele girdi: parçalama, token, tarih filtresi, sayı eşleştirme |
| diğerleri | 138 | API, agent döngüsü, giriş, RAG, seed, değerlendirme setinin tutarlılığı |

Testlerin bulduğu iki gerçek hata düzeltildi: token'sız `/chat` isteğinin 401 yerine 503 dönmesi
(giriş yapmamış biri sunucunun ayar durumunu öğrenebiliyordu) ve girdide NUL baytının
PostgreSQL'de 500 hatasına dönüşmesi. GitHub Actions her pull request'te ruff'ı ve testleri
pgvector'lü bir servis konteynerine karşı çalıştırır; veritabanına ulaşılamazsa testler
atlanmaz, başarısız olur.

Ayrıca iki inceleme yapıldı: güvenlik incelemesi (doğrulanmış açık bulunmadı; önerilen
sertleştirmeyle veritabanı ve API portları yalnızca `127.0.0.1`'e bağlandı) ve arayüz
yönergeleri denetimi (erişilebilirlik, odak, hareket azaltma, form davranışı; bulgular
düzeltildi).

Her iş kendi branch'inde geliştirildi ve pull request ile birleştirildi:
[#1 iskelet](https://github.com/omer1916/andon/pull/1) ·
[#2 veritabanı](https://github.com/omer1916/andon/pull/2) ·
[#3 API](https://github.com/omer1916/andon/pull/3) ·
[#4 RAG](https://github.com/omer1916/andon/pull/4) ·
[#5 agent](https://github.com/omer1916/andon/pull/5) ·
[#6 güvenlik ve kalite](https://github.com/omer1916/andon/pull/6) ·
[#7 arayüz](https://github.com/omer1916/andon/pull/7)

Claude Code ile çalışırken kullanılan güvenlik ve tasarım araçları (Strix skill'leri, tasarım
skill'leri, önerilen plugin'ler, CodeQL, Dependabot) ve Strix ile uygulamanın nasıl
taranacağı: [`docs/claude-araclari.md`](docs/claude-araclari.md).

## Veri

| Tablo | İçerik |
|---|---|
| `hatlar`, `makineler` | 7 hat (Pres 1-3, Kaynak 1-2, Montaj 1, Boya 1) ve ideal çevrim süreleri, 21 makine |
| `ariza_kayitlari` | 6 aylık arıza: başlangıç/bitiş, tip, önem, hattı durdurup durdurmadığı |
| `stok` | Yedek parçalar ve minimum seviyeleri |
| `is_emirleri` | Arıza müdahaleleri ve periyodik bakımlar, kullanılan parça |
| `bakim_talepleri` | Operatörlerin ve agent'ın açtığı talepler |
| `vardiya_uretimi` | Her hattın her vardiyası: planlı süre, üretilen ve hurda adet (hafta içi üç, cumartesi iki, pazar bir vardiya) |
| `vardiya_duruslari` | Vardiyadaki duruşlar: arıza (arıza kaydına bağlı), ürün değişimi, malzeme bekleme |
| `kullanicilar` | Demo kullanıcılar (argon2 parola hash'i) |
| `dokumanlar`, `dokuman_parcalari` | Kılavuzlar ve 384 boyutlu vektörleriyle parçaları |
| `llm_istekleri` | Agent'ın her isteği: token, maliyet, süre, araçlar |

Sahte veride bilerek desenler var: Pres 3 en çok arıza veren hat, P3-HP'de son iki ayda hidrolik
arızalar artıyor, pazar günleri arıza az, beş parça minimum stok seviyesinin altında ve seed
anında üç arıza sürüyor. Elle yazılmış referans sorgular: [`sql/sorular.sql`](sql/sorular.sql).

Üretim verisinin desenleri: Pres 3'ün OEE'si en düşük (~%65; diğer hatlar %78–82), çünkü hem en
çok duran hat hem de 2009 model olduğu için tasarım hızının altında çalışıyor. Pres hatlarında en
büyük kayıp arıza değil kalıp değişimi; Pres 3'te bir kalıp değişimi diğer preslerin 1,5 katı
sürüyor (hızlı kalıp değişimi, SMED, için açık bir fırsat). Pres 3'te son iki ayda hurda oranı
üç katına çıkıyor; P3-HP'deki hidrolik arızaların arttığı dönemle aynı. Gece vardiyasında
performans gündüzden düşük. Üretim verisi ayrı bir rastgele sayı üreteciyle üretilir; eklenmesi
arıza, stok ve iş emri verisini değiştirmedi, demo sorusunun cevabı aynı kaldı.

Kılavuzlar (toplam 20 sayfa) Markdown'da yazılıp `scripts/kilavuz_pdf.py` ile PDF'e çevrilir;
uygulama yalnızca PDF'leri okur. Kılavuzlarda veritabanındaki makine ve stok kodları geçer, böylece
agent iki kaynağı tek cevapta birleştirebilir ("kılavuz SNS-002'yi söylüyor, stokta 1 adet var").

| Kod | Başlık | Erişim | Sayfa |
|---|---|---|---|
| PRES-OT-01 | Pres Hattı Operatör Talimatı | Operasyon | 3 |
| PRES-BK-01 | Pres Hattı Bakım ve Arıza Giderme Kılavuzu | Bakım | 9 |
| KR-BK-01 | Kaynak Robotu Bakım Kılavuzu | Bakım | 4 |
| KAL-PR-01 | Kalite Kontrol Prosedürü | Operasyon | 4 |

## Proje yapısı

```
app/
  main.py        FastAPI uç noktaları
  agent.py       araç döngüsü, sistem istemi, istek kaydı
  tools.py       agent araçları ve JSON şemaları
  llm.py         Gemini/Ollama istemcisi, maliyet hesabı
  rag.py         PDF okuma, parçalama, vektör araması
  embedding.py   multilingual-e5-small
  auth.py        JWT, roller, parola hash'i
  sorgular.py    SQL sorguları
  static/        sohbet arayüzü ve OEE paneli
scripts/         seed, ingest, kılavuz PDF üretimi, ölçüm ve değerlendirme
sql/             şema ve referans sorgular
data/kilavuzlar/ kurgusal kılavuzlar (Markdown kaynak + PDF)
eval/            arama ve agent değerlendirme setleri
tests/           1989 test
```

## Bilinen eksikler

- **Değerlendirme seti küçük ve düzeltmeler ona bakılarak yapıldı.** 30/30 iyimser; görülmemiş
  sorulardan oluşan ikinci bir set gerekiyor.
- **Demo parolası varsayılan olarak bilinen bir değer.** Portlar yalnızca bu makineye açık;
  uygulamayı ağa açmadan önce `.env`'de `DEMO_PAROLA` değiştirilmeli (açılış günlüğü uyarır).
- **Türkçe karakter kullanılmadan yazılan sorularda arama zayıflıyor** (isabet@1 %95'ten %75'e
  iniyor). Çözüm adayı: vektör aramasını PostgreSQL tam metin araması + `unaccent` ile birleştiren
  hibrit arama.
- **Ölçümler iyimser.** Kılavuzları ve soruları aynı kişi yazdı, koleksiyon küçük (67 parça).
- **Sohbet geçmişi yok.** Her soru bağımsız; "peki geçen hafta?" gibi bir devam sorusu anlaşılmaz.
- **Cevap akışı (streaming) yok ve LLM gecikmesi dalgalı.** Cevap tamamlanınca bir seferde
  gelir. Ücretsiz katmanda aynı Gemini çağrısı art arda denemelerde 0,8 sn ile 24 sn arasında
  sürdü (DNS ve ağ tarafı ölçülüp elendi); böyle anlarda bir soru 30 saniyeyi bulabiliyor.
  Streaming ve daha kısa zaman aşımıyla yeniden deneme bunu yumuşatır.
- **Giriş denemelerine sınır yok.** Hesap kilitleme, istek sınırı ve yenileme token'ı üretim
  öncesi eklenmeli; kullanıcı yönetimi yok, demo kullanıcılar seed ile gelir.
- **Ollama yolu denenmedi.** Kod aynı, ama bu makinede Ollama kurulu değildi.

## Lisans

MIT. Veriler ve kılavuzlar kurgusaldır.
