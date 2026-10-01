"""Telegram Bot API için ince bir istemci (yalnızca botun kullandığı yöntemler).

Token adresin içinde geçer (https://api.telegram.org/bot<token>/...). httpx'in hata mesajları
adresi içerebildiği için ağ hataları burada yakalanır ve token'sız bir mesajla yeniden
fırlatılır; token hiçbir günlüğe yazılmaz.
"""

from typing import Any, Protocol

import httpx

API_ADRESI = "https://api.telegram.org"
MESAJ_SINIRI = 4096  # Telegram'ın tek mesaj sınırı (karakter)


class TelegramHatasi(Exception):
    """Telegram isteği başarısız oldu. Mesajda token yoktur."""


class Telegram(Protocol):
    """Botun ihtiyaç duyduğu yöntemler; testler sahte bir uygulama verir."""

    def guncellemeler(self, offset: int | None, zaman_asimi: int) -> list[dict]: ...
    def mesaj_gonder(self, chat_id: int, metin: str) -> None: ...
    def yaziyor(self, chat_id: int) -> None: ...
    def dosya_indir(self, file_id: str, en_fazla_bayt: int) -> bytes: ...


class TelegramAPI:
    def __init__(self, token: str, istemci: httpx.Client | None = None):
        self._api = f"{API_ADRESI}/bot{token}/"
        self._dosya = f"{API_ADRESI}/file/bot{token}/"
        # Uzun yoklamada sunucu `zaman_asimi` saniye bekleyebilir; istemci daha uzun beklemeli.
        self._istemci = istemci or httpx.Client(timeout=httpx.Timeout(10, read=40))

    def _cagir(self, yontem: str, **parametreler: Any) -> Any:
        try:
            cevap = self._istemci.post(self._api + yontem, json=parametreler)
            veri = cevap.json()
        except (httpx.HTTPError, ValueError) as hata:
            raise TelegramHatasi(f"{yontem}: bağlantı hatası ({type(hata).__name__})") from None
        if not veri.get("ok"):
            raise TelegramHatasi(f"{yontem}: {veri.get('description', 'bilinmeyen hata')}")
        return veri["result"]

    def ben(self) -> dict:
        """Token'ı doğrular; botun bilgilerini (kullanıcı adı dahil) döner."""
        return self._cagir("getMe")

    def guncellemeler(self, offset: int | None, zaman_asimi: int) -> list[dict]:
        return self._cagir(
            "getUpdates", offset=offset, timeout=zaman_asimi, allowed_updates=["message"]
        )

    def mesaj_gonder(self, chat_id: int, metin: str) -> None:
        for parca in mesaji_bol(metin):
            self._cagir(
                "sendMessage",
                chat_id=chat_id,
                text=parca,
                parse_mode="HTML",
                link_preview_options={"is_disabled": True},
            )

    def yaziyor(self, chat_id: int) -> None:
        self._cagir("sendChatAction", chat_id=chat_id, action="typing")

    def dosya_indir(self, file_id: str, en_fazla_bayt: int) -> bytes:
        dosya = self._cagir("getFile", file_id=file_id)
        if dosya.get("file_size", 0) > en_fazla_bayt:
            raise TelegramHatasi("getFile: dosya çok büyük")
        try:
            cevap = self._istemci.get(self._dosya + dosya["file_path"])
        except httpx.HTTPError as hata:
            raise TelegramHatasi(f"dosya: bağlantı hatası ({type(hata).__name__})") from None
        if cevap.status_code != 200 or len(cevap.content) > en_fazla_bayt:
            raise TelegramHatasi(f"dosya: indirilemedi (HTTP {cevap.status_code})")
        return cevap.content


def mesaji_bol(metin: str, sinir: int = MESAJ_SINIRI) -> list[str]:
    """Uzun metni Telegram'ın sınırına göre, mümkünse satır sonlarından böler."""
    parcalar = []
    while len(metin) > sinir:
        kesim = metin.rfind("\n", 0, sinir)
        if kesim <= 0:
            kesim = sinir
        parcalar.append(metin[:kesim])
        metin = metin[kesim:].lstrip("\n")
    return [*parcalar, metin] if metin else parcalar
