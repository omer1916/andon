> İlk çalıştırma: dokuman_ara varsayılanı k=3 ve bilinmeyen sorularda tam kelime eşleşmesiyle.
> Başarısız 3 sorunun incelemesi README'deki Değerlendirme bölümünde. Son sonuç: sonuclar.md

# Değerlendirme sonuçları

2026-09-30 15:45 · model: `gemini-3.5-flash-lite` · 30 soru · `python scripts/degerlendir.py` ile üretildi

| Kategori | Geçen | Oran |
|---|---|---|
| sayisal | 10/10 | 100% |
| dokuman | 10/10 | 100% |
| birlesik | 3/4 | 75% |
| yetki | 3/3 | 100% |
| bilinmeyen | 0/2 | 0% |
| yazma | 1/1 | 100% |
| **toplam** | **27/30** | **90%** |

- Süre: ortalama 2.6 sn, p95 2.5 sn
- Token: 81032 girdi + 5003 çıktı (soru başına ortalama 2867)
- Maliyet (ücretli katman liste fiyatıyla): toplam $0.0368

| Soru | Rol | Sonuç | Başarısız kontrol | Adım | Süre |
|---|---|---|---|---|---|
| s01 Pres 3 hattında geçen ay kaç arıza oldu? | bakim | ✓ | - | 2 | 1.9 sn |
| s02 Bu ay Kaynak 2 hattında kaç arıza kaydedildi? | operator | ✓ | - | 2 | 2.0 sn |
| s03 Geçen ay bütün fabrikada toplam kaç arıza oldu? | bakim | ✓ | - | 2 | 1.8 sn |
| s04 Geçen ay Pres 3'te en sık görülen arıza tipi neydi? | bakim | ✓ | - | 2 | 1.6 sn |
| s05 Geçen ay Pres 3 hattında kaç tane hidrolik arıza oldu? | bakim | ✓ | - | 2 | 1.5 sn |
| s06 Geçen ay en çok arıza veren makine hangisiydi? | bakim | ✓ | - | 2 | 1.5 sn |
| s07 Montaj 1 hattında bu ay kaç arıza oldu? | operator | ✓ | - | 2 | 2.1 sn |
| s08 Minimum stok seviyesinin altına düşen yedek parçalar hangileri? | bakim | ✓ | - | 2 | 2.1 sn |
| s09 SNS-002 basınç sensöründen stokta kaç adet var ve nerede duruyor? | bakim | ✓ | - | 2 | 1.4 sn |
| s10 Geçen ay Boya 1 hattında kaç arıza oldu? | bakim | ✓ | - | 2 | 1.6 sn |
| s11 Pres hattında hidrolik bir arıza olduğunda ilk neyi kontrol etmeliyim? | bakim | ✓ | - | 2 | 26.2 sn |
| s12 Oransal valf bobininin direnci kaç ohm olmalı? | bakim | ✓ | - | 2 | 1.6 sn |
| s13 Basınç sensörü 210 bar'da kaç mA göstermeli? | bakim | ✓ | - | 2 | 1.8 sn |
| s14 Kaynak robotunda koruyucu gazın debisi ne olmalı? | bakim | ✓ | - | 2 | 1.9 sn |
| s15 Kaynak robotunun enkoder bataryası ne sıklıkla değiştirilir? | bakim | ✓ | - | 2 | 1.6 sn |
| s16 Boya kalınlığının kabul aralığı nedir? | operator | ✓ | - | 2 | 1.4 sn |
| s17 Hangi durumlarda ilk parça onayı alınması gerekir? | operator | ✓ | - | 2 | 1.6 sn |
| s18 Panelde A102 alarmı çıktı, operatör olarak ne yapmalıyım? | operator | ✓ | - | 2 | 2.1 sn |
| s19 Pres hidrolik sisteminde hangi yağ kullanılıyor? | bakim | ✓ | - | 2 | 1.4 sn |
| s20 Yüksek önemli bir arıza yarım saatte giderilemezse kime haber verilir? | bakim | ✓ | - | 2 | 1.4 sn |
| s21 Pres 3 hattında geçen ay kaç arıza oldu, bu tip arızada ilk neye bakmalıyım? | bakim | ✓ | - | 2 | 3.0 sn |
| s22 Basınç sensörünü değiştirmem gerekiyor. Kılavuza göre hangi stok kodlu parça kullanılıyor ve stokta var mı? | bakim | ✓ | - | 3 | 2.5 sn |
| s23 P3-HP makinesinde geçen ay kaç hidrolik arıza oldu? Kılavuza göre bu durumda kök neden analizi gerekiyor mu? | bakim | ✗ | kaynak | 2 | 2.2 sn |
| s24 Kaynak 2 hattında bu ay kaç arıza oldu? Kaynak dikişinde gözenek görülürse ne kontrol edilmeli? | bakim | ✓ | - | 2 | 2.4 sn |
| s25 Oransal valf bobininin direnci kaç ohm olmalı? | operator | ✓ | - | 2 | 1.8 sn |
| s26 Kaynak robotunun enkoder bataryası ne zaman değiştirilir? | operator | ✓ | - | 2 | 1.6 sn |
| s27 Pres hattında hidrolik arıza olduğunda ne yapmalıyım? | operator | ✓ | - | 2 | 2.3 sn |
| s28 Boya kabininin filtreleri ne sıklıkla değiştirilmeli? | bakim | ✗ | herhangi | 3 | 1.9 sn |
| s29 Pres 7 hattında geçen ay kaç arıza oldu? | bakim | ✗ | herhangi | 1 | 1.1 sn |
| s30 P3-HP makinesinde hidrolik yağ kaçağı var, yüksek öncelikli bir bakım talebi açar mısın? | operator | ✓ | - | 2 | 1.5 sn |
