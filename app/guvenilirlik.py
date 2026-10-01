"""Arıza geçmişinden güvenilirlik: sağdan sansürlü veriyle Weibull dağılımı.

Gözlemler, arızalar arası çalışma süreleridir: bir arızanın bitişinden (tamirden) sonraki
arızanın başlangıcına kadar geçen süre. Son arızadan bugüne geçen süre de bir gözlemdir ama
tamamlanmamıştır, makine henüz bozulmadı: sağdan sansürlü. Bu gözlemi atmak makineyi olduğundan
sık bozuluyormuş gibi gösterir. En çok olabilirlikte arızalar olasılık yoğunluğuyla f(t),
sansürlü gözlemler güvenilirlik fonksiyonuyla R(t) = P(T > t) katılır.

Weibull: R(t) = exp(-(t/η)^β)
  β < 1  erken arıza (risk zamanla azalır)
  β ≈ 1  rastgele arıza (risk sabit; üstel dağılım, "hafızasız")
  β > 1  aşınma (risk zamanla artar; periyodik bakımın en çok işe yaradığı durum)

Log-olabilirliğin β ve η'ya göre türevleri sıfıra eşitlenip η yok edilince tek bilinmeyenli
denklem kalır (r: arıza sayısı, toplamlar: sansürlüler dahil bütün gözlemler):

  g(β) = Σ t^β ln t / Σ t^β - 1/β - (1/r) Σ_arıza ln t = 0,      η = (Σ t^β / r)^(1/β)

g artan bir fonksiyondur (ilk terim, ağırlıkları büyük t'lere kayan bir ln t ortalaması); kökü
ikiye bölme yöntemiyle bulunur.

Az veriyle β'nın tahmini hem oynak hem de yukarı doğru yanlıdır: 8 arızalık rastgele veride
β = 2,5 çıkması şaşırtıcı değildir. Bu yüzden model_sec:
- en az WEIBULL_ICIN_EN_AZ arıza aralığı yoksa yalnızca üstel (sabit riskli, β = 1) modeli,
- varsa Weibull'ü ancak üstel modeli olabilirlik oranı testinde %5 düzeyinde reddederse seçer.
Üstel model Weibull'ün β = 1 hâli olduğu için test istatistiği 2(ℓ_Weibull - ℓ_üstel)
yaklaşık olarak bir serbestlik dereceli ki-kare dağılımına uyar. Yaklaşım küçük örnekte tam
değildir: saf üstel veriyle yapılan simülasyonda Weibull'ün yanlışlıkla seçilme oranı 6 aralıkta
%7,8, 10 aralıkta %7,3, 40 aralıkta %5,0 çıktı (her biri 2.000 deneme).
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

EN_AZ_ARIZA = 5  # Weibull uydurmak için en az arıza aralığı
WEIBULL_ICIN_EN_AZ = 10  # Weibull'ün üstele karşı sınanması için en az arıza aralığı
BETA_ARALIGI = (0.05, 50.0)
KI_KARE_1_YUZDE_95 = 3.841  # ki-kare dağılımı, 1 serbestlik derecesi, %95'lik değer


@dataclass(frozen=True)
class Weibull:
    beta: float  # şekil
    eta: float  # ölçek, gözlemlerle aynı birimde

    def guvenilirlik(self, t: float) -> float:
        """R(t): t süre boyunca bozulmama olasılığı."""
        return math.exp(-((t / self.eta) ** self.beta))

    def kosullu_ariza_olasiligi(self, yas: float, ufuk: float) -> float:
        """`yas` süre bozulmadan çalışmış makinenin sonraki `ufuk` sürede bozulma olasılığı:
        1 - R(yas + ufuk) / R(yas). Oran üslerin farkı olarak hesaplanır; R çok küçükken
        sıfıra bölme olmasın."""
        us = ((yas + ufuk) / self.eta) ** self.beta - (yas / self.eta) ** self.beta
        return -math.expm1(-us)

    def ortalama(self) -> float:
        """Ortalama arızalar arası süre (MTBF) = η Γ(1 + 1/β)."""
        return self.eta * math.gamma(1 + 1 / self.beta)


def weibull_uydur(arizalar: Sequence[float], sansurlu: Sequence[float] = ()) -> Weibull | None:
    """`arizalar`: tamamlanmış arızalar arası süreler; `sansurlu`: henüz bozulmadan geçen
    süreler. En az EN_AZ_ARIZA arıza yoksa None. Bütün süreler pozitif olmalı."""
    r = len(arizalar)
    if r < EN_AZ_ARIZA:
        return None
    hepsi = [*arizalar, *sansurlu]
    if min(hepsi) <= 0:
        raise ValueError("süreler pozitif olmalı")
    # t^β taşmasın diye süreler en büyüğe bölünür; ağırlıklı ortalamada ölçek sadeleşir.
    en_buyuk = max(hepsi)
    oranlar = [t / en_buyuk for t in hepsi]
    lnler = [math.log(t) for t in hepsi]
    ariza_ln_ortalamasi = sum(math.log(t) for t in arizalar) / r

    def g(beta: float) -> float:
        agirliklar = [o**beta for o in oranlar]
        return (
            sum(a * ln for a, ln in zip(agirliklar, lnler, strict=True)) / sum(agirliklar)
            - 1 / beta
            - ariza_ln_ortalamasi
        )

    alt, ust = BETA_ARALIGI
    if g(ust) < 0:  # bütün süreler neredeyse eşit: dağılım deterministik, β sınırda kalır
        beta = ust
    else:
        for _ in range(100):
            orta = (alt + ust) / 2
            alt, ust = (orta, ust) if g(orta) < 0 else (alt, orta)
        beta = (alt + ust) / 2
    eta = en_buyuk * (sum(o**beta for o in oranlar) / r) ** (1 / beta)
    return Weibull(beta=beta, eta=eta)


def ustel_uydur(arizalar: Sequence[float], sansurlu: Sequence[float] = ()) -> Weibull:
    """β = 1 (sabit risk) için en çok olabilirlik: η = toplam gözlem süresi / arıza sayısı."""
    return Weibull(beta=1.0, eta=(sum(arizalar) + sum(sansurlu)) / len(arizalar))


def log_olabilirlik(model: Weibull, arizalar: Sequence[float], sansurlu: Sequence[float]) -> float:
    """ℓ = Σ_arıza ln f(t) + Σ_sansürlü ln R(t). f = h R olduğundan
    ℓ = Σ_arıza ln h(t) - Σ_hepsi (t/η)^β,  ln h(t) = ln β - β ln η + (β - 1) ln t."""
    b, e = model.beta, model.eta
    ln_h = sum(math.log(b) - b * math.log(e) + (b - 1) * math.log(t) for t in arizalar)
    return ln_h - sum((t / e) ** b for t in [*arizalar, *sansurlu])


@dataclass(frozen=True)
class ModelSecimi:
    tur: Literal["weibull", "ustel"]
    secilen: Weibull  # tahminde kullanılacak model (üstelse β = 1)
    weibull: Weibull | None  # Weibull tahmini, seçilmese de bilgi olarak; az veride yok
    olabilirlik_orani: float | None  # 2(ℓ_Weibull - ℓ_üstel); az veride yok


def model_sec(arizalar: Sequence[float], sansurlu: Sequence[float] = ()) -> ModelSecimi | None:
    """Arıza aralığı yoksa None. WEIBULL_ICIN_EN_AZ'dan az aralıkta üstel model; daha çoksa
    Weibull, üstel modeli olabilirlik oranı testinde %5 düzeyinde reddederse seçilir."""
    if not arizalar:
        return None
    ustel = ustel_uydur(arizalar, sansurlu)
    if len(arizalar) < WEIBULL_ICIN_EN_AZ:
        return ModelSecimi("ustel", ustel, None, None)
    weibull = weibull_uydur(arizalar, sansurlu)
    oran = 2 * (
        log_olabilirlik(weibull, arizalar, sansurlu) - log_olabilirlik(ustel, arizalar, sansurlu)
    )
    if oran > KI_KARE_1_YUZDE_95:
        return ModelSecimi("weibull", weibull, weibull, oran)
    return ModelSecimi("ustel", ustel, weibull, oran)


def beta_yorumu(beta: float) -> str:
    if beta < 0.8:
        return "erken arıza (risk azalıyor)"
    if beta <= 1.2:
        return "rastgele arıza (risk sabit)"
    return "aşınma (risk artıyor)"
