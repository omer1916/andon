"""Metinleri vektöre çevirir.

Model: intfloat/multilingual-e5-small. Türkçeyi destekler, 384 boyutlu vektör üretir ve ekran
kartı olmadan CPU'da çalışır. İlk kullanımda Hugging Face'ten indirilir (~470 MB) ve önbelleğe
alınır.
"""

import threading
from typing import Protocol

MODEL_ADI = "intfloat/multilingual-e5-small"
BOYUT = 384


class Embedder(Protocol):
    def pasajlari_vektorle(self, metinler: list[str]) -> list[list[float]]: ...

    def soruyu_vektorle(self, soru: str) -> list[float]: ...


class E5Embedder:
    """E5 modelleri metnin başında "passage: " veya "query: " öneki bekler.

    Öneksiz kullanıldığında arama kalitesi belirgin şekilde düşer. Vektörler normalize
    edilir; böylece kosinüs benzerliği doğrudan karşılaştırılabilir.
    """

    def __init__(self, model_adi: str = MODEL_ADI):
        # torch yüklemesi birkaç saniye sürer; yalnızca model gerçekten gerektiğinde import et.
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_adi, device="cpu")

    def pasajlari_vektorle(self, metinler: list[str]) -> list[list[float]]:
        vektorler = self._model.encode(
            [f"passage: {m}" for m in metinler], normalize_embeddings=True, batch_size=16
        )
        return vektorler.tolist()

    def soruyu_vektorle(self, soru: str) -> list[float]:
        return self._model.encode(f"query: {soru}", normalize_embeddings=True).tolist()


_kilit = threading.Lock()
_embedder: E5Embedder | None = None


def varsayilan_embedder() -> E5Embedder:
    """Model süreç başına bir kez yüklenir (~15 sn).

    Kilit sayesinde, API açılışında arka planda yükleme sürerken gelen istek ikinci bir
    kopya yüklemez; ilk yüklemenin bitmesini bekler.
    """
    global _embedder
    with _kilit:
        if _embedder is None:
            _embedder = E5Embedder()
        return _embedder
