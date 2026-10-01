"""Telegram botunun uçtan uca provası, token olmadan.

Botun gerçek kodu, Telegram Bot API'sini taklit eden yerel bir HTTP sunucusuna karşı çalışır:
eşleştirme, soru, fotoğraflı talep, komutlar ve arıza bildirimi. Gerçek Telegram'a istek gitmez;
veritabanı, embedding modeli ve LLM gerçektir (LLM ayarlıysa birkaç kuruşluk istek atılır).

Kullanım (veritabanı hazır olmalı: docker compose up -d):
    python -m scripts.telegram_prova

Prova sırasında açılan bakım talebi veritabanında kalır; eklenen arıza ve eşleştirmeler silinir.
"""

import json
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app import telegram_api
from app.db import TZ, baglan
from app.embedding import varsayilan_embedder
from app.telegram_bot import Bot, kod_uret
from scripts.telegram_bot import llm_getir, tur

ADRES = ("127.0.0.1", 8765)
BAKIM, OPERATOR = 111, 222  # sahte sohbet numaraları
FOTOGRAF = b"\xff\xd8\xff\xe0" + b"prova" * 300

bekleyen: list[dict] = []
giden: list[tuple[int, str]] = []


class SahteTelegram(BaseHTTPRequestHandler):
    """Bot API'nin botun kullandığı kısmı: getMe, getUpdates, sendMessage, getFile, dosya."""

    def log_message(self, *_):
        pass

    def _sonuc(self, sonuc) -> None:
        govde = json.dumps({"ok": True, "result": sonuc}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(govde)

    def do_POST(self):
        veri = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
        yontem = self.path.rsplit("/", 1)[-1]
        if yontem == "getMe":
            return self._sonuc({"username": "andon_prova_bot"})
        if yontem == "getUpdates":
            offset = veri.get("offset") or 0
            return self._sonuc([g for g in bekleyen if g["update_id"] >= offset])
        if yontem == "sendMessage":
            giden.append((veri["chat_id"], veri["text"]))
            return self._sonuc({"message_id": len(giden)})
        if yontem == "sendChatAction":
            return self._sonuc(True)
        if yontem == "getFile":
            return self._sonuc({"file_path": "photos/1.jpg", "file_size": len(FOTOGRAF)})
        self.send_response(404)
        self.end_headers()

    def do_GET(self):  # dosya indirme
        self.send_response(200)
        self.end_headers()
        self.wfile.write(FOTOGRAF)


def mesaj(chat_id: int, metin: str | None = None, aciklama: str | None = None) -> None:
    no = len(bekleyen) + 1
    m: dict = {"message_id": no, "chat": {"id": chat_id, "type": "private"}}
    if aciklama is None:
        m["text"] = metin
    else:
        m["photo"] = [{"file_id": "kucuk", "file_size": 100},
                      {"file_id": "buyuk", "file_size": len(FOTOGRAF)}]  # fmt: skip
        m["caption"] = aciklama
    bekleyen.append({"update_id": no, "message": m})


def main() -> None:
    sunucu = ThreadingHTTPServer(ADRES, SahteTelegram)
    threading.Thread(target=sunucu.serve_forever, daemon=True).start()
    telegram_api.API_ADRESI = f"http://{ADRES[0]}:{ADRES[1]}"
    api = telegram_api.TelegramAPI("000000:PROVA")

    conn = baglan()
    conn.autocommit = True
    conn.execute("DELETE FROM telegram_baglantilari WHERE chat_id IN (%s, %s)", [BAKIM, OPERATOR])
    bot = Bot(api, conn, varsayilan_embedder(), llm_getir)
    offset = tur(api, bot, None)  # ilk tur: bildirimin başlangıç noktası

    simdi = datetime.now(TZ)
    mesaj(BAKIM, "Merhaba")  # henüz eşleşmemiş
    mesaj(BAKIM, f"/baglan {kod_uret(conn, 'bakim', simdi)}")
    mesaj(OPERATOR, f"/start {kod_uret(conn, 'operator', simdi)}")
    mesaj(BAKIM, "Pres 3 hattında son 7 günde kaç arıza oldu, en çok hangi tip?")
    mesaj(OPERATOR, aciklama="P3-HP'nin altında yağ birikintisi var, kaçak olabilir")
    mesaj(BAKIM, "/oee Pres 3")
    mesaj(BAKIM, "/plan 12")
    mesaj(OPERATOR, "/plan")
    mesaj(BAKIM, "/rapor")
    offset = tur(api, bot, offset)

    # MES'in yazacağı kayıt: hattı durduran yeni bir arıza; sonraki turda bildirilir.
    (ariza_id,) = conn.execute(
        "INSERT INTO ariza_kayitlari (makine_id, baslangic, ariza_tipi, onem, hat_durdu, "
        "aciklama) SELECT id, now(), 'hidrolik', 'yuksek', true, "
        "'Hidrolik basınç set değerinin altına düştü' FROM makineler WHERE kod = 'P3-HP' "
        "RETURNING id"
    ).fetchone()
    tur(api, bot, offset)
    conn.execute("DELETE FROM ariza_kayitlari WHERE id = %s", [ariza_id])
    conn.execute("DELETE FROM telegram_baglantilari WHERE chat_id IN (%s, %s)", [BAKIM, OPERATOR])
    sunucu.shutdown()

    for chat_id, metin in giden:
        kim = "BAKIM" if chat_id == BAKIM else "OPERATÖR"
        print(f"\n===== bot -> {kim} =====\n{metin}")


if __name__ == "__main__":
    main()
