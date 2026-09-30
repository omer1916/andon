"""LLM istemcisi.

Gemini de Ollama da OpenAI'nin "chat completions" biçimini destekler. Bu yüzden tek bir kod yolu
ikisiyle de çalışır; hangisinin kullanılacağı .env'deki LLM_SAGLAYICI ile seçilir.
"""

from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from openai import NOT_GIVEN, OpenAI

from app.ayarlar import Ayarlar

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
VARSAYILAN_MODELLER = {"gemini": "gemini-3.8-flash", "ollama": "qwen3:4b"}

# Ücretli katman liste fiyatı, USD / 1M token: (girdi, çıktı). Kaynak: ai.google.dev/pricing
# (Eylül 2026). Ücretsiz katmanda gerçek maliyet 0'dır; kayıttaki maliyet "bu istek ücretli
# katmanda ne kadara mal olurdu" sorusunu cevaplar. Ollama yerelde çalışır, maliyeti 0.
FIYATLAR = {
    "gemini-3.8-flash": (0.75, 3.75),  # 31.12.2026'ya kadar indirimli fiyat
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.1-flash-lite": (0.25, 1.50),
}


class LLMAyarHatasi(Exception):
    """LLM kullanılamıyor: anahtar eksik ya da ayar hatalı."""


@dataclass
class AracCagrisi:
    id: str
    ad: str
    argumanlar_json: str


@dataclass
class LLMYaniti:
    mesaj: dict  # sohbet geçmişine aynen eklenecek asistan mesajı
    metin: str | None
    arac_cagrilari: list[AracCagrisi]
    girdi_token: int
    cikti_token: int


class LLM(Protocol):
    saglayici: str
    model: str

    def tamamla(self, mesajlar: list[dict], araclar: list[dict]) -> LLMYaniti: ...


class OpenAIUyumluLLM:
    def __init__(self, saglayici: str, model: str, base_url: str, api_key: str):
        self.saglayici, self.model = saglayici, model
        self._istemci = OpenAI(base_url=base_url, api_key=api_key, timeout=60, max_retries=2)

    def tamamla(self, mesajlar: list[dict], araclar: list[dict]) -> LLMYaniti:
        yanit = self._istemci.chat.completions.create(
            model=self.model, messages=mesajlar, tools=araclar or NOT_GIVEN
        )
        mesaj = yanit.choices[0].message
        return LLMYaniti(
            # Mesaj hiçbir alanı atılmadan geçmişe eklenir. Gemini'nin düşünme modelleri araç
            # çağrısına ek alanlar (thought signature) koyar ve sonraki turda geri bekler.
            mesaj=mesaj.model_dump(exclude_none=True),
            metin=mesaj.content,
            arac_cagrilari=[
                AracCagrisi(c.id, c.function.name, c.function.arguments)
                for c in mesaj.tool_calls or []
            ],
            girdi_token=yanit.usage.prompt_tokens if yanit.usage else 0,
            cikti_token=yanit.usage.completion_tokens if yanit.usage else 0,
        )


def maliyet_hesapla(saglayici: str, model: str, girdi_token: int, cikti_token: int) -> float | None:
    if saglayici == "ollama":
        return 0.0
    if model not in FIYATLAR:
        return None
    girdi_fiyati, cikti_fiyati = FIYATLAR[model]
    return (girdi_token * girdi_fiyati + cikti_token * cikti_fiyati) / 1_000_000


def llm_olustur(a: Ayarlar) -> LLM:
    model = a.llm_model or VARSAYILAN_MODELLER[a.llm_saglayici]
    if a.llm_saglayici == "gemini":
        if not a.gemini_api_key:
            raise LLMAyarHatasi(
                "GEMINI_API_KEY tanımlı değil. Anahtarı .env dosyasına ekleyin "
                "(bkz. .env.example) ya da LLM_SAGLAYICI=ollama kullanın."
            )
        return _istemci(a.llm_saglayici, model, GEMINI_URL, a.gemini_api_key)
    return _istemci(a.llm_saglayici, model, a.ollama_url, "ollama")


@lru_cache(maxsize=4)
def _istemci(saglayici: str, model: str, base_url: str, api_key: str) -> OpenAIUyumluLLM:
    """Aynı ayarlarla her istekte yeni HTTP istemcisi kurulmasın."""
    return OpenAIUyumluLLM(saglayici, model, base_url, api_key)
