# Smallest readable width: QR vs PASCAL-MDS v1 vs v2

`bench/benchmark_v2.py`, 2026-10-18. Simulated phone photos (random
rotation, perspective tilt, lighting gradient, lens blur, sensor noise,
JPEG 75, clutter outside each code's quiet zone). Widths tried in
increasing order with 16 photos each; the smallest readable width is the
first of two consecutive widths that decode ≥ 90%. QR level M read by
zxing-cpp; v1 level M and v2 levels A/B/C read by this project's readers.
Raw data: `results_v2_widths_2026-10-18.jsonl`.

Smallest readable printed width, camera pixels (QR / v1 / best v2, which
was level A everywhere), and QR ÷ v2:

| Payload | Blur 0.7 px | Blur 1.2 px | Blur 2.0 px |
|---|---|---|---|
| Link, 53 B | 90 / 36 / **30** (3.0×) | 110 / 52 / **44** (2.5×) | 165 / 90 / **62** (2.7×) |
| Contact, 118 B | 110 / 62 / **44** (2.5×) | 135 / 90 / **62** (2.2×) | 200 / 135 / **90** (2.2×) |
| Notes, 300 B | 165 / – / **75** (2.2×) | 200 / – / **90** (2.2×) | 300 / – / **165** (1.8×) |
| Binary, 500 B | 165 / – / **110** (1.5×) | 245 / – / **135** (1.8×) | 450 / – / **245** (1.8×) |

"–": v1 holds at most 174 bytes. Printed area scales with the square:
v2 needs 2.3× to 9× less area than QR for the same photo quality.

All v2 levels by condition (width in px):

| Payload | Blur | A | B | C |
|---|---|---|---|---|
| Link | 0.7 / 1.2 / 2.0 | 30 / 44 / 62 | 36 / 52 / 75 | 44 / 62 / 90 |
| Contact | 0.7 / 1.2 / 2.0 | 44 / 62 / 90 | 44 / 62 / 110 | 62 / 90 / 135 |
| Notes | 0.7 / 1.2 / 2.0 | 75 / 90 / 165 | 75 / 110 / 165 | 75 / 110 / 200 |
| Binary | 0.7 / 1.2 / 2.0 | 110 / 135 / 245 | 110 / 165 / 245 | does not fit |

Level A, the densest, is never worse: the reader estimates each photo's
blur, so a denser layout pays off even on blurry photos. Levels B and C
only spend area.

## Caveats

* Simulation only. Real-photo evidence so far: `fieldtest/RESULTS.md`
  (v1, round 1). Round 2 with real distances and v2 is pending.
* The simulator and both PASCAL readers were developed together; the QR
  reader (zxing-cpp) was not tuned to it.
* 16 photos per width: a "90%" point has roughly ±8% uncertainty, so
  neighbouring widths can swap order between runs.
