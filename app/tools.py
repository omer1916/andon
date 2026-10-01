"""Agent'ın kullanabildiği araçlar.

LLM'e serbest SQL yazdırılmaz; yalnızca buradaki parametreli fonksiyonları çağırabilir.
- Veritabanına giden her değer SQL parametresidir; LLM bir tabloyu silemez, başka bir
  tabloyu okuyamaz.
- Her aracın girdisi bir Pydantic modeliyle doğrulanır; LLM'e verilen JSON şeması da aynı
  modelden üretilir, ikisi birbirinden kopamaz.
- Hatalar istisna olarak değil, LLM'in okuyup düzeltebileceği bir mesaj olarak döner
  ("'Pres 9' adında hat yok. Geçerli hatlar: ...").
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import psycopg
from pydantic import BaseModel, Field, ValidationError, model_validator

from app import rag, sorgular
from app.auth import Kullanici
from app.embedding import Embedder
from app.models import ArizaTipi, Onem

# Bir sohbet isteğinde açılabilecek en fazla bakım talebi. LLM aynı talebi döngüde
# tekrar tekrar açmasın.
MAKS_TALEP_SAYISI = 1


class AracHatasi(Exception):
    """LLM'e geri gönderilecek, düzeltilebilir hata."""


@dataclass
class AracBaglami:
    """Araçların çalıştığı ortam. Kullanıcı (ve dolayısıyla doküman erişimi) token'dan gelir;
    LLM'in gönderdiği argümanlarda yer almaz, LLM tarafından değiştirilemez."""

    conn: psycopg.Connection
    embedder: Embedder
    kullanici: Kullanici
    kaynaklar: list[dict] = field(default_factory=list)  # dokuman_ara'nın bulduğu parçalar
    acilan_talepler: list[int] = field(default_factory=list)


class ArizaSayGirdisi(BaseModel):
    hat: str | None = Field(None, description="Hat adı, örn. 'Pres 3'. Boş bırakılırsa tüm hatlar.")
    baslangic: date = Field(description="Aralığın ilk günü (dahil), YYYY-AA-GG")
    bitis: date = Field(description="Aralığın son günü (dahil), YYYY-AA-GG")
    ariza_tipi: ArizaTipi | None = Field(None, description="Yalnızca bu tipteki arızalar")

    @model_validator(mode="after")
    def _tarih_sirasi(self):
        if self.baslangic > self.bitis:
            raise ValueError("baslangic, bitis'ten sonra olamaz")
        return self


class DokumanAraGirdisi(BaseModel):
    soru: str = Field(min_length=3, description="Kılavuzlarda aranacak konu, doğal dille")
    # 3 değil 5: iki konulu sorularda (sayı + kural) aranan kural 4.-5. sırada kalabiliyor.
    # Değerlendirmede "kök neden analizi" kuralı 5. sıradaydı ve k=3 ile kaçırıldı.
    k: int = Field(5, ge=1, le=8, description="Kaç parça dönsün")


class StokSorgulaGirdisi(BaseModel):
    parca_kodu: str | None = Field(None, description="Stok kodu, örn. 'SNS-002'")
    sadece_kritik: bool = Field(False, description="Yalnızca minimum seviyenin altındaki parçalar")


class BakimTalebiGirdisi(BaseModel):
    makine_kodu: str = Field(description="Makine kodu, örn. 'P3-HP'")
    aciklama: str = Field(min_length=5, max_length=500, description="Sorunun kısa açıklaması")
    oncelik: Onem


class OeeGirdisi(BaseModel):
    hat: str | None = Field(None, description="Hat adı, örn. 'Pres 3'. Boşsa bütün fabrika.")
    baslangic: date = Field(description="Aralığın ilk günü (dahil), YYYY-AA-GG")
    bitis: date = Field(description="Aralığın son günü (dahil), YYYY-AA-GG")

    @model_validator(mode="after")
    def _tarih_sirasi(self):
        if self.baslangic > self.bitis:
            raise ValueError("baslangic, bitis'ten sonra olamaz")
        return self


def _hat_dogrula(b: AracBaglami, hat: str | None) -> None:
    if hat is not None and sorgular.hat_adini_bul(b.conn, hat) is None:
        gecerli = ", ".join(h["ad"] for h in sorgular.hatlari_getir(b.conn))
        raise AracHatasi(f"'{hat}' adında bir hat yok. Geçerli hatlar: {gecerli}")


def _ariza_say(b: AracBaglami, g: ArizaSayGirdisi) -> dict:
    _hat_dogrula(b, g.hat)
    ozet = sorgular.ariza_ozeti(b.conn, **g.model_dump())
    return {**g.model_dump(mode="json"), **ozet}


DURUS_ADLARI = {
    "urun_degisimi": "ürün değişimi (kalıp, fikstür, renk, model)",
    "malzeme_bekleme": "malzeme bekleme",
}
BILESENLER = ("oee", "kullanilabilirlik", "performans", "kalite")


def yuzde(oran: float | None) -> float | None:
    """LLM hesap yapmasın diye oranlar hazır yüzde olarak verilir (0,7829 -> 78,3)."""
    return None if oran is None else round(oran * 100, 1)


def _oee_hesapla(b: AracBaglami, g: OeeGirdisi) -> dict:
    _hat_dogrula(b, g.hat)
    f = g.model_dump()
    (toplam,) = sorgular.oee_hesapla(b.conn, **f)
    if toplam["vardiya_sayisi"] == 0:
        aralik = sorgular.uretim_araligi(b.conn)
        ek = f" Üretim verisi {aralik[0]} ile {aralik[1]} arasında." if aralik else ""
        raise AracHatasi(f"Bu aralıkta tamamlanmış vardiya kaydı yok.{ek}")

    sonuc = {
        **g.model_dump(mode="json"),
        **{f"{ad}_yuzde": yuzde(toplam[ad]) for ad in BILESENLER},
        **{k: toplam[k] for k in ("vardiya_sayisi", "planli_sure_dk", "durus_dk")},
        "toplam_adet": toplam["toplam_adet"],
        "hurda_adet": toplam["hurda_adet"],
        "vardiyalara_gore_oee_yuzde": {
            str(v["vardiya"]): yuzde(v["oee"])
            for v in sorgular.oee_hesapla(b.conn, **f, grup="vardiya")
        },
        "en_buyuk_duruslar": [
            {
                "neden": DURUS_ADLARI.get(d["neden"]) or f"arıza ({d['ariza_tipi']})",
                "sure_dk": d["sure_dk"],
                "adet": d["adet"],
                "pay_yuzde": yuzde(d["pay"]),
            }
            for d in sorgular.durus_pareto(b.conn, **f)[:5]
        ],
        "en_cok_durduran_makineler": sorgular.durduran_makineler(b.conn, **f, limit=3),
    }
    if g.hat is None:
        sonuc["hatlara_gore_oee_yuzde"] = {
            h["hat"]: yuzde(h["oee"]) for h in sorgular.oee_hesapla(b.conn, **f, grup="hat")
        }
    return sonuc


def _dokuman_ara(b: AracBaglami, g: DokumanAraGirdisi) -> list[dict]:
    sonuclar = rag.dokuman_ara(b.conn, b.embedder, g.soru, g.k, erisim=b.kullanici.erisim)
    b.kaynaklar.extend(sonuclar)
    return [
        {
            "dokuman_kodu": s["dokuman_kodu"],
            "dokuman_basligi": s["dokuman_basligi"],
            "sayfa": s["sayfa"],
            "bolum": s["bolum"],
            "icerik": s["icerik"],
        }
        for s in sonuclar
    ]


def _stok_sorgula(b: AracBaglami, g: StokSorgulaGirdisi) -> list[dict]:
    parcalar = sorgular.stok_getir(b.conn, **g.model_dump())
    if g.parca_kodu and not parcalar:
        raise AracHatasi(f"'{g.parca_kodu}' kodlu bir parça stokta tanımlı değil.")
    return parcalar


def _bakim_talebi_olustur(b: AracBaglami, g: BakimTalebiGirdisi) -> dict:
    if len(b.acilan_talepler) >= MAKS_TALEP_SAYISI:
        raise AracHatasi("Bu istekte zaten bir bakım talebi açıldı; ikinci talep açılamaz.")
    makine = sorgular.makine_bul(b.conn, g.makine_kodu)
    if makine is None:
        gecerli = ", ".join(sorgular.makine_kodlari(b.conn))
        raise AracHatasi(f"'{g.makine_kodu}' kodlu makine yok. Geçerli kodlar: {gecerli}")
    talep_id = sorgular.bakim_talebi_ekle(
        b.conn,
        makine_id=makine["id"],
        aciklama=g.aciklama,
        oncelik=g.oncelik,
        olusturan=b.kullanici.kullanici_adi,
    )
    b.acilan_talepler.append(talep_id)
    return {"talep_id": talep_id, "makine": makine, "oncelik": g.oncelik, "durum": "acik"}


@dataclass(frozen=True)
class Arac:
    ad: str
    aciklama: str
    girdi: type[BaseModel]
    calistir: Callable[[AracBaglami, Any], Any]


ARACLAR = {
    a.ad: a
    for a in [
        Arac(
            "ariza_say",
            "Bir hattaki (ya da tüm hatlardaki) arızaları verilen tarih aralığında sayar; "
            "arıza tiplerine ve makinelere göre dağılımı da döner.",
            ArizaSayGirdisi,
            _ariza_say,
        ),
        Arac(
            "dokuman_ara",
            "Bakım kılavuzları, operatör talimatları ve kalite prosedürlerinde anlamsal arama "
            "yapar. Doküman kodu ve sayfa numarasıyla en alakalı parçaları döner.",
            DokumanAraGirdisi,
            _dokuman_ara,
        ),
        Arac(
            "oee_hesapla",
            "Bir hattın (ya da bütün fabrikanın) verilen tarih aralığındaki OEE'sini ve "
            "bileşenlerini (kullanılabilirlik, performans, kalite) yüzde olarak hesaplar. "
            "Vardiyalara göre OEE'yi, en büyük duruş nedenlerini (arıza tipi, ürün değişimi, "
            "malzeme bekleme) ve hattı en uzun durduran makineleri de döner.",
            OeeGirdisi,
            _oee_hesapla,
        ),
        Arac(
            "stok_sorgula",
            "Yedek parça stoğunu sorgular: bir parçanın miktarı ve yeri ya da minimum seviyenin "
            "altındaki parçalar.",
            StokSorgulaGirdisi,
            _stok_sorgula,
        ),
        Arac(
            "bakim_talebi_olustur",
            "Bir makine için bakım talebi açar ve talep numarasını döner. Yalnızca kullanıcı "
            "açıkça talep açılmasını istediğinde çağrılmalıdır.",
            BakimTalebiGirdisi,
            _bakim_talebi_olustur,
        ),
    ]
}


def _sadelestir(sema: Any) -> Any:
    """Pydantic şemasını LLM'lerin sorunsuz okuduğu sade biçime çevirir.

    `str | None` alanı `anyOf: [{string}, {null}]` olarak üretilir; bazı sağlayıcılar anyOf'u
    desteklemez. Alan zaten zorunlu listesinde olmadığı için null seçeneği atılır. Başlıklar
    ve None varsayılanları da gereksiz token'dır.
    """
    if isinstance(sema, list):
        return [_sadelestir(s) for s in sema]
    if not isinstance(sema, dict):
        return sema
    sade = {k: _sadelestir(v) for k, v in sema.items() if k != "title"}
    if "anyOf" in sade:
        secenekler = [s for s in sade["anyOf"] if s != {"type": "null"}]
        if len(secenekler) == 1:
            del sade["anyOf"]
            sade = {**secenekler[0], **sade}
    if sade.get("default", 0) is None:
        del sade["default"]
    return sade


def arac_semalari() -> list[dict]:
    """Araçların OpenAI "tools" biçimindeki tanımları."""
    return [
        {
            "type": "function",
            "function": {
                "name": arac.ad,
                "description": arac.aciklama,
                "parameters": _sadelestir(arac.girdi.model_json_schema()),
            },
        }
        for arac in ARACLAR.values()
    ]


def arac_calistir(ad: str, argumanlar_json: str, baglam: AracBaglami) -> dict:
    """Aracı çalıştırır; sonucu ya da LLM'in okuyabileceği hata mesajını döner."""
    arac = ARACLAR.get(ad)
    if arac is None:
        return {"hata": f"'{ad}' adında bir araç yok. Araçlar: {', '.join(ARACLAR)}"}
    try:
        girdi = arac.girdi.model_validate_json(argumanlar_json or "{}")
    except ValidationError as hata:
        sorunlar = "; ".join(
            f"{'.'.join(map(str, e['loc'])) or 'girdi'}: {e['msg']}" for e in hata.errors()
        )
        return {"hata": f"Geçersiz argüman: {sorunlar}"}
    try:
        return {"sonuc": arac.calistir(baglam, girdi)}
    except AracHatasi as hata:
        return {"hata": str(hata)}
    except psycopg.DataError:
        # Örneğin argümanda NUL baytı: veritabanı reddeder; LLM'e düzeltilebilir mesaj dön.
        return {"hata": "Argüman geçersiz karakter içeriyor."}
