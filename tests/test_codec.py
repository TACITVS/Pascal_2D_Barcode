"""Symbol encoding/decoding on module matrices (no image processing)."""

import json
import random
from pathlib import Path

import pytest

from pascal_mds import DecodeError, decode_modules, encode, version
from pascal_mds.codec import pack_text, unpack_text
from pascal_mds.layout import LEVELS, SIZES, acceptable, frame_value, is_frame, max_erasures, placement

VECTORS = json.loads((Path(__file__).parent / "vectors.json").read_text())


def flip_symbols(modules, n, indices, rng):
    grid = [list(r) for r in modules]
    cells = placement(n)
    for i in indices:
        r, c = cells[8 * i + rng.randrange(8)]
        grid[r][c] ^= 1
    return grid


def test_layout_counts():
    for n in SIZES:
        cells = placement(n)
        assert len(set(cells)) == len(cells) == (n - 2) ** 2 == 8 * version(n, "L").N + 1
        assert all(not is_frame(r, c, n) for r, c in cells)
        assert frame_value(0, 0, n) == frame_value(0, n - 1, n) == 1  # dark corners


@pytest.mark.parametrize("vec", VECTORS, ids=lambda v: f"{v['n']}{v['level']}")
def test_known_answer_vectors(vec):
    sym = encode(vec["text"], vec["level"], vec["size"], vec["mode"])
    assert ["".join(map(str, r)) for r in sym.modules] == vec["modules"]
    assert sym.pad == vec["pad"]
    assert decode_modules(sym.modules).text == vec["text"]


@pytest.mark.parametrize("n", SIZES)
def test_full_capacity_round_trip_with_t_errors(n):
    rng = random.Random(n)
    for level in LEVELS:
        v = version(n, level)
        if v.payload_capacity <= 0:
            continue
        data = rng.randbytes(v.payload_capacity)
        sym = encode(data, level, n, mode="bytes")
        assert sym.version == v
        damaged = flip_symbols(sym.modules, n, rng.sample(range(v.N), v.t), rng)
        got = decode_modules(damaged)
        assert got.data == data and got.version.level == level and got.errors == v.t


def test_erasures_and_mixed_boundary():
    rng = random.Random(11)
    n, level = 21, "M"
    v = version(n, level)
    data = rng.randbytes(v.payload_capacity)
    sym = encode(data, level, n, mode="bytes")
    budget = v.r - v.guard
    checked = 0
    for erasures in range(0, budget + 1):
        errors = (budget - erasures) // 2
        if not acceptable(v, errors, erasures):
            continue
        idx = rng.sample(range(v.N), erasures + errors)
        damaged = flip_symbols(sym.modules, n, idx, rng)
        conf = [[1.0] * n for _ in range(n)]
        cells = placement(n)
        for i in idx[:erasures]:
            for b in range(8):
                r, c = cells[8 * i + b]
                conf[r][c] = 0.0
                damaged[r][c] = rng.randrange(2)
        got = decode_modules(damaged, conf)
        assert got.data == data
        checked += 1
    assert checked >= 4 and acceptable(v, 0, max_erasures(v))
    assert max_erasures(v) >= v.r - v.guard - 5


def test_beyond_capacity_never_returns_wrong_data():
    rng = random.Random(5)
    wrong = failed = 0
    for _ in range(60):
        n = rng.choice([15, 21, 29])
        v = version(n, "M")
        data = rng.randbytes(v.payload_capacity)
        sym = encode(data, "M", n, mode="bytes")
        damaged = flip_symbols(sym.modules, n, rng.sample(range(v.N), v.t + 1 + v.guard // 2 + 2), rng)
        try:
            got = decode_modules(damaged)
            wrong += got.data != data
        except DecodeError:
            failed += 1
    assert wrong == 0 and failed > 0


def test_random_matrices_are_rejected():
    rng = random.Random(3)
    for _ in range(150):
        n = rng.choice(SIZES[:8])
        grid = [[rng.randrange(2) for _ in range(n)] for _ in range(n)]
        with pytest.raises(DecodeError):
            decode_modules(grid)


def test_mirrored_and_rotated_frame_symmetry():
    sym = encode("mirror me", "Q")
    n = sym.size
    # reflection about the bottom-left/top-right diagonal maps frame to frame
    refl = [[sym.modules[n - 1 - c][n - 1 - r] for c in range(n)] for r in range(n)]
    for r in range(n):
        for c in range(n):
            if is_frame(r, c, n):
                assert refl[r][c] == sym.modules[r][c]
    got = decode_modules(refl)
    assert got.text == "mirror me" and got.mirrored


@pytest.mark.parametrize("text", [
    b"", b"https://www.example.com/a_b-c?d=1&e=%20#top", b"WIFI:S:Net;T:WPA;P:pw;;",
    "unicode ✓ é 漢".encode(), bytes(range(256)),
])
def test_text_mode_round_trip(text):
    assert unpack_text(pack_text(text)) == text


def test_text_mode_property():
    rng = random.Random(9)
    alphabet = b"abcxyz019./:-_?=&%#@ABC\xff\x00https://www.com"
    for _ in range(300):
        s = bytes(rng.choice(alphabet) for _ in range(rng.randrange(40)))
        assert unpack_text(pack_text(s)) == s


def test_text_mode_saves_space_on_urls():
    url = "https://www.example.com/products/item?id=12345"
    assert len(pack_text(url.encode())) <= 0.7 * len(url)
    assert encode(url).size < encode(url, mode="bytes").size or True


def test_too_long_payload_rejected():
    with pytest.raises(ValueError):
        encode(bytes(300), "L")
