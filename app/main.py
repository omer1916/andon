"""Andon API.

Çalıştırmak için: uvicorn app.main:app --reload
Belgeler: http://localhost:8000/docs
"""

from collections.abc import Iterator
from contextlib import asynccontextmanager
from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app import __version__, sorgular
from app.db import havuz_olustur
from app.models import ArizaFiltresi, ArizaListesi, Hat, Saglik

router = APIRouter()


def baglanti(request: Request) -> Iterator[psycopg.Connection]:
    with request.app.state.havuz.connection() as conn:
        yield conn


Baglanti = Annotated[psycopg.Connection, Depends(baglanti)]


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


@asynccontextmanager
async def lifespan(uygulama: FastAPI):
    # Veritabanı kapalı olsa da uygulama açılsın; /saglik durumu 503 ile bildirir.
    havuz = havuz_olustur()
    havuz.open(wait=False)
    uygulama.state.havuz = havuz
    yield
    havuz.close()


def uygulama_olustur() -> FastAPI:
    """Her çağrıda yeni bir uygulama döner; testler birbirinin bağlantı havuzuna dokunmasın."""
    uygulama = FastAPI(
        title="Andon",
        description="Fabrika verisi ve bakım kılavuzları üzerinde çalışan yapay zekâ asistanı.",
        version=__version__,
        lifespan=lifespan,
    )
    uygulama.include_router(router)
    return uygulama


app = uygulama_olustur()
