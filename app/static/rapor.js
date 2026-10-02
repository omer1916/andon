// Vardiya sonu raporu ekranı: POST /rapor/vardiya'nın cevabını gösterir, metnini kopyalatır.

import { durusAdi, isoGun, kpiKartlari, seviye, yuzde } from "./oee.js";

const SAYI = new Intl.NumberFormat("tr-TR");
const PARA = new Intl.NumberFormat("tr-TR", { style: "currency", currency: "USD", maximumFractionDigits: 4 });
const TARIH = new Intl.DateTimeFormat("tr-TR", { day: "numeric", month: "long", year: "numeric", weekday: "long" });
const SAAT = new Intl.DateTimeFormat("tr-TR", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Istanbul" });
const VARDIYA_SAATLERI = { 1: "07:00–15:00", 2: "15:00–23:00", 3: "23:00–07:00" };
const ONEM = { dusuk: "düşük", orta: "orta", yuksek: "yüksek" };
const DUSUS_ESIGI = 0.05; // son 7 güne göre 5 puandan fazla düşüş işaretlenir

const $ = (id) => document.getElementById(id);

export function raporEkrani({ api, eleman }) {
  const form = $("rapor-formu");
  let sonRapor = null;

  form.elements.secim.addEventListener("change", secimiGuncelle);
  form.addEventListener("submit", (olay) => {
    olay.preventDefault();
    hazirla();
  });
  $("rapor-kopyala").addEventListener("click", kopyala);
  $("rapor-yazdir").addEventListener("click", () => window.print());

  function secimiGuncelle() {
    const sec = form.elements.secim.value === "sec";
    for (const alan of form.querySelectorAll("[data-secili-vardiya]")) alan.hidden = !sec;
    form.elements.tarih.required = sec;
  }

  function durum(metin) {
    $("rapor-durum").textContent = metin ?? "";
    $("rapor-durum").hidden = !metin;
  }

  async function hazirla() {
    const dugme = $("rapor-dugmesi");
    const govde =
      form.elements.secim.value === "sec"
        ? { tarih: form.elements.tarih.value, vardiya: Number(form.elements.vardiya.value) }
        : {};
    dugme.disabled = true;
    dugme.textContent = "Hazırlanıyor…";
    durum("Veriler toplanıyor, yorum yazılıyor…");
    try {
      const cevap = await api("/rapor/vardiya", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(govde),
      });
      const veri = await cevap.json().catch(() => ({}));
      if (!cevap.ok) {
        durum(typeof veri.detail === "string" ? veri.detail : `Rapor hazırlanamadı (HTTP ${cevap.status}).`);
        return;
      }
      durum(null);
      ciz(veri);
    } catch (hata) {
      if (hata.name !== "OturumBitti") durum("Sunucuya ulaşılamadı; bağlantıyı kontrol edip tekrar deneyin.");
    } finally {
      dugme.disabled = false;
      dugme.textContent = "Raporu hazırla";
    }
  }

  async function kopyala() {
    if (!sonRapor) return;
    const dugme = $("rapor-kopyala");
    try {
      await navigator.clipboard.writeText(sonRapor.markdown);
      dugme.textContent = "Kopyalandı";
    } catch {
      dugme.textContent = "Kopyalanamadı";
    }
    setTimeout(() => (dugme.textContent = "Metni kopyala"), 2000);
  }

  function ciz(r) {
    sonRapor = r;
    $("rapor-icerik").hidden = false;
    $("rapor-adi").textContent =
      `${TARIH.format(new Date(`${r.tarih}T12:00`))} · ${r.vardiya}. vardiya (${VARDIYA_SAATLERI[r.vardiya]})`;
    $("rapor-kpi").replaceChildren(...kpiKartlari(eleman, r.fabrika));
    yorum(r);
    $("rapor-hatlar").replaceChildren(hatTablosu(r.hatlar));
    $("rapor-duruslar").replaceChildren(liste(r.duruslar, durusMetni, "Bu vardiyada duruş yok."));
    $("rapor-arizalar").replaceChildren(
      liste(r.arizalar, arizaMetni, "Bu vardiyada yeni arıza başlamadı."),
    );
    $("rapor-talep-baslik").textContent =
      `Açık bakım talepleri (${SAYI.format(r.acik_talep_sayisi)})`;
    $("rapor-talepler").replaceChildren(liste(r.acik_talepler, talepMetni, "Açık talep yok."));
    $("rapor-stok").replaceChildren(
      liste(r.kritik_stok, parcaMetni, "Bütün parçalar minimum seviyenin üstünde."),
    );
    const k = r.kullanim;
    const parcalar = [`${(k.sure_ms / 1000).toLocaleString("tr-TR", { maximumFractionDigits: 1 })} sn`];
    if (k.deneme_sayisi) {
      parcalar.push(`${k.deneme_sayisi} LLM çağrısı`, `${SAYI.format(k.girdi_token + k.cikti_token)} token`);
      if (k.maliyet_usd != null) parcalar.push(PARA.format(k.maliyet_usd));
    } else {
      parcalar.push("LLM kullanılmadı");
    }
    $("rapor-kullanim").textContent = `Hazırlanma: ${parcalar.join(" · ")}`;
    $("rapor-icerik").focus();
  }

  function yorum(r) {
    const llm = r.yorum_kaynagi === "llm";
    const rozet = $("rapor-yorum-kaynagi");
    rozet.textContent = llm ? "Asistan yazdı · sayılar denetlendi" : "Kurallarla yazıldı";
    rozet.className = `rozet ${llm ? "llm" : "kural"}`;
    $("rapor-ozet").textContent = r.yorum.ozet;
    $("rapor-dikkat").replaceChildren(...maddeler("Dikkat", r.yorum.dikkat));
    $("rapor-oneriler").replaceChildren(...maddeler("Öneriler", r.yorum.oneriler));
    $("rapor-yorum-notu").textContent = r.yorum_notu ?? "";
    $("rapor-yorum-notu").hidden = !r.yorum_notu;
  }

  function maddeler(baslik, satirlar) {
    if (!satirlar.length) return [];
    const ul = eleman("ul");
    for (const satir of satirlar) ul.append(eleman("li", null, satir));
    return [eleman("h4", null, baslik), ul];
  }

  function liste(ogeler, metin, bos) {
    if (!ogeler.length) return eleman("p", "soluk", bos);
    const ul = eleman("ul", "rapor-listesi");
    for (const oge of ogeler) ul.append(eleman("li", null, metin(oge)));
    return ul;
  }

  function durusMetni(d) {
    const makine = d.makine_kodu ? ` (${d.makine_kodu})` : "";
    return `${d.hat}: ${durusAdi(d)}${makine}, ${SAYI.format(d.sure_dk)} dk`;
  }

  function arizaMetni(a) {
    const saat = SAAT.format(new Date(a.baslangic));
    const sure = a.vardiya_sonunda_suruyor ? "vardiya sonunda sürüyordu" : `${SAYI.format(a.sure_dk)} dk`;
    const durdu = a.hat_durdu ? ", hattı durdurdu" : "";
    return `${saat} ${a.makine_kodu} (${a.hat}): ${a.ariza_tipi}, ${ONEM[a.onem]} önem${durdu}, ${sure}. ${a.aciklama}`;
  }

  function talepMetni(t) {
    return `#${t.id} ${t.makine_kodu} · ${ONEM[t.oncelik]} öncelik: ${t.aciklama}`;
  }

  function parcaMetni(p) {
    return `${p.parca_kodu} ${p.ad}: ${p.miktar} / ${p.min_miktar} ${p.birim}`;
  }

  function hatTablosu(hatlar) {
    const tablo = eleman("table", "oee-tablo");
    tablo.append(eleman("thead"), eleman("tbody"));
    const baslik = eleman("tr");
    for (const ad of ["Hat", "OEE", "Kull.", "Perf.", "Kalite", "Duruş", "Son 7 gün"]) {
      const th = eleman("th", null, ad);
      th.scope = "col";
      baslik.append(th);
    }
    tablo.tHead.append(baslik);
    for (const h of hatlar) {
      const satir = eleman("tr");
      const ad = eleman("th", null, h.hat);
      ad.scope = "row";
      const oee = eleman("td");
      oee.append(eleman("span", `nokta ${seviye(h.oee)}`), document.createTextNode(yuzde(h.oee)));
      const yedi = eleman("td", null, yuzde(h.son_7_gun_oee));
      if (h.oee != null && h.son_7_gun_oee != null && h.oee < h.son_7_gun_oee - DUSUS_ESIGI) {
        yedi.prepend(eleman("span", "dusus", "▼ "));
        yedi.title = "Bu vardiyanın OEE'si son 7 günün 5 puandan fazla altında";
      }
      satir.append(
        ad,
        oee,
        eleman("td", null, yuzde(h.kullanilabilirlik)),
        eleman("td", null, yuzde(h.performans)),
        eleman("td", null, yuzde(h.kalite)),
        eleman("td", null, `${SAYI.format(h.durus_dk)} dk`),
        yedi,
      );
      tablo.tBodies[0].append(satir);
    }
    return tablo;
  }

  return {
    goster() {
      if (!form.elements.tarih.value) {
        const dun = new Date();
        dun.setDate(dun.getDate() - 1);
        form.elements.tarih.value = isoGun(dun);
        form.elements.tarih.max = isoGun(new Date());
      }
      secimiGuncelle();
    },
  };
}
