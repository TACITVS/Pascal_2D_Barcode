"""PM257-SYN-TEST-2026-10-19: independent decoder equivalence checks."""

from __future__ import annotations

import itertools
import json
import random
import shutil
import subprocess
from pathlib import Path

import pytest

from pascal_mds import gf257
from pascal_mds.syndrome import decode_word


def reference(length: int, k: int, received: list[int | None]) -> list[int] | None:
    kept = [i for i, y in enumerate(received) if y is not None]
    poly = gf257.gao_decode(kept, [received[i] for i in kept], k)
    if poly is None:
        return None
    word = [gf257.poly_eval(poly, i) for i in range(length)]
    errors = sum(word[i] != received[i] for i in kept)
    return word if 2 * errors <= len(kept) - k else None


@pytest.mark.parametrize("length,k", [(3, 1), (10, 4), (45, 30), (136, 94),
                                       (253, 177), (256, 1), (256, 255), (256, 256)])
def test_all_mixed_boundary_splits(length: int, k: int) -> None:
    rng = random.Random(length * 1000 + k)
    coefficients = [rng.randrange(257) for _ in range(k)]
    word = [gf257.poly_eval(coefficients, i) for i in range(length)]
    # Sweep every errors/erasures boundary split, including exactly k kept.
    for erasures in range(length - k + 1):
        errors = (length - k - erasures) // 2
        positions = rng.sample(range(length), erasures + errors)
        received: list[int | None] = list(word)
        for i in positions[:erasures]:
            received[i] = None
        for i in positions[erasures:]:
            received[i] = (word[i] + rng.randrange(1, 257)) % 257
        assert decode_word(length, k, received) == word


def test_exhaustive_single_error_values_and_erasure_positions() -> None:
    # Every nonzero field error magnitude, all locations, all <=2 erasures
    # disjoint from the error. This includes x=0 and received field value 256.
    length, k = 5, 1
    word = [256] * length
    for error in range(length):
        others = [i for i in range(length) if i != error]
        for erasures in itertools.combinations(others, 2):
            for delta in range(1, 257):
                received: list[int | None] = list(word)
                received[error] = (256 + delta) % 257
                for i in erasures:
                    received[i] = None
                assert decode_word(length, k, received) == word


def test_random_inputs_match_independent_gao() -> None:
    rng = random.Random(20261019)
    for _ in range(240):
        length = rng.choice([3, 10, 21, 45, 91, 253])
        k = rng.randrange(1, length + 1)
        received: list[int | None] = [rng.randrange(257) for _ in range(length)]
        for i in rng.sample(range(length), rng.randrange(length + 1)):
            received[i] = None
        assert decode_word(length, k, received) == reference(length, k, received)


@pytest.mark.parametrize("length,k,received", [(0, 0, []), (257, 1, [0] * 257),
                                               (3, 1, [0]), (3, 1, [257, 0, 0])])
def test_invalid_dimensions_and_field_values(
    length: int, k: int, received: list[int | None]
) -> None:
    with pytest.raises(ValueError):
        decode_word(length, k, received)


def test_too_many_erasures_and_zero_word() -> None:
    assert decode_word(5, 3, [None, None, None, 0, 0]) is None
    assert decode_word(5, 3, [0, None, None, 0, 0]) == [0] * 5


@pytest.mark.skipif(shutil.which("node") is None, reason="Node not installed")
def test_javascript_word_decoder_matches_python() -> None:
    rng = random.Random(41019)
    cases = []
    for _ in range(100):
        length = rng.choice([5, 21, 55, 136, 250, 253, 256])
        k = rng.randrange(1, length + 1)
        word = [gf257.poly_eval([rng.randrange(257) for _ in range(k)], i)
                for i in range(length)]
        # Alternate random nonwords with genuine, bounded-distance examples.
        if len(cases) % 2:
            message = [rng.randrange(257) for _ in range(k)]
            word = [gf257.poly_eval(message, i) for i in range(length)]
        erasures = rng.randrange(length - k + 1)
        errors = (length - k - erasures) // 2
        positions = rng.sample(range(length), erasures + errors)
        received: list[int | None] = list(word)
        for i in positions[:erasures]:
            received[i] = None
        for i in positions[erasures:]:
            received[i] = (word[i] + rng.randrange(1, 257)) % 257
        cases.append([length, k, received])
    script = (
        "const p = require('./web/pascal_mds.js');"
        "const fs = require('fs');"
        "console.log(JSON.stringify(JSON.parse(fs.readFileSync(0, 'utf8'))"
        ".map(([n,k,y]) => p.decodeWord(n,k,y))));"
    )
    out = subprocess.run(["node", "-e", script], input=json.dumps(cases),
                         cwd=Path(__file__).resolve().parents[1],
                         capture_output=True, text=True, check=True, timeout=30)
    assert json.loads(out.stdout) == [decode_word(*case) for case in cases]
