"""Kılavuzlarda anlamsal arama: PDF'i okuma, parçalara bölme ve pgvector'da arama."""

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from pypdf import PdfReader

from app.embedding import Embedder

# "4. HİDROLİK ARIZALARDA İLK KONTROL" veya "4.2 İlk kontrol sırası" gibi numaralı başlıklar.
# Numaralı adımlar "1) ..." biçiminde yazıldığı için başlıkla karışmaz.
_BASLIK = re.compile(r"^\d+\.(\d+(\.\d+)*)?\s+[A-ZÇĞİÖŞÜ]")
_SAYFA_NUMARASI = re.compile(r"^Sayfa \d+ / \d+$")


@dataclass(frozen=True)
class Parca:
    sayfa: int
    bolum: str | None
    icerik: str


def pdf_sayfalari(yol: Path) -> list[list[str]]:
    """PDF'in her sayfasını satır listesi olarak döner; üst ve alt bilgi satırlarını atar.

    Sayfaların çoğunda aynen tekrar eden satırlar (doküman adı gibi) üst/alt bilgi kabul edilir.
    """
    sayfalar = [
        [s.strip() for s in (sayfa.extract_text() or "").splitlines() if s.strip()]
        for sayfa in PdfReader(yol).pages
    ]
    tekrar_edenler: set[str] = set()
    if len(sayfalar) >= 3:
        sayac = Counter(satir for satirlar in sayfalar for satir in set(satirlar))
        tekrar_edenler = {s for s, adet in sayac.items() if adet >= 0.6 * len(sayfalar)}
    return [
        [s for s in satirlar if s not in tekrar_edenler and not _SAYFA_NUMARASI.match(s)]
        for satirlar in sayfalar
    ]


def _baslik_mi(satir: str) -> bool:
    return len(satir) <= 80 and _BASLIK.match(satir) is not None


def parcala(
    sayfalar: list[list[str]], en_fazla_kelime: int = 120, ortusme: int = 30
) -> list[Parca]:
    """Sayfaları önce bölüm başlıklarına, sonra kelime pencerelerine göre parçalar.

    - Bir parça iki sayfaya yayılmaz; her parçanın tek bir sayfa numarası olur.
    - Parçanın bölümü başlık yoluyla tutulur ("4. HİDROLİK ... > 4.1 Genel yaklaşım").
      Sayfa sonunda bitmeyen bölümün başlığı sonraki sayfadaki parçalara da taşınır.
    - Uzun bölümler `ortusme` kelime örtüşen pencerelere bölünür; böylece bir cümle
      iki parçanın sınırına denk gelirse en az birinde bütün kalır.
    """
    parcalar: list[Parca] = []
    baslik_yolu: list[str] = []
    for sayfa_no, satirlar in enumerate(sayfalar, start=1):
        bloklar: list[tuple[str | None, list[str]]] = [(_yol(baslik_yolu), [])]
        for satir in satirlar:
            if _baslik_mi(satir):
                seviye = satir.split()[0].rstrip(".").count(".") + 1
                baslik_yolu = baslik_yolu[: seviye - 1] + [satir]
                bloklar.append((_yol(baslik_yolu), []))
            else:
                bloklar[-1][1].append(satir)

        for bolum, blok_satirlari in bloklar:
            kelimeler = " ".join(blok_satirlari).split()
            adim = en_fazla_kelime - ortusme
            for bas in range(0, max(len(kelimeler) - ortusme, 1), adim):
                pencere = kelimeler[bas : bas + en_fazla_kelime]
                if pencere:
                    parcalar.append(Parca(sayfa_no, bolum, " ".join(pencere)))
    return parcalar


def _yol(baslik_yolu: list[str]) -> str | None:
    return " > ".join(baslik_yolu) or None


def embedding_metni(dokuman_basligi: str, parca: Parca) -> str:
    """Parça vektöre çevrilirken doküman ve bölüm adı da eklenir.

    "Filtre değiştirilir" gibi kısa bir cümle tek başına hangi makineden bahsettiğini
    söylemez; başlıkla birlikte "pres hattı hidrolik filtre" anlamını taşır.
    """
    return f"{dokuman_basligi} | {parca.bolum or ''}\n{parca.icerik}"


def vektor_metni(vektor: list[float]) -> str:
    """pgvector'ın metin biçimi: [0.1,0.2,...]. Sorguda ::vector ile dönüştürülür."""
    return "[" + ",".join(f"{x:.7f}" for x in vektor) + "]"


def dokuman_ara(
    conn: psycopg.Connection,
    embedder: Embedder,
    soru: str,
    k: int = 3,
    *,
    erisim: Sequence[str],
) -> list[dict]:
    """Soruya anlamca en yakın `k` parçayı, benzerliği yüksekten düşüğe döner.

    Yalnızca erişim seviyesi `erisim` içinde olan dokümanlarda arar. Filtre sıralamadan önce
    SQL'de uygulanır: yetkisiz bir parça sonuçlara hiç girmez. `erisim` bilerek zorunludur;
    bir çağıran yetkiyi unutursa her şeyi döndürmek yerine hata alır.
    """
    vektor = vektor_metni(embedder.soruyu_vektorle(soru))
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT d.kod    AS dokuman_kodu,
                   d.baslik AS dokuman_basligi,
                   p.sayfa,
                   p.bolum,
                   p.icerik,
                   1 - (p.embedding <=> %(vektor)s::vector) AS benzerlik
            FROM dokuman_parcalari p
            JOIN dokumanlar d ON d.id = p.dokuman_id
            WHERE d.erisim = ANY(%(erisim)s)
            ORDER BY p.embedding <=> %(vektor)s::vector, p.id
            LIMIT %(k)s
            """,
            {"vektor": vektor, "k": k, "erisim": list(erisim)},
        )
        return cur.fetchall()
