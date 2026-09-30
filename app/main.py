"""Andon API.

Çalıştırmak için: uvicorn app.main:app --reload
Belgeler: http://localhost:8000/docs  (sağ üstteki "Authorize" ile giriş yapılır)
"""

import threading
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import openai
import psycopg
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, status
from fastapi import Path as FastAPIPath
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles

from app import __version__, agent, rag, sorgular
from app.auth import AktifKullanici, Kullanici, parola_dogrula, rol_gerekli, token_uret
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
    Token,
)
from app.rag import KILAVUZ_KLASORU
from app.tools import AracBaglami

STATIK_KLASOR = Path(__file__).resolve().parent / "static"

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


@router.post(
    "/giris",
    response_model=Token,
    responses={401: {"description": "Kullanıcı adı veya parola hatalı"}},
    summary="Kullanıcı adı ve parolayla giriş; 8 saat geçerli bir erişim token'ı döner",
)
def giris(form: Annotated[OAuth2PasswordRequestForm, Depends()], conn: Baglanti):
    satir = sorgular.kullanici_getir(conn, form.username)
    if not parola_dogrula(form.password, satir["parola_hash"] if satir else None):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Kullanıcı adı veya parola hatalı.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    kullanici = Kullanici(satir["kullanici_adi"], satir["ad_soyad"], satir["rol"])
    return Token(
        access_token=token_uret(kullanici),
        token_type="bearer",
        kullanici_adi=kullanici.kullanici_adi,
        ad_soyad=kullanici.ad_soyad,
        rol=kullanici.rol,
    )


@router.get("/hatlar", response_model=list[Hat], summary="Üretim hatlarını listeler")
def hatlar(conn: Baglanti, _: AktifKullanici):
    return sorgular.hatlari_getir(conn)


@router.get(
    "/arizalar",
    response_model=ArizaListesi,
    responses={404: {"description": "Verilen adda hat yok"}},
    summary="Arızaları hat, tarih aralığı ve tipe göre listeler",
)
def arizalar(filtre: Annotated[ArizaFiltresi, Query()], conn: Baglanti, _: AktifKullanici):
    if filtre.hat is not None and sorgular.hat_adini_bul(conn, filtre.hat) is None:
        gecerli = ", ".join(h["ad"] for h in sorgular.hatlari_getir(conn))
        raise HTTPException(404, f"'{filtre.hat}' adında bir hat yok. Geçerli hatlar: {gecerli}")
    toplam, kayitlar = sorgular.arizalari_getir(conn, **filtre.model_dump())
    return ArizaListesi(toplam=toplam, arizalar=kayitlar)


@router.get(
    "/ara",
    response_model=list[AramaSonucu],
    responses={503: {"description": "Kılavuzlar henüz yüklenmemiş"}},
    summary="Kılavuzlarda anlamsal arama; yalnızca kullanıcının rolünün görebildiği dokümanlarda",
)
def ara(
    istek: Annotated[AramaIstegi, Query()],
    conn: Baglanti,
    embedder: Annotated[Embedder, Depends(embedder_getir)],
    kullanici: AktifKullanici,
):
    try:
        return rag.dokuman_ara(conn, embedder, istek.soru, istek.k, erisim=kullanici.erisim)
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
    # Bağımlılıklar parametre sırasıyla çözülür: kimlik önce doğrulanmalı. Aksi hâlde giriş
    # yapmamış biri LLM ayarının eksik olduğunu 503 hatasından öğrenebilir.
    kullanici: AktifKullanici,
    conn: Baglanti,
    embedder: Annotated[Embedder, Depends(embedder_getir)],
    llm: Annotated[LLM, Depends(llm_getir)],
):
    baglam = AracBaglami(conn=conn, embedder=embedder, kullanici=kullanici)
    try:
        sonuc = agent.sohbet(istek.soru, llm, baglam)
    except agent.SohbetHatasi as hata:
        agent.kaydet(conn, istek.soru, kullanici.kullanici_adi, llm.saglayici, hata.sonuc)
        http_hatasi = _llm_hatasi(hata.__cause__)
        if http_hatasi is None:
            raise hata.__cause__ from None
        raise http_hatasi from None
    agent.kaydet(conn, istek.soru, kullanici.kullanici_adi, llm.saglayici, sonuc)

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
    "/dokumanlar/{kod}/pdf",
    response_class=FileResponse,
    responses={404: {"description": "Doküman yok ya da rolün görmeye yetkili değil"}},
    summary="Kılavuzun PDF'i; arayüzdeki kaynak bağlantıları bununla açılır",
)
def dokuman_pdf(
    kod: Annotated[str, FastAPIPath(pattern=r"^[A-Za-z0-9-]{1,32}$")],
    conn: Baglanti,
    kullanici: AktifKullanici,
):
    dokuman = sorgular.dokuman_getir(conn, kod)
    # Yetkisiz rol için de 404: dokümanın var olduğu bile anlaşılmasın.
    if dokuman is None or dokuman["erisim"] not in kullanici.erisim:
        raise HTTPException(404, "Doküman bulunamadı.")
    return FileResponse(
        KILAVUZ_KLASORU / dokuman["dosya"],
        media_type="application/pdf",
        content_disposition_type="inline",
        filename=dokuman["dosya"],
    )


@router.get("/", include_in_schema=False)
def arayuz():
    return FileResponse(STATIK_KLASOR / "index.html")


@router.get(
    "/kullanim",
    response_model=KullanimOzeti,
    responses={403: {"description": "Yalnızca bakım rolü"}},
    summary="Agent isteklerinin toplam token, maliyet ve süre özeti (yalnızca bakım rolü)",
)
def kullanim(conn: Baglanti, _: Annotated[Kullanici, Depends(rol_gerekli("bakim"))]):
    return sorgular.llm_kullanim_ozeti(conn)


async def _veri_hatasi(request: Request, hata: psycopg.DataError) -> JSONResponse:
    """Kullanıcı girdisi veritabanının kabul etmediği bir değer içeriyorsa (örneğin NUL
    baytı) 500 yerine 422 dön; iç hata ayrıntısı dışarı sızmasın."""
    return JSONResponse(status_code=422, content={"detail": "Girdi geçersiz karakter içeriyor."})


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
    uygulama.add_exception_handler(psycopg.DataError, _veri_hatasi)
    uygulama.include_router(router)
    uygulama.mount("/static", StaticFiles(directory=STATIK_KLASOR), name="static")
    return uygulama


app = uygulama_olustur()
