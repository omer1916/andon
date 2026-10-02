"""OEE panelinin saf fonksiyonları (app/static/oee.js), Node ile.

Dönem seçimi tarih aralığına çevrilirken ay ve yıl sınırları, artık yıl ve "son N gün"ün iki
ucu da dahil olması doğru mu; yüzde biçimi ve andon rengi eşikleri doğru mu. Node kurulu değilse
testler atlanır.
"""

import json
import shutil
import subprocess
from datetime import date, timedelta
from pathlib import Path

import pytest

OEE_JS = Path(__file__).resolve().parent.parent / "app" / "static" / "oee.js"


def _node(cagrilar: list[tuple[str, list]]) -> list:
    """oee.js'teki fonksiyonları verilen argümanlarla çağırır. "@2026-03-31" biçimindeki argüman
    o günün öğlesine ait bir Date nesnesine çevrilir."""
    betik = (
        f"import * as m from {json.dumps(OEE_JS.as_uri())};"
        "let girdi = '';"
        "process.stdin.setEncoding('utf8');"
        "process.stdin.on('data', (p) => (girdi += p));"
        "process.stdin.on('end', () => {"
        "  const arg = (a) => (typeof a === 'string' && a.startsWith('@')"
        "    ? new Date(`${a.slice(1)}T12:00`) : a);"
        "  const sonuc = JSON.parse(girdi).map(([ad, args]) => m[ad](...args.map(arg)));"
        "  process.stdout.write(JSON.stringify(sonuc));"
        "});"
    )
    sonuc = subprocess.run(
        ["node", "--input-type=module", "-e", betik],
        input=json.dumps(cagrilar),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=True,
    )
    return json.loads(sonuc.stdout)


@pytest.fixture(scope="module", autouse=True)
def node_gerekli():
    if shutil.which("node") is None:
        pytest.skip("Node.js kurulu değil")


SON_N_GUN = [
    ("7", date(2026, 10, 1)),
    ("30", date(2026, 10, 1)),
    ("30", date(2026, 3, 1)),  # şubat 28 gün
    ("30", date(2028, 3, 1)),  # artık yıl
    ("30", date(2026, 1, 10)),  # yıl sınırı
    ("180", date(2026, 9, 30)),
]


@pytest.mark.parametrize(("donem", "bugun"), SON_N_GUN, ids=lambda x: str(x))
def test_son_n_gun_iki_ucu_da_dahil(donem, bugun):
    (aralik,) = _node([("donemAraligi", [donem, f"@{bugun}"])])
    baslangic = bugun - timedelta(days=int(donem) - 1)
    assert aralik == [baslangic.isoformat(), bugun.isoformat()]


TAKVIM_AYLARI = [
    ("gecen-ay", "2026-03-31", ["2026-02-01", "2026-02-28"]),
    ("gecen-ay", "2028-03-10", ["2028-02-01", "2028-02-29"]),
    ("gecen-ay", "2026-01-15", ["2025-12-01", "2025-12-31"]),
    ("gecen-ay", "2026-10-01", ["2026-09-01", "2026-09-30"]),
    ("bu-ay", "2026-10-01", ["2026-10-01", "2026-10-01"]),
    ("bu-ay", "2026-09-30", ["2026-09-01", "2026-09-30"]),
]


@pytest.mark.parametrize(("donem", "bugun", "beklenen"), TAKVIM_AYLARI)
def test_takvim_ayi_sinirlari(donem, bugun, beklenen):
    assert _node([("donemAraligi", [donem, f"@{bugun}"])]) == [beklenen]


@pytest.mark.parametrize(
    ("oran", "renk"),
    [(1.0, "yesil"), (0.85, "yesil"), (0.8499, "sari"), (0.65, "sari"), (0.6499, "kirmizi"),
     (0.0, "kirmizi"), (None, "yok")],
)  # fmt: skip
def test_andon_rengi_esikleri(oran, renk):
    assert _node([("seviye", [oran])]) == [renk]


def test_yuzde_ve_durus_adlari_turkce():
    assert _node(
        [
            ("yuzde", [0.6384]),
            ("yuzde", [1]),
            ("yuzde", [None]),
            ("durusAdi", [{"neden": "ariza", "ariza_tipi": "sensor"}]),
            ("durusAdi", [{"neden": "ariza", "ariza_tipi": "pnomatik"}]),
            ("durusAdi", [{"neden": "urun_degisimi", "ariza_tipi": None}]),
            ("durusAdi", [{"neden": "malzeme_bekleme", "ariza_tipi": None}]),
        ]
    ) == [
        "%63,8",
        "%100,0",
        "–",
        "Arıza: sensör",
        "Arıza: pnömatik",
        "Ürün değişimi",
        "Malzeme bekleme",
    ]
