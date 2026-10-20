"""PM257-DENSITY-TEST-2026-10-19: research constructions and exact witnesses."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "research"),
                str(Path(__file__).resolve().parents[1] / "research" / "density")]

from capacity import Channel, render  # noqa: E402
from coarse_fine import ShellCode  # noqa: E402
from hierarchical_probe import modulate, patterns  # noqa: E402
import ml_certificate  # noqa: E402
import turbo  # noqa: E402
import gray  # noqa: E402


def test_shell_full_byte_and_guaranteed_coarse_flip_tolerance() -> None:
    code = ShellCode(9, 7)
    words = [code.encode(value) for value in range(256)]
    assert len(set(words)) == 256
    assert code.count_gap == 3 and code.threshold == 3
    for value, word in enumerate(words):
        assert code.decode(word) == value
        for i in range(9):
            damaged = list(word)
            damaged[i] ^= 1
            assert code.coarse(sum(damaged)) == value >> 7


@pytest.mark.parametrize("n,b", [(1, 0), (4, 2), (9, 6), (16, 11), (64, 51)])
def test_shell_ranking_extremes(n: int, b: int) -> None:
    code = ShellCode(n, b)
    for value in [0, 1, (1 << b) - 1, 1 << b, (1 << (b + 1)) - 1]:
        if value < 1 << (b + 1):
            assert code.decode(code.encode(value)) == value


def test_hierarchical_intensity_and_positions() -> None:
    labels, alphabet = patterns()
    assert np.array_equal(alphabet.sum(axis=1), 1 + 2 * labels[:, 0])
    bits = np.array(labels.T).reshape(3, 2, 4)
    grid = modulate(bits)
    for r in range(2):
        for c in range(4):
            tile = grid[2 * r:2 * r + 2, 2 * c:2 * c + 2]
            assert tile.sum() == 1 + 2 * bits[0, r, c]


@pytest.mark.parametrize("rate", [0.25, 0.55, 0.85])
@pytest.mark.parametrize("size", [0, 32, 128])
def test_turbo_lossless_codec(rate: float, size: int) -> None:
    data = np.random.default_rng(size + 7).bytes(size)
    v, _ = turbo.encode(data, rate)
    info = turbo.encode_outer(v, data)
    assert turbo.decode_outer(v, info) == data
    corrupted = info.copy()
    corrupted[:24] ^= 1
    assert turbo.decode_outer(v, corrupted) is None


def test_real_image_to_bytes_with_no_previous_truth() -> None:
    payload = np.random.default_rng(42).bytes(120)
    v, grid = turbo.encode(payload, 0.7)
    pitch, quiet = 1.1, 4
    image, cx, cy = render(np.pad(grid, quiet), Channel(pitch, 0.7, 6, 75),
                          np.random.default_rng(9))
    result, history = turbo.decode(v, image, cx[quiet:quiet + v.S], cy[quiet:quiet + v.S],
                                  pitch, render.last_blur, rounds=16)
    assert result == payload
    assert len(history) > 1 and history[-1]["payload_valid"]


def test_exact_optical_ml_witness_and_tampering() -> None:
    data = np.random.default_rng(101).bytes(128)
    v, grid = turbo.encode(data, 0.55)
    pitch, quiet = 128 / (v.S + 8), 4
    image, cx, cy = render(np.pad(grid, quiet), Channel(pitch, 0.7, 6, 75),
                          np.random.default_rng(10001))
    certificate = ml_certificate.certify(v, data, image, cx[quiet:quiet + v.S],
                                       cy[quiet:quiet + v.S], pitch, render.last_blur)
    assert certificate["status"] == "certified_unique_ml"
    assert ml_certificate.verify(certificate)
    modified = copy.deepcopy(certificate)
    modified["gradient"][0] += 1
    assert not ml_certificate.verify(modified)
    modified = copy.deepcopy(certificate)
    modified["cuts"][0]["bound"] += 1
    assert not ml_certificate.verify(modified)
    modified = copy.deepcopy(certificate)
    modified["model"]["physical_point"][0][0] += 256
    assert not ml_certificate.verify(modified)
    modified = copy.deepcopy(certificate)
    modified["weights"][0] = 0.5
    assert not ml_certificate.verify(modified)
    assert not ml_certificate.verify({"status": "certified_unique_ml"})


def test_optical_soft_output_matches_explicit_gaussian_elimination() -> None:
    """Check both SVD compression and exclusion of each bit's own prior."""
    v, grid = turbo.encode(b"optics", 0.55)
    pitch, quiet = 1.2, 4
    image, cx, cy = render(np.pad(grid, quiet), Channel(pitch, 0.7, 6, 75),
                          np.random.default_rng(24))
    operator = turbo.NativeOperator(image, grid, cx[quiet:quiet + v.S],
                                    cy[quiet:quiet + v.S], pitch, render.last_blur, 8.0)
    # Equal prior variance makes the Gaussian approximation exact.
    probability = 0.3
    prior = np.full((v.S - 4, v.S - 4), np.log((1 - probability) / probability))
    actual = operator.extrinsic(prior).ravel()
    h = np.kron(operator.ay, operator.ax)
    residual = operator.residual.ravel() - h @ np.full(h.shape[1], probability)
    variance = probability * (1 - probability)
    gram = h.T @ h
    system = operator.noise2 * np.eye(h.shape[1]) + variance * gram
    precision = np.linalg.solve(system, gram)
    score = np.linalg.solve(system, h.T @ residual)
    q = np.diag(precision)
    expected = np.clip((q * (0.5 - probability) - score) / (1 - variance * q), -40, 40)
    np.testing.assert_allclose(actual, expected, rtol=1e-9, atol=1e-9)


@pytest.mark.parametrize("rates", [(0.6, 0.6), (0.6, 0.6, 0.6)])
def test_multilevel_actual_image_to_bytes(rates: tuple[float, ...]) -> None:
    data = np.random.default_rng(11).bytes(32)
    v, grid = gray.encode(data, rates)
    quiet, pitch = 4, 2.0
    image, cx, cy = render(np.pad(grid, quiet), Channel(pitch, 0.7, 6, 75),
                          np.random.default_rng(13))
    result, _ = gray.decode(v, image, cx[quiet:quiet + v.S], cy[quiet:quiet + v.S],
                            pitch, render.last_blur)
    assert result == data
