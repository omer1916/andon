// OEE paneli: GET /oee'den gelen veriyi kartlar, günlük grafik, Pareto ve tablolarla gösterir.
// Renkler andon ışıklarıyla aynı: yeşil dünya standardı (%85+), sarı orta, kırmızı düşük.

const YUZDE = new Intl.NumberFormat("tr-TR", { style: "percent", minimumFractionDigits: 1, maximumFractionDigits: 1 });
const SAYI = new Intl.NumberFormat("tr-TR");
const GUN_ETIKETI = new Intl.DateTimeFormat("tr-TR", { day: "numeric", month: "short" });
const TARIH_ARALIGI = new Intl.DateTimeFormat("tr-TR", { day: "numeric", month: "short", year: "numeric" });
const DUNYA_STANDARDI = 0.85;
const DUSUK = 0.65;
const VARDIYA_SAATLERI = { 1: "07-15", 2: "15-23", 3: "23-07" };
const DONEMLER = {
  7: "son 7 günde",
  30: "son 30 günde",
  "gecen-ay": "geçen ay",
  "bu-ay": "bu ay",
  180: "son 6 ayda",
};
const NEDEN_ADLARI = {
  urun_degisimi: "Ürün değişimi",
  malzeme_bekleme: "Malzeme bekleme",
};
const ARIZA_TIPLERI = {
  hidrolik: "hidrolik",
  mekanik: "mekanik",
  elektrik: "elektrik",
  sensor: "sensör",
  yazilim: "yazılım",
  pnomatik: "pnömatik",
};

const $ = (id) => document.getElementById(id);

export function yuzde(oran) {
  return oran == null ? "–" : YUZDE.format(oran);
}

export function seviye(oran) {
  if (oran == null) return "yok";
  if (oran >= DUNYA_STANDARDI) return "yesil";
  if (oran >= DUSUK) return "sari";
  return "kirmizi";
}

// Durum hiçbir yerde yalnızca renkle verilmez: andon yeşili ile kırmızısı kırmızı-yeşil renk
// körlüğünde (deuteranopi) neredeyse aynı görünür (OKLab ΔE 5, gereken en az 8), sarı da beyaz
// zeminde 1,9:1 kontrastta kalır. Her seviyenin ayrı bir şekli ve adı var.
export const SEVIYE_ISARETLERI = {
  yesil: ["●", "iyi"],
  sari: ["◆", "orta"],
  kirmizi: ["▼", "düşük"],
  yok: ["–", "veri yok"],
};

export function seviyeEtiketi(eleman, oran) {
  const s = seviye(oran);
  const [isaret, ad] = SEVIYE_ISARETLERI[s];
  const etiket = eleman("span", `seviye-etiketi ${s}`);
  const sekil = eleman("span", "seviye-isareti", isaret); // renk şekilde, yazı metin renginde
  sekil.setAttribute("aria-hidden", "true");
  etiket.append(sekil, ad);
  return etiket;
}

export function durusAdi(d) {
  return NEDEN_ADLARI[d.neden] ?? `Arıza: ${ARIZA_TIPLERI[d.ariza_tipi] ?? d.ariza_tipi}`;
}

export function kpiKarti(eleman, baslik, oran, aciklama, ana = false) {
  const kart = eleman("div", `kpi${ana ? " ana" : ""} ${seviye(oran)}`);
  const deger = eleman("div", "kpi-satiri");
  deger.append(eleman("strong", "kpi-deger", yuzde(oran)), seviyeEtiketi(eleman, oran));
  kart.append(eleman("span", "kpi-baslik", baslik), deger);
  const cubuk = eleman("span", "kpi-cubuk");
  cubuk.style.setProperty("--oran", String(Math.min(1, oran ?? 0)));
  kart.append(cubuk, eleman("span", "kpi-aciklama", aciklama));
  return kart;
}

// OEE ve bileşenlerinin dört kartı; OEE panelinde ve vardiya raporunda aynı.
export function kpiKartlari(eleman, t) {
  return [
    kpiKarti(eleman, "OEE", t.oee, "Kullanılabilirlik × performans × kalite", true),
    kpiKarti(
      eleman,
      "Kullanılabilirlik",
      t.kullanilabilirlik,
      `${SAYI.format(t.durus_dk)} dk duruş / ${SAYI.format(t.planli_sure_dk)} dk planlı`,
    ),
    kpiKarti(eleman, "Performans", t.performans, `${SAYI.format(t.toplam_adet)} adet üretildi`),
    kpiKarti(eleman, "Kalite", t.kalite, `${SAYI.format(t.hurda_adet)} adet hurda`),
  ];
}

// "2026-09-03", "2026-10-02" -> "3 Eyl – 2 Eki 2026" (ekranda ISO tarih gösterilmez).
export function aralikMetni(baslangic, bitis) {
  return TARIH_ARALIGI.formatRange(new Date(`${baslangic}T12:00`), new Date(`${bitis}T12:00`));
}

export function isoGun(tarih) {
  const ay = String(tarih.getMonth() + 1).padStart(2, "0");
  const gun = String(tarih.getDate()).padStart(2, "0");
  return `${tarih.getFullYear()}-${ay}-${gun}`;
}

// Dönem seçeneğini [başlangıç, bitiş] günlerine çevirir; iki uç da dahil.
export function donemAraligi(donem, bugun = new Date()) {
  const gun = (y, a, g) => isoGun(new Date(y, a, g));
  const [y, a, g] = [bugun.getFullYear(), bugun.getMonth(), bugun.getDate()];
  if (donem === "gecen-ay") return [gun(y, a - 1, 1), gun(y, a, 0)];
  if (donem === "bu-ay") return [gun(y, a, 1), gun(y, a, g)];
  return [gun(y, a, g - Number(donem) + 1), gun(y, a, g)];
}

export function oeeEkrani({ api, eleman, asistanaSor }) {
  let hatlarYuklendi = false;
  let sonIstek = 0;

  $("oee-filtre").addEventListener("change", yukle);
  $("oee-filtre").addEventListener("submit", (olay) => olay.preventDefault());
  $("oee-sor").addEventListener("click", () => asistanaSor(soru()));

  function secim() {
    const form = $("oee-filtre").elements;
    return { hat: form.hat.value, donem: form.donem.value };
  }

  // Filtre adreste tutulur (#oee?hat=Pres+3&donem=7); yenileyince ve paylaşınca aynı görünüm.
  function adrestenOku() {
    const p = new URLSearchParams(location.hash.split("?")[1] ?? "");
    const form = $("oee-filtre").elements;
    for (const ad of ["hat", "donem"]) {
      const deger = p.get(ad);
      if (deger !== null && [...form[ad].options].some((s) => s.value === deger)) form[ad].value = deger;
    }
  }

  function adreseYaz() {
    const { hat, donem } = secim();
    const p = new URLSearchParams({ donem });
    if (hat) p.set("hat", hat);
    history.replaceState(null, "", `#oee?${p}`);
  }

  // Panelle asistan aynı aralığa baksın diye tarihler soruda açıkça yazılır; "son 30 gün"ü
  // model kendi yorumlarsa (örneğin takvim ayı) paneldekinden farklı bir sayı verebilir.
  function soru() {
    const { hat, donem } = secim();
    const [baslangic, bitis] = donemAraligi(donem);
    const yer = hat ? `${hat} hattında` : "Fabrikada";
    return (
      `${yer} ${DONEMLER[donem]} (${baslangic} – ${bitis}) OEE neden bu seviyede, ` +
      "en büyük kayıp ne ve ne yapmalıyız?"
    );
  }

  async function hatlariYukle() {
    if (hatlarYuklendi) return;
    const cevap = await api("/hatlar");
    if (!cevap.ok) return;
    const secenekler = (await cevap.json()).map((h) => new Option(h.ad, h.ad));
    $("oee-filtre").elements.hat.append(...secenekler);
    hatlarYuklendi = true;
  }

  async function yukle() {
    const istekNo = ++sonIstek;
    const { hat, donem } = secim();
    const [baslangic, bitis] = donemAraligi(donem);
    const parametreler = new URLSearchParams({ baslangic, bitis });
    if (hat) parametreler.set("hat", hat);
    adreseYaz();
    $("oee-durum").textContent = "Yükleniyor…";
    $("oee-durum").hidden = false;
    $("oee-icerik").setAttribute("aria-busy", "true");
    try {
      const cevap = await api(`/oee?${parametreler}`);
      if (istekNo !== sonIstek) return; // kullanıcı bu arada başka bir seçim yaptı
      if (!cevap.ok) throw new Error(`HTTP ${cevap.status}`);
      ciz(await cevap.json(), { hat, baslangic, bitis });
      $("oee-durum").hidden = true;
    } catch (hata) {
      if (hata.name === "OturumBitti") return;
      $("oee-durum").textContent = "OEE verisi alınamadı; filtreyi değiştirip tekrar deneyin.";
    } finally {
      $("oee-icerik").removeAttribute("aria-busy");
    }
  }

  function ciz(veri, { hat, baslangic, bitis }) {
    const t = veri.toplam;
    $("oee-aralik").textContent =
      `${hat || "Bütün fabrika"} · ${aralikMetni(baslangic, bitis)} · ${SAYI.format(t.vardiya_sayisi)} vardiya`;
    $("oee-bos").hidden = t.vardiya_sayisi > 0;
    $("oee-icerik").hidden = t.vardiya_sayisi === 0;
    if (t.vardiya_sayisi === 0) return;

    $("oee-kpi").replaceChildren(...kpiKartlari(eleman, t));
    $("oee-trend").replaceChildren(trend(veri.gunluk));
    $("oee-pareto").replaceChildren(pareto(veri.duruslar));
    $("oee-hatlar").replaceChildren(hatTablosu(veri.hatlara_gore));
    $("oee-vardiyalar").replaceChildren(vardiyalar(veri.vardiyalara_gore));
    $("oee-makineler").replaceChildren(makineler(veri.makineler));
  }

  // Günlük OEE: her gün bir sütun; sütunun tamamı dokunma/fare hedefi, çubuk en fazla 24 px.
  // Değer ipucuyla (fare, dokunma, ok tuşları) ve altındaki tabloyla okunur; ipucu tek yol değil.
  function trend(gunler) {
    const kap = eleman("div", "trend");
    const degerler = gunler.filter((g) => g.oee != null).map((g) => g.oee);
    const ortalama = degerler.reduce((a, b) => a + b, 0) / (degerler.length || 1);
    const ozet =
      `Günlük OEE, ${gunler.length} gün. En düşük ${yuzde(Math.min(...degerler))}, ` +
      `en yüksek ${yuzde(Math.max(...degerler))}, gün ortalaması ${yuzde(ortalama)}. ` +
      "Ok tuşlarıyla günler arasında gezinilir; değerler alttaki tabloda da var.";

    const alan = eleman("div", "trend-alan");
    alan.tabIndex = 0;
    alan.setAttribute("role", "img");
    alan.setAttribute("aria-label", ozet);
    const sutunlar = eleman("div", "trend-sutunlar");
    sutunlar.style.setProperty("--gun", String(gunler.length));
    for (const [i, g] of gunler.entries()) {
      const sutun = eleman("span", "trend-gun");
      sutun.dataset.i = String(i);
      const cubuk = eleman("span", `trend-cubuk ${seviye(g.oee)}`);
      cubuk.style.setProperty("--oran", String(g.oee ?? 0));
      sutun.append(cubuk);
      sutunlar.append(sutun);
    }
    for (const [esik, sinif] of [[DUNYA_STANDARDI, "ust"], [DUSUK, "alt"]]) {
      const cizgi = eleman("span", `trend-esik ${sinif}`);
      cizgi.style.setProperty("--oran", String(esik));
      cizgi.append(eleman("span", "trend-esik-adi", yuzde(esik).replace(",0", "")));
      sutunlar.append(cizgi);
    }
    const ipucu = eleman("div", "trend-ipucu");
    ipucu.hidden = true;
    ipucu.setAttribute("aria-hidden", "true"); // ekran okuyucu için tablo var
    alan.append(sutunlar, ipucu);

    let etkin = null;
    function goster(i) {
      if (etkin != null) sutunlar.children[etkin].classList.remove("etkin");
      etkin = i;
      if (i == null) {
        ipucu.hidden = true;
        return;
      }
      const sutun = sutunlar.children[i];
      sutun.classList.add("etkin");
      const g = gunler[i];
      ipucu.replaceChildren(
        eleman("strong", null, yuzde(g.oee)),
        eleman("span", null, GUN_ETIKETI.format(new Date(`${g.gun}T12:00`))),
        seviyeEtiketi(eleman, g.oee),
      );
      ipucu.hidden = false;
      // Kutucuk sütunun üstünde ortalanır, alanın dışına taşmaz.
      const a = alan.getBoundingClientRect();
      const s = sutun.getBoundingClientRect();
      const genislik = ipucu.offsetWidth;
      const orta = s.left - a.left + s.width / 2;
      ipucu.style.left = `${Math.min(Math.max(orta - genislik / 2, 0), a.width - genislik)}px`;
    }
    sutunlar.addEventListener("pointerover", (olay) => {
      const sutun = olay.target.closest(".trend-gun");
      if (sutun) goster(Number(sutun.dataset.i));
    });
    // Dokunmada pointerleave parmak kalkar kalkmaz gelir; ipucu odak gidene kadar kalsın.
    alan.addEventListener("pointerleave", (olay) => {
      if (olay.pointerType === "mouse" && document.activeElement !== alan) goster(null);
    });
    alan.addEventListener("focus", () => goster(etkin ?? gunler.length - 1));
    alan.addEventListener("blur", () => goster(null));
    alan.addEventListener("keydown", (olay) => {
      const son = gunler.length - 1;
      const yeni = {
        ArrowLeft: Math.max((etkin ?? son) - 1, 0),
        ArrowRight: Math.min((etkin ?? son) + 1, son),
        Home: 0,
        End: son,
      }[olay.key];
      if (yeni === undefined) return;
      olay.preventDefault();
      goster(yeni);
    });

    const eksen = eleman("div", "trend-eksen soluk");
    eksen.append(
      eleman("span", null, GUN_ETIKETI.format(new Date(`${gunler[0].gun}T12:00`))),
      eleman("span", null, "kesikli çizgiler: %85 ve %65"),
      eleman("span", null, GUN_ETIKETI.format(new Date(`${gunler.at(-1).gun}T12:00`))),
    );
    kap.append(alan, eksen, gunlukTablo(gunler));
    return kap;
  }

  function gunlukTablo(gunler) {
    const kutu = eleman("details", "tablo-gorunumu");
    kutu.append(eleman("summary", null, "Tablo olarak göster"));
    const tablo = eleman("table", "oee-tablo");
    tablo.append(eleman("thead"), eleman("tbody"));
    const baslik = eleman("tr");
    for (const ad of ["Gün", "OEE", "Durum"]) {
      const th = eleman("th", null, ad);
      th.scope = "col";
      baslik.append(th);
    }
    tablo.tHead.append(baslik);
    for (const g of [...gunler].reverse()) {
      const satir = eleman("tr");
      const gun = eleman("th", null, GUN_ETIKETI.format(new Date(`${g.gun}T12:00`)));
      gun.scope = "row";
      const durum = eleman("td");
      durum.append(seviyeEtiketi(eleman, g.oee));
      satir.append(gun, eleman("td", null, yuzde(g.oee)), durum);
      tablo.tBodies[0].append(satir);
    }
    const kap = eleman("div", "tablo-kap");
    kap.append(tablo);
    kutu.append(kap);
    return kutu;
  }

  function pareto(duruslar) {
    if (!duruslar.length) return eleman("p", "soluk", "Bu dönemde duruş yok.");
    const liste = eleman("ol", "pareto");
    const enBuyuk = duruslar[0].sure_dk;
    for (const d of duruslar.slice(0, 8)) {
      const satir = eleman("li");
      const ust = eleman("div", "pareto-ust");
      ust.append(
        eleman("span", null, durusAdi(d)),
        eleman("span", "soluk", `${SAYI.format(d.sure_dk)} dk · ${yuzde(d.pay)} · birikimli ${yuzde(d.kumulatif_pay)}`),
      );
      const cubuk = eleman("span", "pareto-cubuk");
      cubuk.style.setProperty("--oran", String(d.sure_dk / enBuyuk));
      satir.append(ust, cubuk);
      liste.append(satir);
    }
    return liste;
  }

  function hatTablosu(hatlar) {
    const tablo = eleman("table", "oee-tablo");
    const baslik = eleman("tr");
    for (const ad of ["Hat", "OEE", "Kull.", "Perf.", "Kalite", "Duruş"]) {
      const th = eleman("th", null, ad);
      th.scope = "col";
      baslik.append(th);
    }
    tablo.append(eleman("thead"), eleman("tbody"));
    tablo.tHead.append(baslik);
    for (const h of [...hatlar].sort((a, b) => (a.oee ?? 0) - (b.oee ?? 0))) {
      const satir = eleman("tr");
      const ad = eleman("th");
      ad.scope = "row";
      const dugme = eleman("button", "metin-dugme", h.hat);
      dugme.type = "button";
      dugme.title = `${h.hat} hattını seç`;
      dugme.addEventListener("click", () => {
        $("oee-filtre").elements.hat.value = h.hat;
        yukle();
      });
      ad.append(dugme);
      const oee = eleman("td");
      oee.append(eleman("span", `nokta ${seviye(h.oee)}`), document.createTextNode(yuzde(h.oee)));
      satir.append(
        ad,
        oee,
        eleman("td", null, yuzde(h.kullanilabilirlik)),
        eleman("td", null, yuzde(h.performans)),
        eleman("td", null, yuzde(h.kalite)),
        eleman("td", null, `${SAYI.format(h.durus_dk)} dk`),
      );
      tablo.tBodies[0].append(satir);
    }
    return tablo;
  }

  function vardiyalar(satirlar) {
    const kap = eleman("div", "vardiyalar");
    for (const v of satirlar) {
      const kart = eleman("div", `vardiya ${seviye(v.oee)}`);
      kart.append(
        eleman("span", "soluk", `${v.vardiya}. vardiya · ${VARDIYA_SAATLERI[v.vardiya]}`),
        eleman("strong", null, yuzde(v.oee)),
        seviyeEtiketi(eleman, v.oee),
        eleman("span", "soluk", `Perf. ${yuzde(v.performans)} · Kull. ${yuzde(v.kullanilabilirlik)}`),
      );
      kap.append(kart);
    }
    return kap;
  }

  function makineler(satirlar) {
    if (!satirlar.length) return eleman("p", "soluk", "Bu dönemde hattı durduran arıza yok.");
    const liste = eleman("ol", "makine-listesi");
    for (const m of satirlar) {
      const satir = eleman("li");
      satir.append(
        eleman("code", null, m.makine_kodu),
        eleman("span", null, ` ${m.makine_adi} (${m.hat})`),
        eleman("span", "soluk", ` · ${m.ariza_sayisi} arıza, ${SAYI.format(m.sure_dk)} dk`),
      );
      liste.append(satir);
    }
    return liste;
  }

  return {
    async goster() {
      await hatlariYukle();
      adrestenOku();
      await yukle();
    },
  };
}
