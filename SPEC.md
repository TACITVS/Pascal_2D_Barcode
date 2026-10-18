# PASCAL-MDS symbol specification, revision 1

Status: implemented and tested (Python reference `pascal_mds/`, JavaScript port
`web/pascal_mds.js`, bit-identical on the known-answer vectors in
`tests/vectors.json`). Not an ISO standard; not field-tested with real phone
cameras (see README, "What is and is not established").

This revision turns the research handout *PASCAL-MDS-257* (October 2026) into a
complete symbol format, applying the referee report PM257-REF-2026-10-18-01.
Section 9 lists every handout claim and what became of it.

## 1. Notation

* `F = GF(257)`, the integers mod the Fermat prime 257 = 2^8 + 1.
* `C(x, k)` is the binomial coefficient; Pascal's rule
  `C(x, k) = C(x-1, k-1) + C(x-1, k)`.
* A symbol is an `n × n` grid of modules, 1 = dark. Row `r` counts from the
  top, column `c` from the left, both from 0.

## 2. Geometry

* **Sizes**: `n ∈ {11, 13, …, 47}` (odd), 19 sizes.
* **Frame** (one module wide, `4n − 4` modules):
  * column 0 and row `n−1` are dark: the solid **L finder**;
  * row 0: dark iff `c` is even; column `n−1`: dark iff `r` is even (the
    **timing tracks**). Because `n` is odd, all four corners are dark, so the
    symbol's outline is a complete quadrilateral in a photograph.
* **Quiet zone**: at least 2 light modules on every side (QR requires 4).
* **Data region**: rows and columns `1 … n−2`, an `m × m` square with `m = n − 2`
  odd, so `m² = 8N + 1`: `N = (m² − 1)/8` codeword bytes plus one
  **remainder module**, which is light.
* **Placement**: a two-column snake. Starting at the right edge of the data
  region, take column pairs `(j, j−1)`, `j = m−1, m−3, …` (the last "pair" is
  the single column 0); the first pair is walked upward from the bottom row,
  the next downward, alternating; within a row the right column comes first.
  Data bit `k` occupies the `k`-th module of this walk. Codeword byte `i`
  occupies bits `8i … 8i+7`, most significant bit first. Away from the turns,
  each byte is a compact 2 × 4 brick.
* **Symmetry**: reflecting a symbol about its bottom-left/top-right diagonal,
  `(r, c) ↦ (n−1−c, n−1−r)`, maps the frame onto itself. A reader therefore
  tries both readings; this also reads mirrored prints.

## 3. Error-correction code

For a size `n` and level `λ ∈ {L, M, Q, H}`:

* `N` as above; `t = max(1, ⌈f_λ · N⌉)` with `f = 0.07, 0.15, 0.25, 0.30` for
  L, M, Q, H (the same nominal recovery fractions as QR);
* **guard** `g` = the least `g ≥ 0` with `V(N, t) · 10^10 ≤ 257^(2t+g)`, where
  `V(M, t) = Σ_{i≤t} C(M, i) · 256^i` (exact integer arithmetic);
* `r = 2t + g` parity bytes, `K = N − r` systematic bytes.

The code is the set of words `(P(0), P(1), …, P(N−1))` for polynomials
`P` over `F` of degree `< K`, i.e. a Reed–Solomon code with evaluation points
`0 … N−1`. It is MDS (`d = r + 1`) because any `K` evaluations of a degree
`< K` polynomial determine it. Writing `P(x) = Σ u_k C(x, k)` (the Pascal or
Newton basis) changes the basis, not the code.

**Systematic encoding (additions only).** Given the message `m_0 … m_{K−1}`,
form the backward difference diagonal `b_k = ∇^k P(K−1)` from the difference
triangle (subtractions mod 257), then repeat `r` times:
`for k = K−2 down to 0: b_k ← b_k + b_{k+1}`; emit `b_0`. This uses
`∇^k P(x+1) = ∇^k P(x) + ∇^{k+1} P(x+1)` and `∇^{K−1} P` constant. The parity
bytes are `P(K) … P(N−1)`.

### Theorem 1 (byte packing always succeeds)

Codeword symbols live in `{0, …, 256}`, but a module brick stores a byte.
Let `m_{K−1}` (the **pad**) be free and all other message symbols fixed bytes,
and let `r ≤ 255`. Then some pad value `s ∈ {0, …, r}` makes every parity symbol
a byte (`≠ 256`).

*Proof.* Changing the pad by `s` adds `s · ℓ(x)` to `P(x)`, where `ℓ` is the
Lagrange basis polynomial of node `K−1` on nodes `0 … K−1`:
`ℓ(x) = Π_{i<K−1} (x − i)/(K − 1 − i) = C(x, K−1)`.
For `K ≤ x ≤ 256`, `C(x, K−1) = x!/((K−1)!(x−K+1)!)` has no factor 257, so
`ℓ(x) ≢ 0 (mod 257)`. Hence for each parity position `x` the map
`s ↦ P_0(x) + s·ℓ(x)` is injective on `F` and equals 256 for exactly one `s`.
The `r` parity positions exclude at most `r` values, so one of the `r + 1`
values `0 … r` remains, and `r ≤ 255` keeps it a byte. ∎

All versions have `N ≤ 253`, so `r ≤ 255` holds. The encoder takes the
**smallest** valid `s`; it finds it by adding `C(x, K−1)` to each parity symbol
per step (additions only; `C(x, K−1)` is itself `pascal_extend` of the unit
vector). This replaces the handout's seed search, whose success was only
probabilistic (referee F04). Cost: one byte per symbol.

## 4. Message format

Systematic bytes `m_0 … m_{K−1}`:

| bytes | content |
|---|---|
| header (1 or 2) | bits 7–6 mode (0 = raw bytes, 1 = compact text, 2–3 reserved); bit 5 = long; if long, length = 13 bits (bits 4–0 of byte 0, then byte 1), else length = bits 4–0 |
| `length` | payload (mode-packed) |
| zeros | filler; a reader rejects a nonzero filler byte |
| `m_{K−1}` | pad (Theorem 1) |

Capacity = largest `L` with `L + header(L) + 1 ≤ K`.

**Compact text mode** (6 bits per code, MSB first):

| codes | meaning |
|---|---|
| 0–25 | letters a–z (case: see CAPS/SHIFT) |
| 26–35 | digits 0–9 |
| 36–57 | `space . / : - _ ? = & % # @ + ~ ! * , ; ' ( )` and newline (in that order) |
| 58, 59, 60 | `https://`, `www.`, `.com` |
| 61 CAPS | toggle caps lock |
| 62 SHIFT | flip the case of the next letter |
| 63 ESC | followed by 8 bits: one raw byte |

The bit string is padded to a whole byte with 1s; a trailing incomplete ESC
ends parsing. Length counts packed bytes. The encoder uses CAPS for runs of two
or more letters of the other case and SHIFT for single letters, and it chooses
text mode only when it is strictly shorter than raw bytes.

## 5. Scrambling and level identification

Before placement, codeword byte `i` is XORed with `w_λ(i)`: a xorshift32
sequence (`s ← s ⊕ (s≪13); s ← s ⊕ (s≫17); s ← s ⊕ (s≪5)`, 32-bit) seeded
with `0x2545F491 · (index(λ) + 1) mod 2^32`, output `s ≫ 24`, one step per
byte. This whitens repetitive input, and it carries the level: unscrambling
with the wrong level's sequence gives a word far from the code, so no format
modules are needed. A payload equal to the scrambler output still renders
unevenly (referee F05); no balance guarantee is claimed.

## 6. Decoding and false-accept control

A reader samples the grid and tries both readings (§2), each of the four
levels, and first no erasures, then growing sets of erased bytes, ranked by
lowest sampling confidence. Each attempt runs Gao's algorithm on the kept
positions and accepts a corrected word only if

1. `2·errors + erasures ≤ r − g`, and
2. `V(N − e, errors) · 10^10 ≤ 257^(r − e)` (exactly), and
3. every corrected symbol is `≤ 255`, the header is valid and the filler is zero.

Condition 2 bounds by `10^−10` the chance that one attempt accepts a uniformly
random word: such a word is accepted only if its kept part lies within
`errors` of a codeword of the punctured `[N − e, K]` MDS code, which happens
with probability at most `V(N−e, errors)/257^(r−e)`. A reader makes at most
56 attempts per candidate (2 readings × 4 levels × 7 erasure rounds).
Without condition 2, erasing all `r` parity positions makes any word decode;
an early version of this reader did exactly that (see the repository history).
The erasure budget actually usable is the largest `e` meeting condition 2
with no errors ("e" in the table below), about `r − g − 4`.

## 7. Capacity table

`K` systematic bytes, `t` correctable unknown byte errors, `e` correctable
erasures (no errors), **cap** = payload bytes (after mode packing).

| Size | N | L: K / t / e / cap | M: K / t / e / cap | Q: K / t / e / cap | H: K / t / e / cap |
|---:|---:|---|---|---|---|
| 11×11 | 10 | 4 / 1 / 1 / **2** | 3 / 2 / 2 / **1** | 1 / 3 / 4 / **0** | 1 / 3 / 4 / **0** |
| 13×13 | 15 | 8 / 2 / 2 / **6** | 6 / 3 / 4 / **4** | 5 / 4 / 5 / **3** | 4 / 5 / 6 / **2** |
| 15×15 | 21 | 13 / 2 / 3 / **11** | 11 / 4 / 5 / **9** | 8 / 6 / 8 / **6** | 7 / 7 / 9 / **5** |
| 17×17 | 28 | 20 / 2 / 3 / **18** | 16 / 5 / 7 / **14** | 14 / 7 / 9 / **12** | 10 / 9 / 13 / **8** |
| 19×19 | 36 | 27 / 3 / 4 / **25** | 23 / 6 / 8 / **21** | 18 / 9 / 13 / **16** | 14 / 11 / 17 / **12** |
| 21×21 | 45 | 34 / 4 / 6 / **31** | 30 / 7 / 10 / **28** | 21 / 12 / 19 / **19** | 17 / 14 / 23 / **15** |
| 23×23 | 55 | 44 / 4 / 6 / **41** | 37 / 9 / 13 / **34** | 27 / 14 / 23 / **25** | 21 / 17 / 29 / **19** |
| 25×25 | 66 | 53 / 5 / 8 / **50** | 46 / 10 / 15 / **43** | 32 / 17 / 29 / **30** | 26 / 20 / 35 / **24** |
| 27×27 | 78 | 64 / 6 / 9 / **61** | 54 / 12 / 19 / **51** | 38 / 20 / 35 / **35** | 30 / 24 / 43 / **28** |
| 29×29 | 91 | 75 / 7 / 11 / **72** | 63 / 14 / 23 / **60** | 45 / 23 / 41 / **42** | 35 / 28 / 51 / **32** |
| 31×31 | 105 | 88 / 8 / 12 / **85** | 73 / 16 / 27 / **70** | 51 / 27 / 49 / **48** | 41 / 32 / 59 / **38** |
| 33×33 | 120 | 101 / 9 / 14 / **98** | 84 / 18 / 31 / **81** | 60 / 30 / 55 / **57** | 48 / 36 / 67 / **45** |
| 35×35 | 136 | 115 / 10 / 16 / **112** | 94 / 21 / 37 / **91** | 68 / 34 / 63 / **65** | 54 / 41 / 77 / **51** |
| 37×37 | 153 | 131 / 11 / 17 / **128** | 107 / 23 / 41 / **104** | 75 / 39 / 73 / **72** | 61 / 46 / 87 / **58** |
| 39×39 | 171 | 147 / 12 / 19 / **144** | 119 / 26 / 47 / **116** | 85 / 43 / 81 / **82** | 67 / 52 / 99 / **64** |
| 41×41 | 190 | 162 / 14 / 23 / **159** | 132 / 29 / 53 / **129** | 94 / 48 / 91 / **91** | 76 / 57 / 109 / **73** |
| 43×43 | 210 | 180 / 15 / 25 / **177** | 146 / 32 / 59 / **143** | 104 / 53 / 101 / **101** | 84 / 63 / 121 / **81** |
| 45×45 | 231 | 197 / 17 / 29 / **194** | 161 / 35 / 65 / **158** | 115 / 58 / 111 / **112** | 91 / 70 / 135 / **88** |
| 47×47 | 253 | 217 / 18 / 31 / **214** | 177 / 38 / 71 / **174** | 125 / 64 / 123 / **122** | 101 / 76 / 147 / **98** |

QR Code byte-mode capacity at level M for comparison: 21×21 → 14, 25×25 → 26,
29×29 → 42, 33×33 → 62, 37×37 → 84, 41×41 → 106, 45×45 → 122.

## 8. Reading photographs (informative)

Both implementations do the following:

1. adaptive (box-mean) binarisation, Otsu as fallback;
2. 8-connected components (run-length union–find), convex hull, the
   farthest-point quadrilateral;
3. orientation: for each corner as the L corner, and the fourth corner from
   the hull or completed as a parallelogram, score dark samples just inside the
   two L sides against the light quiet zone on all four sides;
4. size-free refinement: rays across each side from the quiet zone inward; the
   first dark sample gives an edge point; a line through the outermost points
   (trimming rays that started on light timing gaps) is exact in the
   homography's frame, and the four lines intersect at the corners;
5. size: the `n` whose timing tracks correlate best with the alternating
   pattern; then per-module edge refinement;
6. sampling: 3 × 3 averaged grey value at each module centre; threshold from
   quadratic surfaces fitted to the frame's dark modules and the light
   gaps/quiet zone (handles lighting gradients); confidence =
   |value − threshold| / half-contrast;
7. decoding as in §6.

## 9. Handout claims, referee findings, and this revision

| Handout claim | Referee | Revision 1 |
|---|---|---|
| Pascal matrix over GF(257) is MDS | correct (F01) | kept; proof in §3 |
| A new coding mechanism | it is Reed–Solomon in the Newton basis (F02) | stated as such; the Pascal basis is used for the additions-only encoder |
| Hasse derivative identity `D^(r) C(x,k) = C(x,k−r)` | false; it holds for forward differences (F03) | not used |
| Seed search guarantees byte packing (~10⁻³²⁷ failure) | unproved model (F04) | replaced by Theorem 1: a deterministic guarantee |
| Whitening guarantees 50/50 balance | false (F05) | scrambler kept for typical data; no guarantee claimed |
| 11s mod 46 interleaver improves damage tolerance | a permutation cannot change d_min (F06) | dropped; a single MDS block needs no interleaving |
| 73 fiducial modules, 46 data bytes at 21×21 | does not tile; 41 bricks max for that layout (F08) | new frame layout: 80 frame modules, 45 data bytes at 21×21, fully specified |
| 30 user bytes at 21×21, t = 7 | conditional at best | 28 bytes at level M (t = 7, guard 0 → 1 with a 10⁻¹⁰ false-accept target) |
| Multiplication-free decoding | not established | encoding is additions-only; decoding uses ordinary modular arithmetic |
| Beats QR | not measured | measured in simulation (README); not yet tested with real cameras |
