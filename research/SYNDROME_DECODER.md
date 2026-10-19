# Exact syndrome decoder — PM257-SYN-2026-10-19

Baseline: `4be8aa76b346e68a630ffbe8888ee49283078ea0` (2026-10-19 UTC).

The existing readers construct the entire received interpolation polynomial
with Gao's algorithm for every level, mirror and erasure hypothesis. The new
Python `pascal_mds/syndrome.py` and JavaScript `decodeWord` use dual GRS
syndromes, Berlekamp–Massey and Forney error evaluation instead. They return
the corrected evaluation word directly. Gao remains available as an
independent reference. Encoding, format, capacity and acceptance predicates
are unchanged. The Dense outer decoder uses the same new routine.

These are established coding algorithms; the contribution is their exact
specialization and measured integration into this repository. Reference:
O'Sullivan and Bras-Amorós, *The Key Equation for One-Point Codes*, chapter 3
(2008), https://arxiv.org/abs/2108.02758.

## Mathematical certificate

The PB labels continue the earlier PASCAL referee report's PB-01…PB-10.

### Theorem PB-11 — Punctured dual-syndrome certificate

Let I be the s retained coordinates, alpha_i=i+1, 1<=N<=256, and

    w_i = 1 / product_{h in I, h != i}(alpha_i-alpha_h).
    S_j = sum_{i in I} w_i y_i alpha_i^j, 0<=j<s-K.

Then all S_j vanish if and only if the retained values are evaluations of
a polynomial of degree less than K.

Proof: for a polynomial F of degree at most s-2, the coefficient of x^(s-1)
in its Lagrange interpolation is zero, giving sum_i w_i F(alpha_i)=0.
Apply this to F(x)=P(x)x^j. The resulting s-K check rows are independent
(a nonzero row combination is a polynomial of degree less than s-K and
cannot vanish at s distinct nodes). Their nullspace therefore has dimension
K and equals the evaluation code. Shifting every node by one preserves
polynomial degree and avoids zero error locations. ∎

The full-grid weights are (-1)^(N-1-i)/(i!(N-1-i)!). For erased coordinates
E, multiply each full-grid weight by product_{h in E}(i-h). All arithmetic
is modulo 257; no floating point is used.

### Theorem PB-12 — Certified unique decoding

With e erased coordinates, the new routine returns the same unique
polynomial-evaluation word as a valid bounded-distance RS decoder whenever
2t+e<=N-K. Every returned word is in the code and is within that radius of
the retained input.

Proof: the syndrome of the error vector is a sum of t exponentials,
S_j=sum_l A_l alpha_l^j. Berlekamp–Massey recovers the minimal recurrence
Lambda(z)=product_l(1-alpha_l z) from at least 2t moments. Distinct nonzero
locations and nonzero amplitudes make its order t. The roots identify the
error locations; for Omega=(S Lambda) mod z^t,

    A_l = -alpha_l Omega(1/alpha_l) / Lambda'(1/alpha_l).

The implementation rejects a locator exceeding half the available checks,
missing or repeated roots, or corrections that fail to reproduce EVERY
original syndrome. Thus the corrected retained word satisfies PB-11 and
differs in at most floor((s-K)/2) coordinates. Barycentric interpolation
recovers erased values. Two such codewords would differ in at most s-K
retained coordinates, contradicting punctured minimum distance s-K+1. ∎

The caller still applies its stricter byte, header, filler, error-budget and
probability checks. PB-12 does not establish the README's broad false-read
claim for arbitrary photographs; that separate claim needs a noise model.

The cache holds at most 32 punctured check matrices. For fixed redundancy,
the syndrome work is linear in block length; the old naive interpolation is
quadratic. Cold matrix construction and erasure recovery add work. No
asymptotically fast implementation of Gao is being compared here.

## Measured results

Python 3.12, local container. Median of five batches of five decodes; warm
matrix cache. The baseline includes converting Gao's polynomial to the
same corrected word. Times are milliseconds per block.

| N,K | Input | Gao | Syndrome | Speedup |
|---|---|---:|---:|---:|
| 55,37 | clean | 1.115 | 0.071 | 15.77× |
| 55,37 | maximum errors | 1.257 | 0.139 | 9.01× |
| 136,94 | clean | 6.688 | 0.273 | 24.54× |
| 136,94 | maximum errors | 6.662 | 0.645 | 10.33× |
| 253,177 | clean | 20.713 | 0.849 | 24.41× |
| 253,177 | maximum errors | 23.489 | 2.121 | 11.08× |
| 250,246 | clean, Dense outer | 23.950 | 0.076 | 313.47× |
| 250,246 | maximum errors | 22.365 | 0.141 | 158.45× |

Raw Python results also include mixed errors/erasures, random nonwords and
cold cache timings: `bench/syndrome_results_2026-10-19.json`. The full 16
algebra cases show 7.65–313.47× warm speedups. The 250,246 maximum-error
test exercises the low-level radius of two; Dense's caller intentionally
continues accepting at most one erroneous byte per block.

Complete v1 image reader: 16 deterministic simulated photos, URL at widths
44/52 px and contact at 75/90 px, blur sigma 1.2 px, four seeds per condition.
Both implementations returned identical lists on all 16 images: 12 reads,
four rejections, no incorrect payloads. Total read time decreased from
4.399 s to 1.637 s, or **2.69×**. Order alternates by seed. Rendering is
outside the timed section. This is a small local latency benchmark, not
a claim of better optical recovery, phone latency, or more payload capacity.

Node v24.19: separate random inputs, five batches of 20 calls. The 16
algebra cases measured 4.21–325.85× speedups, with exact Gao agreement.
Raw results: `bench/syndrome_js_results_2026-10-19.json`. Node measurements
are not browser or on-device measurements.

## Validation and reproduction

Final run: **356 Python tests passed**, Node v1 **89 checks**, Node v2 **6
checks**. New tests cover every mixed boundary split for representative
dimensions including 256-coordinate edge cases; 7,680 exhaustive single-error
magnitude/location/two-erasure combinations; 240 independent random-input
comparisons with Gao; 100 Python/JavaScript comparisons; malformed inputs
and zero words. Existing image tests include v1, Dense and both JS ports.

The dev extra now installs cv2 and sklearn, which the Dense test module
otherwise skips in CI via importorskip. Production dependencies are unchanged.

```bash
python -m pip install -e '.[dev,bench]'
python -m pytest -o addopts='' -q
node web/test_node.js
node web/test_node_v2.js
python bench/benchmark_syndrome.py --photos 4
node bench/benchmark_syndrome.js
python research/audit_evidence.py
```

The Python benchmark prints a progress bar, elapsed time and ETA. These are
short runs; the expensive channel-capacity training sweep is not rerun.
