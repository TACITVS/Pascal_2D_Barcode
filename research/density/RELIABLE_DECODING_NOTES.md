# PB-RELIABLE-NOTES-01: mathematical scope and receiver design

## PB-21: sufficient RS errors/erasures condition

Consider an existing GF(257) outer block with four parity symbols. Let S
be a tested erasure set, s its size, and e the number of incorrect decisions
outside S. If 2e+s <= 4, the transmitted word is the unique word within that
RS errors/erasures radius.

**Proof.** An evaluation Reed-Solomon code of dimension k and length n=k+4
on distinct field elements has distance 5: a nonzero polynomial of degree
below k has at most k-1 roots. Two candidate words within this radius would
differ in at most 2e+s <= 4 coordinates, contradicting distance 5. The exact
syndrome decoder implements this recovery, including interpolation at
erasures. Restricting the codebook to byte-representable words cannot lower
its distance.

The receiver tests nested sets of zero, two and four least-reliable bytes.
Recovery is guaranteed if a tested set satisfies the condition for each
block, the correct block combination is within the list budget, and the
payload passes its header/padding/integrity checks. Four blocks give at most
3^4=81 combinations, within the default budget of 256. Larger versions can
have more blocks; their complete candidate product may exceed that budget.

This is the classical RS distance argument and bounded generalized minimum
distance decoding, not a new coding-theory result. Confidence ordering can
be wrong. The unkeyed integrity tag is not authentication, and its length
alone supplies no universal false-read bound.

The frozen Turbo receiver waited for all inner LDPC checks and accepted at
most one repaired byte per outer block. The new receiver permits the full
two-error or four-selected-erasure correction. Damaged-stream tests verify
these cases. The first binary image pilot found no additional final reads.

## Four levels with unequal protection

The data-cell mapper is:

    darkness = (1-a) * coarse_bit + a * fine_bit

At a=1/4 the four levels are 0, 1/4, 3/4 and 1. Coarse clusters are separated
by 1/2, while fine-bit spacing is 1/4. Uniform four-level spacing gives both
gaps 1/3. The selected rates are .85 for the coarse plane and .55 for the
fine plane: more parity protects the less separated fine values.

Both planes exchange soft information with the native-pixel optical model,
and the outer decoder uses combined posterior reliabilities. Expected
source bytes, true data modules and true bit labels never enter a receiver.
This is geometric shaping and unequal protection. There is no distribution
matcher or probabilistic amplitude shaping, and no proof of maximum camera
capacity. Spacing and rates were selected in exploratory trials.

A packet verified before every inner check converges is an early recovery.
Its count does not prove that the inner-only receiver would still fail after
all sixteen rounds. Binary paired results use the same full trajectory.

## Standard-code assistance

QR and Data Matrix get exact geometry, actual blur and common black/white
endpoints, as does the research receiver. Their known pilot patterns are
generated independently from public layout rules. QR data and mask-dependent
format bits remain unknown. No true data modules are copied from the encoder.

ZXing is tried on native pixels, centre samples, Gaussian LMMSE decisions
and a bounded Chase list. Extra candidates force public pilots and condition
a matrix-free Gaussian solve on them. The conditioned solve gives Gaussian
posterior-mean decision signs to numerical tolerance; it is not binary MAP or
soft-input Reed-Solomon decoding. Tests check pilot values against independent
writers and different random payloads. Commercial readers remain untested.

## One confidence budget for both fresh studies

The first plan fixed 48 operating-point/receiver combinations before fresh
trials. Its saved records retain its original 48-point intervals. Eight
follow-up standard-code points use an independent seed set.

The combined report recomputes every interval with per-tail alpha=0.05/112.
The original 48 fixed intervals contribute at most 48*0.05/56 failure
probability. Conditional on the original data, each independently sampled
follow-up interval has pointwise coverage regardless of the selected width.
The eight contribute at most 8*0.05/56. A union bound gives at least 95%
simultaneous coverage for all 56. No optional stopping is used.

Trials are independent within each point. Correlated draws between paired
formats do not invalidate the union bound. Only finite widths were tested;
none is proved to be a globally minimal footprint.

## Primary prior art

* Senger, Sidorenko and Zyablov, *On Generalized Minimum Distance Decoding
  Thresholds for the AWGN Channel* (2009):
  https://arxiv.org/abs/0903.3204
* Zhang, Chen and Mow, *Accurate Modeling and Efficient Estimation of the
  Print-Capture Channel with Application in Barcoding*, IEEE TIP 28(1),
  464-478 (2019), DOI 10.1109/TIP.2018.2868383:
  https://researchportal.hkust.edu.hk/en/publications/accurate-modeling-and-efficient-estimation-of-the-print-capture-c/

Multilevel barcodes, LDPC soft decoding, channel estimation and GMD have
substantial prior art. The contribution here is tested profile/receiver
integration and reproducible comparisons. Global novelty and world leadership
are not established by these results.
