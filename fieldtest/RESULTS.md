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

## 2026-10-18, round 2: paged sheet, QR vs Standard vs Dense

Seven photos (Galaxy S26, HEIC, 1436–3602 px wide as saved) of the paged
`sheet.html` in the artifact viewer on a 15.6" laptop screen, dark mode.
Three pages; two or three photos per page at different distances. Round-2
tags and widths (CSS px): a1–a6 = 220, 150, 105, 75, 55, 40;
b1–b5 = 260, 180, 125, 90, 65; c1–c5 = 320, 230, 165, 120, 90.
QR by zxing-cpp, Standard by `pascal_mds.reader`, Dense (level A) by
`research/v2/reader2.py`; the JS reader gives the same Dense results.

Decoded tags, final reader:

| Photo (width) | Page | QR | Standard | Dense |
|---|---|---|---|---|
| 193500 (3087) | 1 | a1 a3 b4 c1 | a3 b5 | a4 b1 c1 |
| 193503 (1788) | 1 | a1 c1 | a3 | a4 b1 c1 |
| 193514 (3056) | 2 | a2 b1 b3 c3 | a2 b1 b3 | a1 a2 b3 c2 |
| 193519 (1436) | 2 | a2 b1 | a2 b1 b3 | a1 b3 |
| 193523 (3602) | 3 | a4 b2 c2 | a1 a4 b2 | a3 b2 |
| 193525 (2194) | 3 | a4 b2 c2 | a1 a4 b2 | a3 b2 |
| 193528 (1587) | 3 | b2 c2 | a1 b2 | a3 b2 |

Totals: QR 20, Standard 17, Dense 18 (Dense was 10 with the reader as it
stood before this round). Smallest width read: link — QR, Standard and
Dense all 75 px; contact — Standard 65, QR 90, Dense 125; notes — QR 165,
Dense 230. **Dense did not beat QR in this round.**

### What limited the photos

1. **The screen, not the camera.** At the smallest sizes every symbology
   had under 2 CSS px per module (QR 1.2–1.6, Dense 1.5–1.7; 125% scaling
   makes that 1.9–2.6 screen pixels). Pixel snapping makes such modules
   2 or 3 screen pixels wide at random, and screenshots of the same page
   fail at exactly these sizes, with no camera involved. Soft decoding is
   meant to win when the *camera* resolves too few pixels per module; these
   photos were taken close enough that it never did.
2. **Overexposure.** On the dark page the phone exposed for the dark
   screen, the white codes clipped, and light bled into dark modules:
   isolated dark modules shrink to dots. Hard thresholding of large
   modules (QR, Standard) tolerates this; Dense's model did not.
3. A hover tooltip from the sheet covered c5 on page 1.

### Dense reader changes (Python and JS)

Measured against the true bits of every located Dense symbol, the soft
decisions held near-perfect information on large codes but the decoder
still failed on many mid-size ones. Three causes, three fixes:

1. **Model mismatch at module edges.** Bloom and sharpening make the 7 × 7
   window's edge samples disagree with the linear footprint model by 60–85
   grey levels (of 200), the module centres by about 30. One noise level
   for all samples drowned the clean centres. Noise is now estimated per
   window position from the frame's residual. Without it the photos lose
   6 Dense decodes.
2. **Tone curve.** Phones store tone-mapped pixels and overexposed screens
   bloom. If the linear model fails, the reader retries with the tone
   curve (y / light) ** gamma, gamma in 1 … 5, that fits the frame best.
   Linear first, because on simulated photos the frame fit prefers
   gamma 1.5 while gamma 1 decodes better.
3. **Overconfident LLRs.** On the hard photos, scaling the LLRs by 0.2–0.5
   turned stages with near-zero or negative information into 0.5–0.75 bit
   per module. A stage that fails
   to decode is retried at ½ and ¼ scale; success is verified by the
   parity checks and the outer code. (A blind EM fit of the scale worked
   on the photos but collapsed on blurry simulated ones, so it was
   dropped.)

Simulated benchmark re-checked for V2-A at each recorded smallest width
and one step below (16 photos each, same seeds): 21 of 24 points within
one photo of the recorded rate; one step below the smallest width, notes
fell by 2 and 3 photos (blur 0.7, 2.0) and binary at blur 2.0 rose by 5.
Every recorded smallest width holds except contact at blur 2.0, which fell
from 15/16 to 14/16 at 90 px, under the 90% bar, so it moves up one step.

### Open question for round 3: the stage rates

Level A gives stages 2 and 3 high rates (0.82, 0.89) because, on the
simulated blur channel, already decoded neighbours make the late stages
much cleaner. On these photos the late stages were no cleaner than stage
0 (information per stage with the fitted scale, e.g. contact b4 at 2.9 px
per module: 0.83 / 0.92 / 0.86 / 0.80; notes c2 at 4.0 px: 0.96 / 0.94 /
0.92 / 0.91), so stage 3 is the one that fails. Whether that holds once
the camera, not the screen, limits the photo decides whether the stage
rates should be rebalanced (a format change). Round 3 (`sheet.html` now)
is that test: no code under 3 CSS px per module, white code pages, photos
from 1 to 4 m.

## 2026-10-18, round 3: distance test

Eleven photos (Galaxy S26, 1× camera, HEIC) of the round-3 sheet, the
same 15.6" screen, white code pages, cropped to the screen. Distances from
the screen's width in the photo with the 23 mm-equivalent lens (827–832,
501–519, 322–341 and 225–236 px wide): about 1.1, 1.7, 2.7 and 3.8 m;
labelled by the photographer as the 1.5, 2, 3 and 4 m series. Tags name the
width in CSS px; 1 CSS px is 1.25 screen pixels.

Decoded tags, reader of this round (Dense still in the old level-A format):

| Distance | Photo | QR | Standard | Dense (old A) |
|---|---|---|---|---|
| ~1.1 m | 205256 | b260 | a120 b260 | – |
| | 205301 | a220 | a220 a160 b190 | b190 |
| ~1.7 m | 205320 | – | – | a220 |
| | 205328 | – | b260 | – |
| | 205335 | – | a220 a160 b190 | – |
| ~2.7 m | 205347 | – | – | – |
| | 205358 | – | b260 | – |
| | 205408 | – | a220 | – |
| ~3.8 m | 3 photos | – | – | – |

**Standard beat QR at every distance**: QR read only the two largest codes
at 1.1 m and nothing beyond; Standard read 160–260 px codes at 1.7 m and
220–260 px codes at 2.7 m.

### Smallest code read, in camera pixels

Each photo's scale (camera px per CSS px) from its located Dense symbols;
rounds 2 and 3 together. Width of the code itself, without quiet zone:

| | Link (55 chars) | Contact (97–104) | Notes (275–300) |
|---|---|---|---|
| QR | 115 | 149 | 252 |
| Standard | **50** | **60** | does not fit |
| Dense, old level A | 80 | 127 | 235 |
| Dense, flat rate 0.6 (replayed, below) | 58 | 69 | ~124 |

### Why old Dense lost, and the format change

Measured against the true bits, the Dense soft decisions at 1.1 m held
0.65–0.76 bit per module in stage 0, enough for its rate 0.43, but the late
stages (rates 0.82, 0.89) failed. Two changes:

1. **Reader: refit after every stage.** The model (blur, contrast, tone
   curve, per-position noise) was fitted on the frame alone, a thin band
   with few patterns. Refitting on the frame plus every decoded module
   raised the late stages by up to 0.2 bit per module (e.g. stage 3 of b190
   0.70 → 0.91). Added to the Python and JS readers (identical results on
   all 18 photos of rounds 2–3): round 2 Dense decodes 18 → 21, round 3
   0 → 2.
2. **Format: flat stage rates.** Even after the refit the late stages were
   no cleaner than stage 0 on real photos, unlike the simulated channel the
   old rates came from. To choose new rates without new photos, the
   reader's LLRs for all 75 located Dense sightings (rounds 2–3, with the
   true bits standing in for decoded stages) were re-signed against the
   all-zero codeword of IRA codes of each candidate rate and decoded
   (valid for a symmetric channel; with the ½ and ¼ LLR-scale retries):

   | Stage rates | Sightings decoded (of 75) | Side for the same data |
   |---|---|---|
   | old A (0.43, 0.41, 0.82, 0.89) | 22 | 1.00 |
   | flat 0.45 | 44 | 1.19 |
   | flat 0.5 | 42 | 1.13 |
   | flat 0.55 | 40 | 1.08 |
   | **flat 0.6** | **40** | **1.03** |
   | flat 0.65 | 33 | 0.99 |
   | flat 0.7 | 29 | 0.96 |

   Flat 0.6 reads nearly twice as many sightings as the old level A at
   about the same size. By the smallest effective width read (pitch ×
   modules × side factor) it is within 8% of the best design on every
   payload (link 58 vs 54 px for flat 0.7, contact the best at 69, notes 119
   vs 110), while flat 0.65 and 0.7 lose a third on the contact card and the
   lower rates grow the symbol more than they gain. Levels are now A = 0.6, B = 0.5, C = 0.4 in every stage. The link
   and contact symbols keep their sizes (30 and 38 modules); the notes grow
   from 58 to 62.

Caveat: the Dense row "flat 0.6" is replayed from measured LLRs, not read
from photos of new-format codes. Round 4 (the sheet as it is now) checks it.

### Where this leaves the comparison

On real photos of a screen, both PASCAL-MDS formats read codes about half
as wide as QR needs (a quarter of the area): Standard for short data, where
its larger modules and hard decisions do best; Dense (flat 0.6) for data
too long for Standard, about 2× narrower than QR on the 300-character
notes. For short data Dense is still about 15% wider than Standard.

## 2026-10-18, round 4: the flat-rate Dense format

Thirteen photos, same phone, screen and procedure as round 3, of the sheet
with Dense codes in the new format (level A = rate 0.6 in every stage).
Full screen; the sheet packed into three pages (9, 19 and 2 codes; page
contents reproduced in a browser to know which codes each photo showed).
Distances from the screen's width in the photo (706–733, 491–511, 315–321,
233–239 px): about 1.2, 1.75, 2.75 and 3.7 m.

| Distance | Page | QR | Standard | Dense |
|---|---|---|---|---|
| ~1.2 m | 1 | b260 | a120 b260 | a220 b260 c260 c320 |
| | 2 | a220 | a220 a160 b190 | a160 b190 |
| | 3 | – | a100 | (not on page) |
| ~1.75 m | 1 | – | b260 | a220 b260 c320 |
| | 2 | – | a220 a160 | – |
| | 3 | – | – | |
| ~2.75 m | 4 photos | – | a220 | a220 |
| ~3.7 m | 3 photos | – | – | – |

The 275-character notes: **QR missed even its 320 px code at 1.2 m; Dense
read 260 px at 1.2 m and 320 px at 1.75 m.** QR read nothing beyond 1.2 m.

Smallest code read, in camera pixels (scale from each photo's Dense
symbols; widths come in steps, so each figure bounds the true limit from
above):

| | Link (55 chars) | Contact (97–104) | Notes (275) |
|---|---|---|---|
| QR | 107 | 132 | none (missed at 162) |
| Standard | 48 | 89 | does not fit |
| **Dense, flat 0.6** | **47** | **89** | **110** |
| Dense, replay prediction (round 3) | 58 | 69 | ~124 |

Dense read down to 1.6–1.8 camera px per module with 15–18% of module
centres wrong on their own (c320 at 1.77 px, a220 at 1.57 px): the soft,
model-based detection doing what it was built for. With round 3, Standard's
best contact read was 60 px (at 2.7 m), so for short data the two formats
are now about even; for long data only Dense reads, at less than half the
width QR needs (QR's notes: 252 px in round 2, missed at 162 px here).

**Summary of rounds 3–4 (one phone, one laptop screen, 1–4 m):** PASCAL-MDS
reads codes 2.2–2.3× narrower than QR for links, ~1.5× for the contact
card (QR's limit lies between two steps) and 1.5–2.3× for 275-character
notes (QR missed 162 px here and first read 252 px in round 2), i.e. 2–5×
less area, and was read at distances where QR read nothing.
