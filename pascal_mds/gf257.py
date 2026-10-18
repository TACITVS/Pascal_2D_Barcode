"""Arithmetic over the Fermat prime field GF(257) in Pascal's (Newton/binomial) basis.

Encoding uses only Pascal's rule: every step adds or subtracts two neighbours
mod 257, exactly like building a row of Pascal's triangle.  No multiplication
and no lookup tables are needed to produce a codeword.

Decoding (errors and erasures) uses Gao's algorithm, which needs ordinary
modular multiplication and inversion.  All arithmetic is exact.
"""

from __future__ import annotations

P = 257


def difference_diagonal(values: list[int]) -> list[int]:
    """Backward-difference diagonal of ``values``: b[k] = nabla^k f(K-1).

    The difference triangle is Pascal's rule run in reverse (each entry is the
    difference of its two neighbours); only subtractions mod 257 are used.
    """
    row = [v % P for v in values]
    diag: list[int] = []
    while row:
        diag.append(row[-1])
        row = [(row[j + 1] - row[j]) % P for j in range(len(row) - 1)]
    return diag


def pascal_extend(values: list[int], count: int) -> list[int]:
    """Values f(K), ..., f(K+count-1) of the unique polynomial of degree < K
    with f(x) = values[x] for x = 0..K-1.  Additions mod 257 only.

    Uses nabla^k f(x+1) = nabla^k f(x) + nabla^(k+1) f(x+1); nabla^(K-1) f is
    constant because deg f < K.
    """
    b = difference_diagonal(values)
    out: list[int] = []
    for _ in range(count):
        for k in range(len(b) - 2, -1, -1):
            s = b[k] + b[k + 1]
            b[k] = s - P if s >= P else s
        out.append(b[0])
    return out


# --------------------------------------------------------------------------
# Polynomials over GF(257): little-endian coefficient lists, no trailing zeros.

def _trim(a: list[int]) -> list[int]:
    while a and a[-1] == 0:
        a.pop()
    return a


def poly_eval(a: list[int], x: int) -> int:
    acc = 0
    for coef in reversed(a):
        acc = (acc * x + coef) % P
    return acc


def poly_mul(a: list[int], b: list[int]) -> list[int]:
    if not a or not b:
        return []
    out = [0] * (len(a) + len(b) - 1)
    for i, ai in enumerate(a):
        if ai:
            for j, bj in enumerate(b):
                out[i + j] = (out[i + j] + ai * bj) % P
    return _trim(out)


def poly_sub(a: list[int], b: list[int]) -> list[int]:
    n = max(len(a), len(b))
    out = [((a[i] if i < len(a) else 0) - (b[i] if i < len(b) else 0)) % P for i in range(n)]
    return _trim(out)


def poly_divmod(a: list[int], b: list[int]) -> tuple[list[int], list[int]]:
    if not b:
        raise ZeroDivisionError("polynomial division by zero")
    rem = list(a)
    if len(rem) < len(b):
        return [], _trim(rem)
    inv_lead = pow(b[-1], P - 2, P)
    quot = [0] * (len(rem) - len(b) + 1)
    for shift in range(len(rem) - len(b), -1, -1):
        coef = rem[shift + len(b) - 1] * inv_lead % P
        quot[shift] = coef
        if coef:
            for j, bj in enumerate(b):
                rem[shift + j] = (rem[shift + j] - coef * bj) % P
    return _trim(quot), _trim(rem[: len(b) - 1])


def interpolate(xs: list[int], ys: list[int]) -> list[int]:
    """Monomial coefficients of the polynomial of degree < len(xs) through the
    points (Newton divided differences, then Horner expansion)."""
    n = len(xs)
    coef = [y % P for y in ys]
    for level in range(1, n):
        for i in range(n - 1, level - 1, -1):
            den = (xs[i] - xs[i - level]) % P
            coef[i] = (coef[i] - coef[i - 1]) * pow(den, P - 2, P) % P
    poly = [coef[-1]] if n else []
    for i in range(n - 2, -1, -1):
        # poly = poly * (x - xs[i]) + coef[i]
        shifted = [0] + poly
        for j in range(len(poly)):
            shifted[j] = (shifted[j] - xs[i] * poly[j]) % P
        shifted[0] = (shifted[0] + coef[i]) % P
        poly = shifted
    return _trim(poly)


def gao_decode(xs: list[int], ys: list[int], k: int) -> list[int] | None:
    """Unique decoding of a Reed-Solomon (evaluation) code over GF(257).

    Given received values ys at distinct points xs (erased points already
    removed), return the monomial coefficients of the unique polynomial f with
    deg f < k that disagrees with ys in at most (len(xs) - k) // 2 points, or
    None when no such polynomial exists.  (S. Gao, "A new algorithm for
    decoding Reed-Solomon codes", 2003.)
    """
    n = len(xs)
    if n < k:
        return None
    g0: list[int] = [1]
    for x in xs:
        g0 = poly_mul(g0, [(-x) % P, 1])
    g1 = interpolate(xs, ys)
    r0, r1 = g0, g1
    v0: list[int] = []
    v1: list[int] = [1]
    # Partial extended Euclid: stop at the first remainder of degree < (n+k)/2.
    while len(r1) - 1 >= (n + k) / 2:
        q, rem = poly_divmod(r0, r1)
        r0, r1 = r1, rem
        v0, v1 = v1, poly_sub(v0, poly_mul(q, v1))
    if not v1:
        return None
    f, rem = poly_divmod(r1, v1)
    if rem or len(f) > k:
        return None
    return f
