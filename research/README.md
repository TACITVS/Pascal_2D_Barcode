# Research: how far beyond QR can a 2D code go?

Goal of the project: a 2D code that carries far more data per printed area
than QR Code, spending the computing power of current phones on decoding.

QR's density is not a law of nature. The hard limit for any code is the
information capacity of the print-to-camera channel (blur, noise,
compression, resolution). QR (1994) uses that channel conservatively:
large modules read one at a time as black or white, then a byte-wise
Reed–Solomon code. This folder measures the ceiling and builds toward it.

## Plan

1. **Measure the ceiling** (`capacity.py`): bits per camera pixel² that the
   simulated channel can carry, for receivers of increasing power, against
   the operating points of QR and PASCAL-MDS v1. *Status: this document.*
2. **Soft decoding** with a modern inner code (`ldpc.py`) on grey-level
   information instead of black/white decisions.
3. **Modules smaller than the blur**, decoded jointly (`multistage.py`).
4. Optional grey levels per module.
5. Field test with real phones.

Pascal's-triangle Reed–Solomon over GF(257) stays as the outer code (exact,
erasure-optimal, false-accept control); the inner layer is chosen for
soft-decision performance.

## Step 1 method

`capacity.py` renders random module patterns on a square grid of pitch `p`
camera pixels per module (8× optical supersampling, Gaussian lens blur,
pixel integration, sensor noise, JPEG quality 75: the same model as
`bench/benchmark.py`), samples a 7 × 7 grid of grey values around every
module centre, and estimates the information rate per module `R(p)` for:

| Receiver | What it knows when deciding module *i* |
|---|---|
| hard | the grey value at the module centre, turned into black/white (how QR reads) |
| soft | grey values around the module; neighbours unknown |
| joint | grey values plus the already-decoded neighbours above and to the left |
| genie | grey values plus every neighbour (reference only) |
| mfb | matched-filter bound: exact upper bound for black/white modules without JPEG |

**Why the numbers are trustworthy.** For any model `q(x | y)`,
`I(X; Y) ≥ H(X) − E[−log₂ q(x | y)]`, evaluated on held-out samples. A
poorly trained model only makes the bound looser, never wrong. For "joint",
the chain rule `I(X; Y) = Σ I(Xᵢ; Y | X₍<i₎)` together with data processing
makes the rate achievable by decoding in stages (multistage / decision
feedback) with ideal codes. Density = `R(p) / p²` bits per camera pixel².

Two channels are measured:

* **ideal**: blur and grid position known exactly; sensor noise σ = 4 grey levels;
* **realistic**: blur varies ±25% per photo without the decoder knowing,
  each module-centre estimate is off by N(0, 0.1 px), and noise is σ = 6.

Both assume the decoder has located the symbol and its grid to that
accuracy; building the structure that achieves this is part of steps 2–3.
