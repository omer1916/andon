-- Elle yazılmış SQL soruları.
--
-- Agent (4. hafta) bu soruları kendisi SQL yazarak değil, parametreli araç
-- fonksiyonlarıyla cevaplayacak. Önce burada elle yazıp hangi sorgunun hangi
-- aracın arkasında çalışacağını görüyoruz.
--
-- Çalıştırmak için:
--   docker compose exec -T db psql -U andon -d andon < sql/sorular.sql
--
-- "Geçen ay", "bu ay" gibi ifadeler veritabanı saat dilimine (Europe/Istanbul) göre
-- hesaplanır. Sonuçlar seed.py'nin çalıştığı güne göre değişir.


-- 1. (Demo) Pres 3 hattında geçen ay kaç arıza oldu?
--    Arıza makineye bağlı; hatta ulaşmak için makineler ve hatlar tablolarını birleştiriyoruz.
--    Tarih aralığı [geçen ayın başı, bu ayın başı): alt sınır dahil, üst sınır hariç.
SELECT count(*) AS ariza_sayisi
FROM ariza_kayitlari a
JOIN makineler m ON m.id = a.makine_id
JOIN hatlar h    ON h.id = m.hat_id
WHERE h.ad = 'Pres 3'
  AND a.baslangic >= date_trunc('month', now()) - interval '1 month'
  AND a.baslangic <  date_trunc('month', now());


-- 2. Bu ay hangi hat en çok arıza verdi?
--    İpucu: GROUP BY, ORDER BY ... DESC, LIMIT


-- 3. Pres 3'te geçen ay en sık görülen arıza tipi hangisi, kaç kez?


-- 4. Şu anda devam eden (bitmemiş) arızalar hangileri? Makine kodu ve kaç dakikadır
--    sürdüğüyle birlikte listele.
--    İpucu: bitis IS NULL, now() - baslangic


-- 5. Geçen ay hattı durduran arızalar her hatta toplam kaç saat duruşa sebep oldu?
--    İpucu: sum(bitis - baslangic) bir interval döner; extract(epoch FROM ...) / 3600


-- 6. Son 6 ayda ortalama arıza giderme süresi (MTTR) en yüksek 3 makine hangisi?
--    İpucu: bitmemiş arızaları hesaba katma.


-- 7. Minimum stok seviyesinin altındaki yedek parçalar hangileri, kaçar tane eksik?


-- 8. P3-HP makinesinin aylık arıza sayısı nasıl değişiyor?
--    İpucu: date_trunc('month', baslangic)


-- 9. Haftanın hangi günü en çok arıza oluyor?
--    İpucu: extract(isodow FROM baslangic) -> 1 = pazartesi, 7 = pazar


-- 10. Son 3 ayda en çok kullanılan 5 yedek parça hangisi?
--     İpucu: is_emirleri.parca_id + parca_adet, stok ile birleştir.


-- 11. Açık ya da devam eden iş emirleri teknisyenlere göre nasıl dağılıyor?
