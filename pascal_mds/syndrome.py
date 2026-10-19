"""PM257-SYN-2026-10-19: exact word decoding of the existing RS code.

Dual GRS syndromes, Berlekamp--Massey, and Forney error evaluation avoid
interpolating an entire received polynomial for every decoding hypothesis.
The format and the caller's acceptance policy are unchanged. Gao's decoder
in gf257.py remains an independent reference implementation.
"""

from __future__ import annotations

from functools import lru_cache

from .gf257 import P, poly_eval


@lru_cache(maxsize=1)
def _inverses() -> tuple[int, ...]:
    return (0,) + tuple(pow(a, P - 2, P) for a in range(1, P))


@lru_cache(maxsize=32)
def _checks(
    length: int, k: int, kept: tuple[int, ...]
) -> tuple[tuple[int, ...], tuple[tuple[int, ...], ...]]:
    """Punctured dual weights and parity-check rows; bounded geometry cache."""
    inv = _inverses()
    # For the full consecutive grid, w_i = (-1)^(N-1-i)/(i! (N-1-i)!).
    factorial = [1]
    for i in range(1, length):
        factorial.append(factorial[-1] * i % P)
    erased = sorted(set(range(length)).difference(kept))
    weights = []
    for i in kept:
        w = inv[factorial[i] * factorial[length - 1 - i] % P]
        if (length - 1 - i) % 2:
            w = -w % P
        for j in erased:
            w = w * (i - j) % P
        weights.append(w)
    # Shift x_i=i to alpha_i=i+1. The polynomial space is unchanged,
    # and all alpha_i are nonzero for the supported lengths <=256.
    row = tuple(weights)
    checks = []
    for _ in range(len(kept) - k):
        checks.append(row)
        row = tuple(w * (i + 1) % P for w, i in zip(row, kept))
    return tuple(weights), tuple(checks)


def _locator(syndromes: list[int]) -> list[int]:
    """Minimal recurrence C(z), C(0)=1, by Berlekamp--Massey."""
    current, previous = [1], [1]
    degree, shift, last = 0, 1, 1
    inv = _inverses()
    for n, value in enumerate(syndromes):
        discrepancy = (value + sum(
            current[j] * syndromes[n - j]
            for j in range(1, degree + 1)
        )) % P
        if not discrepancy:
            shift += 1
            continue
        before = current[:]
        factor = discrepancy * inv[last] % P
        required = len(previous) + shift
        current += [0] * max(0, required - len(current))
        for j, coefficient in enumerate(previous):
            current[j + shift] = (current[j + shift] - factor * coefficient) % P
        if 2 * degree <= n:
            degree = n + 1 - degree
            previous, last, shift = before, discrepancy, 1
        else:
            shift += 1
    return current[:degree + 1]


def decode_word(
    length: int, k: int, received: list[int | None]
) -> list[int] | None:
    """Return the unique RS word within 2*errors+erasures <= length-k.

    Coordinates are evaluations at 0..length-1 over GF(257), 1<=length<=256.
    None marks an erasure. Symbols may include the full field value 256;
    byte representability and integrity checks belong to the calling codec.
    """
    if not 1 <= k <= length <= 256 or len(received) != length:
        raise ValueError("invalid RS dimensions")
    if any(y is not None and not 0 <= y < P for y in received):
        raise ValueError("received symbol outside GF(257)")
    kept = tuple(i for i, y in enumerate(received) if y is not None)
    if len(kept) < k:
        return None
    values = [y for y in received if y is not None]
    weights, checks = _checks(length, k, kept)
    syndromes = [sum(w * y for w, y in zip(row, values)) % P for row in checks]
    if any(syndromes):
        locator = _locator(syndromes)
        degree = len(locator) - 1
        if not degree or 2 * degree > len(checks):
            return None
        inv = _inverses()
        locations = [j for j, i in enumerate(kept)
                     if poly_eval(locator, inv[i + 1]) == 0]
        if len(locations) != degree:
            return None
        # Omega(z) = (S(z) Lambda(z)) mod z^degree.
        omega = [sum(locator[j] * syndromes[n - j]
                     for j in range(n + 1)) % P for n in range(degree)]
        derivative = [j * locator[j] % P for j in range(1, len(locator))]
        predicted = [0] * len(checks)
        for j in locations:
            alpha = kept[j] + 1
            root = inv[alpha]
            denom = poly_eval(derivative, root)
            if not denom:
                return None
            amplitude = -alpha * poly_eval(omega, root) * inv[denom] % P
            values[j] = (values[j] - amplitude * inv[weights[j]]) % P
            term = amplitude
            for n in range(len(predicted)):
                predicted[n] = (predicted[n] + term) % P
                term = term * alpha % P
        # Membership certificate: corrected kept values have zero syndrome.
        if predicted != syndromes:
            return None
    word = [0] * length
    for i, y in zip(kept, values):
        word[i] = y
    # Barycentric interpolation only at erased coordinates. Zero syndromes
    # already certify degree < k, so no monomial polynomial is necessary.
    inv = _inverses()
    for x in sorted(set(range(length)).difference(kept)):
        product, total = 1, 0
        for i, y, w in zip(kept, values, weights):
            delta = (x - i) % P
            product = product * delta % P
            total += y * w * inv[delta]
        word[x] = product * total % P
    return word
