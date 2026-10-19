# Smallest readable width: QR vs PASCAL-MDS v1 vs v2

`bench/benchmark_v2.py`, re-run 2026-10-19 for the current v2 format
(flat stage rates: A 0.6, B 0.5, C 0.4) and reader (per-position noise,
tone-curve fallback, LLR-scale retries, refit after every stage).
Simulated phone photos (random rotation, perspective tilt, lighting
gradient, lens blur, sensor noise, JPEG 75, clutter outside each code's
quiet zone). Widths tried in increasing order with 16 photos each; the
smallest readable width is the first of two consecutive widths that decode
≥ 90%. QR level M read by zxing-cpp; v1 level M and v2 levels A/B/C read by
this project's readers. Raw data: `results_v2_widths_2026-10-19.jsonl`
(QR and v1 rows carried over from the 2026-10-18 run; neither changed).

Smallest readable printed width, camera pixels (QR / v1 / best v2), and
QR ÷ v2:

| Payload | Blur 0.7 px | Blur 1.2 px | Blur 2.0 px |
|---|---|---|---|
| Link, 53 B | 90 / 36 / **36** (2.5×) | 110 / 52 / **44** (2.5×) | 165 / 90 / **75** (2.2×) |
| Contact, 118 B | 110 / 62 / **52** (2.1×) | 135 / 90 / **75** (1.8×) | 200 / 135 / **110** (1.8×) |
| Notes, 300 B | 165 / – / **75** (2.2×) | 200 / – / **110** (1.8×) | 300 / – / **165** (1.8×) |
| Binary, 500 B | 165 / – / **110** (1.5×) | 245 / – / **165** (1.5×) | 450 / – / **245** (1.8×) |

"–": v1 holds at most 174 bytes. Printed area scales with the square:
v2 needs 2.2× to 6.3× less area than QR for the same photo quality.

All v2 levels by condition (width in px; modules per side in brackets):

| Payload | Blur | A | B | C |
|---|---|---|---|---|
| Link | 0.7 / 1.2 / 2.0 | 36 / 44 / 75 (26) | 44 / 52 / 75 (30) | 44 / 62 / 90 (34) |
| Contact | 0.7 / 1.2 / 2.0 | 52 / 75 / 135 (42) | 52 / 75 / 110 (42) | 62 / 90 / 135 (50) |
| Notes | 0.7 / 1.2 / 2.0 | 75 / 110 / 165 (62) | 75 / 110 / 165 (66) | 90 / 135 / 200 (74) |
| Binary | 0.7 / 1.2 / 2.0 | 110 / 165 / 245 (90) | does not fit | does not fit |

## Against the first v2 format (2026-10-18)

The first format gave the four decoding stages rates 0.43, 0.41, 0.82,
0.89 (level A), designed on this simulator, where decoded neighbours make
the late stages much cleaner. In simulation it was better: link 30 / 44 /
62 px, contact 44 / 62 / 90, notes 75 / 90 / 165, binary 110 / 135 / 245
(QR ÷ v2 1.5–3.0×, 2.3–9× in area). On real phone photos the late stages
were no cleaner than the first, and that format read 22 of 75 real symbol
sightings against 40 for flat 0.6 (`fieldtest/RESULTS.md`, round 3); in
round 4 the flat format read codes 1.5–2.3× narrower than QR on real
photos. The format follows the real photos; the gap between the two shows
the simulator overstates the inter-stage gain.

## Caveats

* The simulator and both PASCAL readers were developed together; the QR
  reader (zxing-cpp) was not tuned to it. Real-photo results:
  `fieldtest/RESULTS.md` (rounds 1–4, one phone, one laptop screen).
* 16 photos per width: a "90%" point has roughly ±8% uncertainty, so
  neighbouring widths can swap order between runs.
