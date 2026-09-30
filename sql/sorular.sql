-- Referans sorgular: asistana sorulacak tipik soruların elle yazılmış SQL karşılıkları.
--
-- Agent (4. hafta) SQL yazmayacak; bu sorguların parametreli hâllerini araç fonksiyonu
-- olarak çağıracak. Değerlendirme seti (5. hafta) beklenen cevapları buradan alır.
--
-- Çalıştırmak için:
--   docker compose exec -T db psql -U andon -d andon < sql/sorular.sql
--
-- "Geçen ay", "bu ay" gibi ifadeler veritabanı saat dilimine (Europe/Istanbul) göre
-- hesaplanır. Sonuçlar seed.py'nin çalıştığı güne göre değişir.
--
-- Tarih aralıkları hep [başlangıç, bitiş) biçimindedir: alt sınır dahil, üst sınır hariç.
-- Böylece ayın son günü 23:59:59.999 gibi uç değerlerle uğraşmak gerekmez.


\echo '1. (Demo) Pres 3 hattında geçen ay kaç arıza oldu?'
-- Arıza makineye bağlı; hatta ulaşmak için makineler ve hatlar tablolarını birleştiriyoruz.
SELECT count(*) AS ariza_sayisi
FROM ariza_kayitlari a
JOIN makineler m ON m.id = a.makine_id
JOIN hatlar h    ON h.id = m.hat_id
WHERE h.ad = 'Pres 3'
  AND a.baslangic >= date_trunc('month', now()) - interval '1 month'
  AND a.baslangic <  date_trunc('month', now());


\echo '2. Bu ay hangi hat en çok arıza verdi?'
SELECT h.ad AS hat, count(*) AS ariza_sayisi
FROM ariza_kayitlari a
JOIN makineler m ON m.id = a.makine_id
JOIN hatlar h    ON h.id = m.hat_id
WHERE a.baslangic >= date_trunc('month', now())
GROUP BY h.ad
ORDER BY ariza_sayisi DESC
LIMIT 1;


\echo '3. Pres 3''te geçen ay en sık görülen arıza tipi hangisi?'
SELECT a.ariza_tipi, count(*) AS adet
FROM ariza_kayitlari a
JOIN makineler m ON m.id = a.makine_id
JOIN hatlar h    ON h.id = m.hat_id
WHERE h.ad = 'Pres 3'
  AND a.baslangic >= date_trunc('month', now()) - interval '1 month'
  AND a.baslangic <  date_trunc('month', now())
GROUP BY a.ariza_tipi
ORDER BY adet DESC
LIMIT 1;


\echo '4. Şu anda devam eden (bitmemiş) arızalar hangileri?'
SELECT a.id,
       m.kod AS makine,
       a.ariza_tipi,
       a.aciklama,
       round(extract(epoch FROM now() - a.baslangic) / 60) AS suren_dk
FROM ariza_kayitlari a
JOIN makineler m ON m.id = a.makine_id
WHERE a.bitis IS NULL
ORDER BY a.baslangic;


\echo '5. Geçen ay hattı durduran arızalar her hatta toplam kaç saat duruşa sebep oldu?'
-- bitis - baslangic bir interval döner; epoch saniyeye çevirir.
SELECT h.ad AS hat,
       count(*) AS durus_sayisi,
       round(sum(extract(epoch FROM a.bitis - a.baslangic)) / 3600, 1) AS durus_saat
FROM ariza_kayitlari a
JOIN makineler m ON m.id = a.makine_id
JOIN hatlar h    ON h.id = m.hat_id
WHERE a.hat_durdu
  AND a.bitis IS NOT NULL
  AND a.baslangic >= date_trunc('month', now()) - interval '1 month'
  AND a.baslangic <  date_trunc('month', now())
GROUP BY h.ad
ORDER BY durus_saat DESC;


\echo '6. Son 6 ayda ortalama arıza giderme süresi (MTTR) en yüksek 3 makine'
-- Bitmemiş arızaların süresi henüz belli değil, ortalamaya katılmaz.
SELECT m.kod AS makine,
       m.ad,
       count(*) AS ariza_sayisi,
       round(avg(extract(epoch FROM a.bitis - a.baslangic)) / 60) AS ort_sure_dk
FROM ariza_kayitlari a
JOIN makineler m ON m.id = a.makine_id
WHERE a.bitis IS NOT NULL
  AND a.baslangic >= now() - interval '6 months'
GROUP BY m.id
ORDER BY ort_sure_dk DESC
LIMIT 3;


\echo '7. Minimum stok seviyesinin altındaki yedek parçalar'
SELECT parca_kodu, ad, miktar, min_miktar, min_miktar - miktar AS eksik, birim, konum
FROM stok
WHERE miktar < min_miktar
ORDER BY parca_kodu;


\echo '8. P3-HP makinesinin aylık arıza sayısı'
-- generate_series hiç arıza olmayan ayların da 0 olarak görünmesini sağlar.
SELECT to_char(ay, 'YYYY-MM') AS ay, count(a.id) AS ariza_sayisi
FROM generate_series(
         date_trunc('month', now()) - interval '5 months',
         date_trunc('month', now()),
         interval '1 month'
     ) AS ay
LEFT JOIN ariza_kayitlari a
       ON a.baslangic >= ay
      AND a.baslangic <  ay + interval '1 month'
      AND a.makine_id = (SELECT id FROM makineler WHERE kod = 'P3-HP')
GROUP BY ay
ORDER BY ay;


\echo '9. Haftanın hangi günü en çok arıza oluyor?'
SELECT (ARRAY['Pazartesi', 'Salı', 'Çarşamba', 'Perşembe', 'Cuma', 'Cumartesi', 'Pazar'])
           [extract(isodow FROM baslangic)::int] AS gun,
       count(*) AS ariza_sayisi
FROM ariza_kayitlari
GROUP BY extract(isodow FROM baslangic)
ORDER BY ariza_sayisi DESC;


\echo '10. Son 3 ayda en çok kullanılan 5 yedek parça'
SELECT s.parca_kodu, s.ad, sum(e.parca_adet) AS kullanilan, s.birim
FROM is_emirleri e
JOIN stok s ON s.id = e.parca_id
WHERE e.acilis >= now() - interval '3 months'
GROUP BY s.id
ORDER BY kullanilan DESC, s.parca_kodu
LIMIT 5;


\echo '11. Açık ve devam eden iş emirlerinin teknisyenlere dağılımı'
SELECT atanan,
       count(*) FILTER (WHERE durum = 'acik')  AS acik,
       count(*) FILTER (WHERE durum = 'devam') AS devam
FROM is_emirleri
WHERE durum IN ('acik', 'devam')
GROUP BY atanan
ORDER BY count(*) DESC, atanan;
