"""Andon API.

Çalıştırmak için: uvicorn app.main:app --reload
Belgeler: http://localhost:8000/docs
"""

import threading
from collections.abc import Iterator
from contextlib import asynccontextmanager
from typing import Annotated

import openai
import psycopg
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app import __version__, agent, rag, sorgular
from app.ayarlar import ayarlar
from app.db import havuz_olustur
from app.embedding import Embedder, TembelEmbedder, varsayilan_embedder
from app.llm import LLM, LLMAyarHatasi, llm_olustur
from app.models import (
    AramaIstegi,
    AramaSonucu,
    ArizaFiltresi,
    ArizaListesi,
    Hat,
    KullanimOzeti,
    Saglik,
    SohbetCevabi,
    SohbetIstegi,
)
from app.tools import AracBaglami

router = APIRouter()


def baglanti(request: Request) -> Iterator[psycopg.Connection]:
    with request.app.state.havuz.connection() as conn:
        yield conn


Baglanti = Annotated[psycopg.Connection, Depends(baglanti)]


def embedder_getir() -> Embedder:
    """Testler bunu sahte bir embedder'la değiştirir; model indirmeden çalışırlar."""
    return TembelEmbedder()


def llm_getir() -> LLM:
    """Testler bunu senaryolu sahte bir LLM'le değiştirir."""
    try:
        return llm_olustur(ayarlar())
    except LLMAyarHatasi as hata:
        raise HTTPException(503, str(hata)) from None


def _llm_hatasi(hata: BaseException) -> HTTPException | None:
    """LLM sağlayıcısının hatasını kullanıcıya anlamlı bir HTTP hatasına çevirir."""
    if isinstance(hata, openai.RateLimitError):
        return HTTPException(429, "LLM kota sınırına ulaşıldı; biraz sonra tekrar deneyin.")
    if isinstance(hata, openai.AuthenticationError | openai.PermissionDeniedError):
        return HTTPException(
            502, "LLM anahtarı geçersiz ya da yetkisiz; .env'deki anahtarı kontrol edin."
        )
    if isinstance(hata, openai.APIConnectionError):
        return HTTPException(502, "LLM sağlayıcısına ulaşılamadı (Ollama çalışıyor mu?).")
    if isinstance(hata, openai.APIError):
        return HTTPException(502, f"LLM sağlayıcısı hata verdi: {hata}")
    return None


@router.get(
    "/saglik",
    response_model=Saglik,
    responses={503: {"model": Saglik, "description": "Veritabanına ulaşılamıyor"}},
    summary="Servis ve veritabanı ayakta mı",
)
def saglik(request: Request):
    try:
        with request.app.state.havuz.connection(timeout=2) as conn:
            conn.execute("SELECT 1")
    except psycopg.Error:
        return JSONResponse(status_code=503, content={"veritabani": False})
    return Saglik(veritabani=True)


@router.get("/hatlar", response_model=list[Hat], summary="Üretim hatlarını listeler")
def hatlar(conn: Baglanti):
    return sorgular.hatlari_getir(conn)


@router.get(
    "/arizalar",
    response_model=ArizaListesi,
    responses={404: {"description": "Verilen adda hat yok"}},
    summary="Arızaları hat, tarih aralığı ve tipe göre listeler",
)
def arizalar(filtre: Annotated[ArizaFiltresi, Query()], conn: Baglanti):
    if filtre.hat is not None and sorgular.hat_adini_bul(conn, filtre.hat) is None:
        gecerli = ", ".join(h["ad"] for h in sorgular.hatlari_getir(conn))
        raise HTTPException(404, f"'{filtre.hat}' adında bir hat yok. Geçerli hatlar: {gecerli}")
    toplam, kayitlar = sorgular.arizalari_getir(conn, **filtre.model_dump())
    return ArizaListesi(toplam=toplam, arizalar=kayitlar)


@router.get(
    "/ara",
    response_model=list[AramaSonucu],
    responses={503: {"description": "Kılavuzlar henüz yüklenmemiş"}},
    summary="Kılavuzlarda anlamsal arama; sonuçlar sayfa numarasıyla döner",
)
def ara(
    istek: Annotated[AramaIstegi, Query()],
    conn: Baglanti,
    embedder: Annotated[Embedder, Depends(embedder_getir)],
):
    try:
        return rag.dokuman_ara(conn, embedder, istek.soru, istek.k)
    except psycopg.errors.UndefinedTable:
        raise HTTPException(
            503, "Kılavuzlar henüz yüklenmemiş; önce 'python scripts/ingest.py' çalıştırın."
        ) from None


@router.post(
    "/chat",
    response_model=SohbetCevabi,
    responses={
        429: {"description": "LLM kota sınırı"},
        502: {"description": "LLM sağlayıcısı hatası"},
        503: {"description": "LLM ayarlı değil"},
    },
    summary="Asistana soru sor; agent veritabanı ve kılavuz araçlarını kullanarak cevaplar",
)
def chat(
    istek: SohbetIstegi,
    conn: Baglanti,
    embedder: Annotated[Embedder, Depends(embedder_getir)],
    llm: Annotated[LLM, Depends(llm_getir)],
):
    kullanici = "anonim"  # 5. haftada JWT'deki kullanıcı adı olacak
    baglam = AracBaglami(conn=conn, embedder=embedder, kullanici=kullanici)
    try:
        sonuc = agent.sohbet(istek.soru, llm, baglam)
    except agent.SohbetHatasi as hata:
        agent.kaydet(conn, istek.soru, kullanici, llm.saglayici, hata.sonuc)
        http_hatasi = _llm_hatasi(hata.__cause__)
        if http_hatasi is None:
            raise hata.__cause__ from None
        raise http_hatasi from None
    agent.kaydet(conn, istek.soru, kullanici, llm.saglayici, sonuc)

    kaynaklar = {}
    for parca in sonuc.kaynaklar:
        kaynaklar.setdefault((parca["dokuman_kodu"], parca["sayfa"]), parca)
    return SohbetCevabi(
        cevap=sonuc.cevap,
        kaynaklar=list(kaynaklar.values()),
        arac_cagrilari=sonuc.arac_cagrilari,
        kullanim={
            "model": sonuc.model,
            "adim_sayisi": sonuc.adim_sayisi,
            "girdi_token": sonuc.girdi_token,
            "cikti_token": sonuc.cikti_token,
            "maliyet_usd": sonuc.maliyet_usd,
            "sure_ms": sonuc.sure_ms,
        },
    )


@router.get(
    "/kullanim",
    response_model=KullanimOzeti,
    summary="Agent isteklerinin toplam token, maliyet ve süre özeti",
)
def kullanim(conn: Baglanti):
    return sorgular.llm_kullanim_ozeti(conn)


@asynccontextmanager
async def lifespan(uygulama: FastAPI):
    # Veritabanı kapalı olsa da uygulama açılsın; /saglik durumu 503 ile bildirir.
    havuz = havuz_olustur()
    havuz.open(wait=False)
    uygulama.state.havuz = havuz
    if uygulama.state.model_on_yukle:
        # İlk /ara isteği modelin yüklenmesini (~15 sn) beklemesin.
        threading.Thread(target=varsayilan_embedder, daemon=True).start()
    yield
    havuz.close()


def uygulama_olustur(model_on_yukle: bool = True) -> FastAPI:
    """Her çağrıda yeni bir uygulama döner; testler birbirinin bağlantı havuzuna dokunmasın.

    Testler `model_on_yukle=False` verir; embedding modeli yerine sahte embedder kullanırlar.
    """
    uygulama = FastAPI(
        title="Andon",
        description="Fabrika verisi ve bakım kılavuzları üzerinde çalışan yapay zekâ asistanı.",
        version=__version__,
        lifespan=lifespan,
    )
    uygulama.state.model_on_yukle = model_on_yukle
    uygulama.include_router(router)
    return uygulama


app = uygulama_olustur()
