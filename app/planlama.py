"""Bakım ekibinin sınırlı saatini makinelere dağıtmak: 0/1 sırt çantası problemi.

Her makine bir eşya: ağırlığı bakımın süresi (saat), değeri bakım yapılırsa önlenmesi beklenen
duruş (dakika). Kapasite, ekibin bu hafta ayırabileceği saat. Amaç, toplam süresi kapasiteyi
aşmayan ve toplam değeri en büyük olan makine kümesini bulmak.

Dinamik programlama kesin sonucu verir. tablo[i][c]: ilk i makineyle, c saati aşmadan elde
edilebilecek en büyük değer.
    tablo[i][c] = max(tablo[i-1][c],                          i. makine seçilmezse
                      tablo[i-1][c - süre_i] + değer_i)       seçilirse (süre_i <= c ise)
Karmaşıklık O(n x C); 21 makine ve 200 saat için 4.200 hücre.

Açgözlü yöntem (değer/süre oranı en yüksekten başlayıp sığanı almak) hızlıdır ama en iyiyi
garanti etmez: uzun ama değerli bir bakım, kapasitede kalan boşluğa sığmadığı için atlanabilir.
Karşılaştırma için burada; plan her zaman dinamik programlamayla yapılır.
"""

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Aday:
    sure: int  # saat; dinamik programlama tam sayı ister
    deger: float


def sirt_cantasi(adaylar: Sequence[Aday], kapasite: int) -> list[int]:
    """Kapasiteyi aşmayan ve toplam değeri en büyük olan adayların indeksleri (artan sırada)."""
    n = len(adaylar)
    tablo = [[0.0] * (kapasite + 1) for _ in range(n + 1)]
    for i, aday in enumerate(adaylar, start=1):
        for c in range(kapasite + 1):
            tablo[i][c] = tablo[i - 1][c]
            if aday.sure <= c:
                tablo[i][c] = max(tablo[i][c], tablo[i - 1][c - aday.sure] + aday.deger)

    # Geri izleme: değer bir önceki satırdan farklıysa o aday seçilmiştir.
    secilen, c = [], kapasite
    for i in range(n, 0, -1):
        if tablo[i][c] != tablo[i - 1][c]:
            secilen.append(i - 1)
            c -= adaylar[i - 1].sure
    return sorted(secilen)


def acgozlu(adaylar: Sequence[Aday], kapasite: int) -> list[int]:
    """Değer/süre oranına göre sırayla sığanı alır. En iyiyi garanti etmez."""
    sira = sorted(range(len(adaylar)), key=lambda i: -adaylar[i].deger / adaylar[i].sure)
    secilen, kalan = [], kapasite
    for i in sira:
        if adaylar[i].deger > 0 and adaylar[i].sure <= kalan:
            secilen.append(i)
            kalan -= adaylar[i].sure
    return sorted(secilen)
