"""GF(257) Pascal-basis arithmetic, Gao decoding, and Theorem 1 (pad)."""

import random
from math import comb

import pytest

from pascal_mds import gf257
from pascal_mds.codec import _choose_pad
from pascal_mds.layout import SIZES, version

P = 257


def lagrange_eval(values, x):
    total = 0
    k = len(values)
    for j, v in enumerate(values):
        num = den = 1
        for i in range(k):
            if i != j:
                num = num * (x - i) % P
                den = den * (j - i) % P
        total += v * num * pow(den, P - 2, P)
    return total % P


@pytest.mark.parametrize("k", [1, 2, 3, 7, 32])
def test_pascal_extend_matches_lagrange(k):
    rng = random.Random(k)
    values = [rng.randrange(256) for _ in range(k)]
    ext = gf257.pascal_extend(values, 300 - k)
    assert ext == [lagrange_eval(values, x) for x in range(k, 300)]


def test_forward_differences_are_newton_coefficients():
    # u_k = Delta^k f(0) gives f(x) = sum u_k C(x, k)  (Gregory-Newton)
    rng = random.Random(2)
    values = [rng.randrange(257) for _ in range(12)]
    row, u = list(values), []
    while row:
        u.append(row[0])
        row = [(row[j + 1] - row[j]) % P for j in range(len(row) - 1)]
    for x in range(40):
        assert sum(uk * comb(x, k) for k, uk in enumerate(u)) % P == lagrange_eval(values, x)


@pytest.mark.parametrize("k", range(1, 257))
def test_pad_influence_is_binomial_and_nonzero(k):
    """Lemma of Theorem 1: the pad at position K-1 adds s*C(x, K-1) to the
    parity at x, and C(x, K-1) is nonzero mod 257 for K <= x <= 256."""
    unit = gf257.pascal_extend([0] * (k - 1) + [1], 257 - k)
    assert unit == [comb(x, k - 1) % P for x in range(k, 257)]
    assert all(unit)


@pytest.mark.parametrize("r", [1, 2, 14, 100, 255])
def test_choose_pad_survives_adversarial_parity(r):
    """Theorem 1: with r <= 255 parity symbols a pad in 0..r always works,
    even when pads 0..r-1 are each blocked by a different parity symbol."""
    rng = random.Random(r)
    unit = [rng.randrange(1, P) for _ in range(r)]
    # parity x is 256 exactly when the pad equals j_x = x
    parity0 = [(256 - j * g) % P for j, g in enumerate(unit)]
    s, parity = _choose_pad(parity0, unit)
    assert s == r
    assert parity == [(c + s * g) % P for c, g in zip(parity0, unit)]
    assert all(v <= 255 for v in parity)


def test_all_versions_within_theorem_1():
    for n in SIZES:
        for level in "LMQH":
            v = version(n, level)
            assert v.N <= 256 and v.r <= 255 and v.K >= 1


@pytest.mark.parametrize("n,k", [(10, 4), (36, 23), (45, 31), (253, 177)])
def test_gao_corrects_up_to_radius(n, k):
    rng = random.Random(n * 1000 + k)
    for _ in range(5):
        msg = [rng.randrange(256) for _ in range(k)]
        word = msg + gf257.pascal_extend(msg, n - k)
        for errors in (0, (n - k) // 2):
            recv = list(word)
            for i in rng.sample(range(n), errors):
                recv[i] = (recv[i] + rng.randrange(1, P)) % P
            f = gf257.gao_decode(list(range(n)), recv, k)
            assert f is not None
            assert [gf257.poly_eval(f, x) for x in range(n)] == word


def test_gao_with_erasures_boundary():
    rng = random.Random(7)
    n, k = 46, 32
    msg = [rng.randrange(256) for _ in range(k)]
    word = msg + gf257.pascal_extend(msg, n - k)
    for erasures in range(0, n - k + 1, 2):
        errors = (n - k - erasures) // 2
        idx = rng.sample(range(n), erasures + errors)
        keep = sorted(set(range(n)) - set(idx[:erasures]))
        recv = {i: word[i] for i in keep}
        for i in idx[erasures:]:
            recv[i] = (recv[i] + 1 + rng.randrange(256)) % P
        f = gf257.gao_decode(keep, [recv[i] for i in keep], k)
        assert f is not None and [gf257.poly_eval(f, x) for x in range(n)] == word
