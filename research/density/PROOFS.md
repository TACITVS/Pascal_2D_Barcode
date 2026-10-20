# Mathematical statements for the density experiments

2026-10-19. Statement numbers continue the project's earlier PB-01–PB-14
analysis. These are proofs of precisely stated components, not assertions of
world novelty. The accompanying implementation uses known coding, estimation,
and optimization techniques. None of these statements proves that the complete
barcode is optimal for real print/capture channels.

## PB-15 — Optimal ordered coarse-intensity separation

Let two classes of binary patterns of length n each contain at least 2^b
distinct patterns. A pattern's ideal observed darkness is its Hamming weight
divided by n. Require every member of the low class to have lower darkness
than every member of the high class. Define

\[
t=\min\{s:\sum_{j=0}^{s}{n\choose j}\ge 2^b\}.
\]

If 2t<n, the largest possible gap between the darkest low pattern and the
lightest high pattern is exactly

\[
\Delta^*=(n-2t)/n.
\]

**Proof.** There are fewer than 2^b patterns with weight strictly below t, so
the low class must contain a pattern of weight at least t. By complementation,
the high class must contain a pattern of weight at most n−t. The gap is
therefore at most (n−2t)/n. Choose any 2^b lowest-weight patterns, taking all
weights below t first, and use their complements as the high class. The two
classes attain that gap. ∎

`ShellCode` implements an efficient combinatorial rank/unrank bijection.
For n=9, b=7, the binomial tail through weight 3 contains 130 patterns. Select
128 and their complements to encode a complete arbitrary byte in a 3×3 binary
tile. Its coarse bit separates weights at most 3 from weights at least 6.
Any single module flip leaves this bit recoverable by a threshold of 4.5.
The other seven bits have no such guarantee. Their protection must be supplied
by a fine-scale code. Blur between adjacent tiles, unknown illumination, and
finite sensor integration are outside the ideal average model of this theorem.
This construction is a candidate modulation, not the format used in the
successful packet-density measurements.

## PB-16 — Lossless separable optical sufficient statistic

Suppose a registered linear observation, after subtraction of the known frame,
is

\[
Y=A_y X A_x^T+Z,
\]

where the entries of Z are independent N(0,σ²), and the two optical operators
are known. Let A_x=U_xΣ_xV_x^T and A_y=U_yΣ_yV_y^T be reduced SVDs whose U
columns span their signal spaces. Then

\[
T=U_y^T Y U_x
\]

is a sufficient statistic for X. Its noise remains independent Gaussian with
variance σ² per entry. Its signal is Σ_y V_y^T X V_x Σ_x.

**Proof.** Vectorization gives a signal in the column space of U_x⊗U_y.
Complete this orthonormal basis and rotate the observation. The first block
is vec(T); every other coordinate has zero signal mean. Isotropic Gaussian
noise makes the blocks independent, and the other coordinates' distribution
does not depend on X. Their likelihood factor cancels in every comparison
between inputs. ∎

This avoids assigning independent evidence to repeated interpolated samples
of the same sensor pixels. It does not make the prototype's Gaussian
interference approximation or loopy LDPC feedback exact. JPEG, tone curves,
nonseparable blur, and registration errors violate the stated likelihood model.

## PB-17 — A channel-dependent upper bound on reliable payload

Let K uniformly distributed message bits be mapped to N intensity values in
[0,1], observed through y=Hx+z with known H and white Gaussian noise of variance
σ². Suppose the message error probability is at most ε≤1/2. If λ_i are the
positive eigenvalues of H^T H, define

\[
C_G=\max_{p_i\ge0,\ \sum_i p_i\le N/4}
\frac12\sum_i\log_2(1+\lambda_i p_i/\sigma^2).
\]

For binary cells,

\[
(1-\varepsilon)K\le\min(N,C_G)+h_2(\varepsilon).
\]

For B allowed intensity levels, replace N in the minimum by N log₂ B.

**Proof.** Fano's inequality gives
H(M|Y)≤h₂(ε)+εK, hence (1−ε)K≤I(M;Y)+h₂(ε).
Every [0,1] coordinate has variance at most 1/4, so tr Cov(X)≤N/4.
Replacing the output distribution by a Gaussian of the same covariance
upper-bounds its differential entropy. Maximizing the resulting log-determinant
over all positive semidefinite input covariances with this trace constraint
diagonalizes in H's right singular vectors and gives the stated waterfilling
optimization. The discrete input entropy also bounds I(M;Y) by N log₂ B.
Combine both bounds. ∎

The power allocation is p_i=(μ−σ²/λ_i)_+ with μ chosen for the trace constraint.
The intensity constraints and code restrictions are relaxed, so this is usually
a loose upper bound, not an achievable rate. `relaxed_capacity_bound()` computes
a floating-point estimate of this relaxation; its eigenvalue truncation and
numerics are not a certified upper enclosure. No reported density claim relies
on that numerical estimate. Area must include the frame and quiet zone.
Without a specified optical channel, alphabet, allowed area, and error target,
there is no single numerical answer to “maximum reliable density.”

## PB-18 — An exactly checkable unique-ML witness

Fix a binary linear code and a rational optical least-squares objective
F(x)=||Ax−b||², represented after scaling by integer A,b. Let Q=A^T A.
Choose an exactly justified γ≥0 with Q−γI positive semidefinite. The polynomial

\[
\phi(x)=F(x)+\gamma\sum_i x_i(1-x_i)
\]

is convex and agrees with F at every binary word. Let x̂ be a codeword and
c=∇φ(x̂). Let Cx≤d be any collection of inequalities valid for all other
codewords, including the exclusion inequality

\[
\sum_i(2\hat x_i-1)x_i\le\sum_i\hat x_i-1.
\]

For any λ≥0, define

\[
L(\lambda)=\sum_i\min(0,c_i+(C^T\lambda)_i)-\lambda^T d.
\]

If L(λ)>c^T x̂, then x̂ is the unique minimizer of F over the code.

**Proof.** For every other codeword x, nonnegative λ gives
c^T x ≥ c^T x+λ^T(Cx−d) ≥ L(λ), where the last minimum is over the entire
box [0,1]^N. Convexity gives φ(x)≥φ(x̂)+c^T(x−x̂)>φ(x̂). Binary equivalence
then gives F(x)>F(x̂). ∎

The implementation uses forbidden-set inequalities of even parity checks:
for each odd subset S of a check neighborhood J,

\[
\sum_{i\in S}x_i-\sum_{i\in J\setminus S}x_i\le |S|-1.
\]

They hold because a binary assignment violating the inequality would have
exactly the odd set S as its ones in J. For the separable integer optical
operator A=200(A_x⊗A_y), set G_x=A_x^T A_x, G_y=A_y^T A_y and

\[
\ell_x=\max(0,\min_i[G_{x,ii}-\sum_{j\ne i}|G_{x,ij}|]),
\quad\ell_y\text{ analogously},\qquad
\gamma=200^2\ell_x\ell_y.
\]

Gershgorin's theorem and positivity of both Gram matrices justify the shift.
The permutation and binary complement mask are affine orthogonal changes of
coordinates, preserving convexity. An LP proposes nonnegative dual weights.
They are rounded to integers over a common denominator, and the entire strict
inequality is rechecked using integer arithmetic. Floating-point LP success
alone never constitutes a certificate.

The verifier checks candidate code membership, binary physical values,
mapping, the shift, every cut, and a freshly recomputed gradient. It proves
optimality only for the explicitly published rational model and known code
profile. It cannot certify that this model is the true printer/camera channel.
`uncertified` is an allowed outcome; density-limit examples did not certify.

## PB-19 — Payload injectivity, independent of correction performance

For every supported prototype profile and payload within its stated capacity,
the encoder maps distinct byte strings to distinct printed binary grids.

**Proof.** The length header and payload bytes are present systematically
before the outer parity extension; the extra tag is deterministic. The
GF(257) extension preserves those bytes while choosing an auxiliary pad so
the whole outer word remains byte-valued. Each of the four parity coordinates
is affine in this pad with a nonzero coefficient: the coefficient is the
last systematic point's Lagrange polynomial evaluated at a distinct parity
point, with all evaluation points distinct in GF(257). Each coordinate
therefore forbids at most one of the 256 byte-valued pad choices. At most four
choices are excluded, so an admissible pad exists. Interleaving, bit packing, and zero extension
preserve the systematic stream. The IRA encoder is systematic and therefore
injective. Physical permutation and XOR with a fixed mask are bijections.
Consequently different payloads cannot print the same grid. ∎

This statement explains why random incompressible bytes fit without a hidden
dictionary or server lookup. It supplies no error correction radius and no
guarantee about the decoder's convergence or false acceptance rate.

## Relationship to previous research

These proofs specialize established tools. Joint detection/decoding of 2D ISI
channels, multilevel coding, LP decoding certificates, and diagonal convex
relaxations precede this project. The project contribution here is the tested
format/receiver integration and a concrete integer-verifiable optical witness.
No exhaustive novelty or patent search has been performed.

- Soriaga, Siegel, Wolf and Marrow,
  [On Achievable Rates of Multistage Decoding on Two-Dimensional ISI Channels](https://cmrr-star.ucsd.edu/static/pubs/achievable_rates_multistage_2D.pdf).
- Kim and Pfister (2010),
  [On the Joint Decoding of LDPC Codes and Finite-State Channels via Linear Programming](https://arxiv.org/abs/1005.0052).
- Zhang, Chen and Mow (2019),
  [Accurate Modeling and Efficient Estimation of Print-Capture Channel With Application in Barcoding](https://ieeexplore.ieee.org/document/8453836/).
