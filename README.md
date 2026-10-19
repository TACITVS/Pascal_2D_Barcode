# PASCAL-MDS

A compact 2D matrix barcode whose error correction is a Reed–Solomon code over
the prime field GF(257), written and encoded in Pascal's-triangle (Newton)
form. It is the practical implementation of the *PASCAL-MDS-257* research
handout, revised according to the referee report of 2026-10-18.

* **Reads where QR does not**: in real phone photos of a screen at 1–4 m,
  PASCAL-MDS read codes 1.5–2.3× narrower than QR needed (2–5× less area),
  and at distances where QR read nothing (table below).
* **Readable from photos**: rotation, perspective, blur, uneven light,
  mirrored prints, several codes per image.
* **Erasure-aware**: smudged or glared areas are detected from sampling
  confidence and erased, which doubles how many such bytes can be repaired.
* **No false reads by design**: every accepted decode satisfies an exact
  10⁻¹⁰ per-attempt false-accept bound (SPEC §6).
* **Encoder uses only additions mod 257** (Pascal's rule), with a proof that
  every payload fits into bytes (SPEC Theorem 1).

## Try it

Web app (make, save, and scan from a photo, or with the live camera where the
browser allows it): `web/index.html` together with `web/pascal_mds.js`. Any
static host works, for example GitHub Pages. No build step, no dependencies.

Python (3.11+; the photo reader needs `numpy` and `Pillow`):

```
pip install -e ".[reader]"     # or just run from the repository root
python -m pascal_mds encode "https://www.example.com/menu" -o menu.png
python -m pascal_mds decode photo.jpg
python -m pascal_mds info            # capacity table
```

```python
from pascal_mds import encode, decode_modules
from pascal_mds.render import to_image, to_svg
from pascal_mds.reader import read

sym = encode("WIFI:S:HomeNetwork;T:WPA;P:secret;;", level="Q")
to_image(sym, module_px=12).save("wifi.png")
print([d.decoded.text for d in read("wifi_photo.jpg")])
```

JavaScript: `PascalMDS.encode(text, level)`, `PascalMDS.readImageData(imageData)`,
`PascalMDS.toSVG(symbol)`; see `web/index.html` for camera and file handling.

## Two formats

* **Standard (v1)**: a fixed-alphabet byte code (GF(257) Reed–Solomon,
  4 error-correction levels), sizes 11×11 to 47×47, up to 174 bytes at
  level M. Specified in `SPEC.md`.
* **Dense (v2)**: modules read jointly from grey levels with a per-photo
  camera model (blur, contrast, tone curve, refitted as decoding
  proceeds), four LDPC stages at equal rates plus a Pascal GF(257) outer
  check, sizes 22×22 to 94×94, up to 590 bytes (level A). For data too long for
  Standard. Prototype in `research/v2/` (Python) and
  `web/pascal_mds_v2.js` (JS); see `research/README.md`.

### Real phone photos (`fieldtest/RESULTS.md`, rounds 3–4)

One phone (Galaxy S26, 1× camera), a 15.6" laptop screen showing
`fieldtest/sheet.html`, photos from about 1.1 to 3.8 m. Width of the
smallest code read, in camera pixels (smaller is better):

| Payload | QR | Standard | Dense | Least area vs QR |
|---|---|---|---|---|
| Link, 55 chars | 107 | 48 | **47** | 5.2× less |
| Contact card, ~100 chars | 132 | **60** | 89 | 4.8× less |
| Notes, 275 chars | not read (missed 162) | too long | **110** | > 2.1× less |

QR read nothing beyond ~1.2 m; Standard and Dense read 220 px links at
2.75 m, and Dense read the 275-character notes at 1.75 m. Widths come in
steps, so each figure bounds the true limit from above. Use Standard for
short data and Dense when the data does not fit Standard.

Simulated photos (`bench/benchmark_v2.py`, results in `bench/RESULTS_v2.md`)
are being re-run for the current Dense format; the field tests showed the
first simulator overstated how much later decoding stages gain from earlier
ones.

## How v1 compares (simulated phone photos, first benchmark)

`bench/benchmark.py` encodes the same payloads at level M as QR (segno) and as
PASCAL-MDS, prints both at the **same symbol width**, and simulates phone
photos: random rotation, perspective tilt, lighting gradient, blur, sensor
noise, JPEG, and clutter outside each code's required quiet zone. QR is
decoded by **zxing-cpp**, the engine used by many Android scanners; Data
Matrix (ISO 16022) is included for reference. 30 photos per point; raw data
in `bench/results_2026-10-18.json`.

| Payload | QR | PASCAL | Area with quiet zone | Smallest width read ≥ 90% | Read with 6% of area blotted |
|---|---|---|---|---|---|
| Short link, 24 B | 25×25 | 17×17 | −60% | QR 50 px · **40 px** | QR 33% · **83%** |
| Link, 53 B | 33×33 | 23×23 | −57% | QR 75 px · **50 px** | QR 40% · **90%** |
| Wi-Fi, 52 B | 33×33 | 25×25 | −50% | QR 75 px · **50 px** | QR 30% · **77%** |
| Contact card, 118 B | 45×45 | 35×35 | −46% | QR 110 px · **75 px** | QR 50% · **97%** |

Defocus (width 140 px): PASCAL-MDS kept 100% success up to a blur σ of
2.0 px for the 52–53-byte payloads (3.5 px for the short link) and 1.5 px for
the contact card; QR
dropped to ≤ 50% at σ = 2.0 px (53-byte payloads) and to 3% at σ = 1.5 px
(contact card).

Where the gain comes from: (1) a 1-module frame (L finder + timing) instead of
three 7×7 finders, separators, format and timing patterns; (2) a 2-module
quiet zone instead of 4; (3) a compact text mode (6 bits per character, with
`https://`, `www.`, `.com` and case shifts) that QR does not have; (4) one MDS
block per symbol and confidence-based erasures in the reader.

## What is and is not established

* **Established**: the code and its guarantees (proofs in SPEC.md and tests);
  bit-identical Python and JavaScript implementations; the simulation results
  above; four rounds of real phone photos of a laptop screen
  (`fieldtest/RESULTS.md`), which also exposed and fixed reader and format
  weaknesses the simulator had hidden.
* **Not established**: other phones, printed paper, low light, motion. All
  real-photo results so far come from one phone and one screen; Dense's
  current format has one round of real photos.
* **Data Matrix is nearly as compact.** On these payloads it needed 7–13% more
  area than PASCAL-MDS, at its single fixed (fairly strong) error-correction
  level. PASCAL-MDS's frame is the same idea as Data Matrix's. In this simulation
  zxing-cpp read Data Matrix less reliably than either code, which says more
  about that reader than about the format.
* **Not novel coding theory.** The MDS code is Reed–Solomon. The Pascal basis
  gives an additions-only encoder and the clean byte-packing proof.
* **Adoption**: phone cameras read QR natively; PASCAL-MDS needs this web app
  or an app built from this code. For printed material people scan with their
  stock camera app, QR is still the practical choice.

## Repository layout

```
pascal_mds/          Python package (codec: stdlib only; reader: numpy, Pillow)
  gf257.py           GF(257) arithmetic, Pascal encoder, Gao decoder
  layout.py          sizes, frame, placement, levels, false-accept rule
  codec.py           message format, text mode, encode/decode of module grids
  reader.py          photo reader
  render.py          SVG / PNG
tests/               pytest suite + vectors.json (known-answer vectors)
web/                 pascal_mds.js (JS port), index.html (app), node tests
bench/               benchmark.py and recorded results
SPEC.md              symbol specification, Theorem 1, handout/referee audit
.github/workflows/   CI (Python + Node tests) and the scheduled publish switch
```

Tests: `python -m pytest -q` and
`node web/test_node.js`. `tests/test_js_port.py` runs the Node test and the
cross-language photo check when Node is installed.

## Scheduled publication

This repository is private and is set to become public automatically on the
date in `.github/publish-on` (see `.github/PUBLISH_ON_DATE.md`). To postpone or
cancel, edit or delete that file.
