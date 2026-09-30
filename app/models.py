"""API'nin girdi ve çıktı modelleri."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

HatTipi = Literal["pres", "kaynak", "montaj", "boya"]
ArizaTipi = Literal["hidrolik", "mekanik", "elektrik", "sensor", "yazilim", "pnomatik"]
Onem = Literal["dusuk", "orta", "yuksek"]


class Hat(BaseModel):
    id: int
    ad: str = Field(examples=["Pres 3"])
    tip: HatTipi
    makine_sayisi: int


class ArizaFiltresi(BaseModel):
    """`GET /arizalar` sorgu parametreleri. Tarihler gün olarak verilir, iki uç da dahildir."""

    model_config = ConfigDict(extra="forbid")

    hat: str | None = Field(
        None, description="Hat adı, büyük/küçük harf fark etmez", examples=["Pres 3"]
    )
    baslangic: date | None = Field(
        None, description="Bu günden itibaren (dahil)", examples=["2026-08-01"]
    )
    bitis: date | None = Field(None, description="Bu güne kadar (dahil)", examples=["2026-08-31"])
    ariza_tipi: ArizaTipi | None = None
    limit: int = Field(100, ge=1, le=1000, description="En fazla kaç kayıt dönsün")
    offset: int = Field(0, ge=0, description="Baştan kaç kayıt atlansın")

    @model_validator(mode="after")
    def _tarih_sirasi(self):
        if self.baslangic and self.bitis and self.baslangic > self.bitis:
            raise ValueError("baslangic, bitis'ten sonra olamaz")
        return self


class Ariza(BaseModel):
    id: int
    hat: str
    makine_kodu: str = Field(examples=["P3-HP"])
    makine_adi: str
    baslangic: datetime
    bitis: datetime | None = Field(description="Arıza hâlâ sürüyorsa boş")
    sure_dk: int | None = Field(description="Arıza hâlâ sürüyorsa boş")
    ariza_tipi: ArizaTipi
    onem: Onem
    hat_durdu: bool
    aciklama: str


class ArizaListesi(BaseModel):
    toplam: int = Field(description="Filtreye uyan arıza sayısı; limit ve offset'ten bağımsız")
    arizalar: list[Ariza]


class AramaIstegi(BaseModel):
    """`GET /ara` sorgu parametreleri."""

    model_config = ConfigDict(extra="forbid")

    soru: str = Field(min_length=3, max_length=500, examples=["pres hattı arıza ilk kontrol"])
    k: int = Field(3, ge=1, le=10, description="Kaç parça dönsün")


class AramaSonucu(BaseModel):
    dokuman_kodu: str = Field(examples=["PRES-BK-01"])
    dokuman_basligi: str
    sayfa: int
    bolum: str | None = Field(
        description="Başlık yolu, örn. '4. HİDROLİK ... > 4.1 Genel yaklaşım'"
    )
    icerik: str
    benzerlik: float = Field(description="Kosinüs benzerliği; 1'e yakın olan daha alakalı")


class SohbetIstegi(BaseModel):
    model_config = ConfigDict(extra="forbid")

    soru: str = Field(
        min_length=2,
        max_length=2000,
        examples=["Pres 3 hattında geçen ay kaç arıza oldu, bu tip arızada ilk neye bakmalıyım?"],
    )


class Kaynak(BaseModel):
    dokuman_kodu: str
    dokuman_basligi: str
    sayfa: int
    bolum: str | None


class AracCagrisiOzeti(BaseModel):
    ad: str
    argumanlar: dict | str
    hata: str | None = None


class Kullanim(BaseModel):
    model: str
    adim_sayisi: int
    girdi_token: int
    cikti_token: int
    maliyet_usd: float | None = Field(
        description="Ücretli katman liste fiyatıyla; bilinmiyorsa boş"
    )
    sure_ms: int


class SohbetCevabi(BaseModel):
    cevap: str
    kaynaklar: list[Kaynak] = Field(description="Agent'ın okuduğu kılavuz sayfaları")
    arac_cagrilari: list[AracCagrisiOzeti]
    kullanim: Kullanim


class KullanimOzeti(BaseModel):
    istek_sayisi: int
    hatali_istek: int
    toplam_girdi_token: int
    toplam_cikti_token: int
    toplam_maliyet_usd: float | None
    ortalama_sure_ms: int | None
    p95_sure_ms: int | None


class Token(BaseModel):
    access_token: str
    token_type: Literal["bearer"]
    kullanici_adi: str
    ad_soyad: str
    rol: Literal["operator", "bakim"]


class Saglik(BaseModel):
    veritabani: bool
