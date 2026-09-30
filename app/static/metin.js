// LLM cevabını güvenli HTML'e çeviren saf fonksiyonlar. DOM kullanmaz; testler Node ile
// doğrudan çalıştırır (tests/test_arayuz_metin.py).

const KACIS = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

export function kacis(metin) {
  return metin.replace(/[&<>"']/g, (c) => KACIS[c]);
}

function satirIci(metin) {
  return kacis(metin)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
}

// Basit Markdown'ı (paragraf, madde, numaralı liste, kalın, kod) HTML'e çevirir. Metin önce
// kaçış karakterlerine çevrilir; modelin ürettiği HTML sayfada çalıştırılamaz. Çıktıda
// yalnızca p, ul, ol, li, strong ve code etiketleri bulunur, hiçbirinde öznitelik yoktur.
export function guvenliMarkdown(metin) {
  const bloklar = [];
  let liste = null;
  for (const satir of metin.split("\n")) {
    const madde = satir.match(/^\s*([-*•]|\d+[.)])\s+(.*)$/);
    if (madde) {
      const tur = /\d/.test(madde[1]) ? "ol" : "ul";
      if (!liste || liste.tur !== tur) {
        liste = { tur, maddeler: [] };
        bloklar.push(liste);
      }
      liste.maddeler.push(satirIci(madde[2]));
      continue;
    }
    liste = null;
    const baslik = satir.match(/^#{1,6}\s+(.*)$/);
    if (baslik) bloklar.push({ html: `<p><strong>${satirIci(baslik[1])}</strong></p>` });
    else if (satir.trim()) bloklar.push({ html: `<p>${satirIci(satir)}</p>` });
  }
  return bloklar
    .map((b) => b.html ?? `<${b.tur}>${b.maddeler.map((m) => `<li>${m}</li>`).join("")}</${b.tur}>`)
    .join("");
}
