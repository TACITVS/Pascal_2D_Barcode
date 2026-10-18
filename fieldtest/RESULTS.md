# Field-test results

## 2026-10-18, round 1: phone photos of the screen sheet

Four photos (4000 × 1848, HEIC) of `sheet.html` on a laptop screen in dark
mode, hand-held, one at an angle. Each photo was also shrunk to 1/2 … 1/12
to imitate a longer distance while keeping the phone's real optics, screen
texture and processing. QR decoded by zxing-cpp; PASCAL-MDS by
`pascal_mds.reader`. The photos are not in the repository.

Tags decoded (✓) per photo and scale, after the reader fixes below:

| Photo | Scale | QR | PASCAL-MDS |
|---|---|---|---|
| a1, a2 | 1 … 1/6 | a1 a2 | a1 a2 |
| | 1/8 … 1/12 | a1 | **a1 a2** |
| a3–a5 | 1 | a3 a4 | a3 a4 **a5** |
| | 1/2 | a3 | a3 a4 **a5** |
| | 1/3 | a3 | a3 a4 |
| | 1/4 | – | **a3 a4** |
| | 1/6, 1/8 | – | **a3** |
| b1, b2 | 1 … 1/6 | b1 b2 | b1 b2 |
| | 1/8 | b1 | b1 **b2** |
| | 1/10 | b1 | b1 |
| | 1/12 | – | **b1** |
| b3–b5 (angled) | 1 | b3 b5 | b3 b4 b5 |
| | 1/2 | b3 b4 | b3 b4 |
| | 1/3 | b3 | b3 **b4** |
| | 1/4, 1/6 | – | **b3 b4** |
| | 1/8 | – | **b3** |

Totals over all photo × scale cells: QR 31 decodes, PASCAL-MDS 47; QR never
read a code PASCAL-MDS missed.

### Reader defects found by these photos (fixed)

1. A candidate filter rejected a frame whose data modules did not touch it
   (a bare L fills ~9% of its box; the threshold was 12%).
2. Phone sharpening and screen texture misread 30 modules of b5: a 3 × 3
   equalizer learned per photo from the frame and quiet zone (second
   reading) cut that to 13 and the code decodes.
3. Fine screen texture broke the frame of large symbols into pieces: an
   image pyramid (full, ½, ¼) now runs detection.
4. The adaptive threshold window grew with the photo (230 px at 4000 px)
   and exceeded small symbols on a dark page: capped at 65 px.

The same fixes improved the simulated benchmark: the 53-byte link now
decodes at 40 px width at blur 0.7 (was 50) and 75 px at blur 1.5 (was 90).
