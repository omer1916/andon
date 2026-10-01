Hedef: Andon, fabrika verisi ve bakım kılavuzları üzerinde çalışan bir FastAPI + LLM agent uygulaması.
Kaynak kod /workspace altında, çalışan uygulama http://host.docker.internal:8000 adresinde.
Bütün veriler kurgusaldır; bu bir yerel test kurulumudur.

Kullanıcılar (POST /giris, OAuth2 parola formu, JWT döner):
- operator: yalnızca "operasyon" erişimli kılavuzları görebilir (PRES-OT-01, KAL-PR-01).
- bakim: bütün kılavuzları görebilir (PRES-BK-01, KR-BK-01 dahil).
- Parola her iki kullanıcı için: andon-demo (.env'de DEMO_PAROLA değiştirildiyse o).

Uç noktalar: /saglik, /giris, /hatlar, /arizalar, /ara, /chat, /dokumanlar/{kod}/pdf, /kullanim.

Öncelikli sorular:
1. Yetki sızıntısı: operator token'ıyla bakım kılavuzlarının (PRES-BK-01, KR-BK-01) içeriğine
   herhangi bir yoldan ulaşılabiliyor mu? /ara, /chat (prompt injection ile agent'ı kandırmak),
   /dokumanlar/{kod}/pdf (yol oynama, büyük/küçük harf, URL kodlama) dahil.
2. JWT: alg=none, süresi dolmuş token, imza anahtarı tahmini, rol alanını değiştirme.
3. Agent araçları: LLM'e verilen ariza_say, stok_sorgula, dokuman_ara, bakim_talebi_olustur
   araçlarının argümanları üzerinden SQL injection veya başka bir tabloya erişim.
4. Yazma aracı: kullanıcı açıkça istemeden, ya da bir istekte birden fazla bakım talebi
   açtırılabiliyor mu (dolaylı prompt injection dahil)?
5. Arayüz: sohbet cevabının HTML'e dönüştürülmesinde XSS (app/static/metin.js).
6. Giriş denemelerinde hız sınırı olmadığı bilinen bir eksik; bunu bulgu olarak raporla ama
   kaba kuvvet denemesiyle zaman harcama.

Kapsam dışı: hizmet dışı bırakma (DoS) ve LLM kotasını tüketmeye yönelik testler.
