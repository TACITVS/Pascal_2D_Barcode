"""Tests with damaged encoded streams, not expected-payload-aided decoding."""

from __future__ import annotations

import numpy as np
import pytest

from research.density import soft_outer, turbo


def _damage(
    count: int, per_block: bool = False,
) -> tuple[turbo.Version, bytes, np.ndarray, np.ndarray]:
    data = np.random.default_rng(7109).bytes(800)
    v, _ = turbo.encode(data, rate=0.85)
    info = turbo.encode_outer(v, data)
    weights = np.full(len(info), 20.0)
    for indices in soft_outer.block_positions(v.blocks):
        for index in indices[:count]:
            offset = 8 * int(index)
            info[offset] ^= 1
            weights[offset] = 0.01
        if not per_block:
            break
    return v, data, info, (1.0 - 2.0 * info) * weights


@pytest.mark.parametrize("count", [0, 1, 2, 3, 4])
def test_nested_erasures_recover(count: int) -> None:
    v, data, info, llr = _damage(count, per_block=True)
    assert soft_outer.decode(v, info, llr) == data


def test_two_errors_expose_frozen_acceptance_limit() -> None:
    v, data, info, llr = _damage(2)
    assert turbo.decode_outer(v, info) is None
    assert soft_outer.decode(v, info, llr) == data


def test_wrong_reliability_is_not_an_oracle() -> None:
    v, _, info, llr = _damage(8)
    # Eight wrong bytes exceed the four parity symbols even with erasures.
    assert soft_outer.decode(v, info, llr) is None


def test_tag_rejects_a_valid_rs_stream_with_bad_payload_tag() -> None:
    data = np.random.default_rng(90).bytes(128)
    v, _ = turbo.encode(data, 0.65)
    original = turbo.tag
    from unittest.mock import patch

    with patch.object(turbo, "tag", return_value=b"\x00" * 8):
        info = turbo.encode_outer(v, data)
    assert original(data) != b"\x00" * 8
    llr = (1.0 - 2.0 * info) * 20
    assert soft_outer.decode(v, info, llr) is None


def test_interleave_is_a_partition() -> None:
    indices = soft_outer.block_positions((248, 247, 247, 247))
    assert sorted(np.concatenate(indices).tolist()) == list(range(989))
    assert all(len(row) == n for row, n in zip(indices, (248, 247, 247, 247)))


def test_clean_image_preserves_baseline_trajectory() -> None:
    data = np.random.default_rng(5).bytes(128)
    v, grid = turbo.encode(data, 0.65)
    pitch = 4.0
    image = np.repeat(np.repeat(225.0 - 200.0 * grid, 4, axis=0),
                      4, axis=1)
    centers = (np.arange(v.S) + 0.5) * pitch
    old, new, _ = soft_outer.decode_pair(
        v, image, centers, centers, pitch, blur=0.7, rounds=4)
    frozen, _ = turbo.decode(
        v, image, centers, centers, pitch, blur=0.7, rounds=4)
    assert old == new == frozen == data


@pytest.mark.parametrize("budget", [0, -1])
def test_candidate_budget_is_positive(budget: int) -> None:
    v, _, info, llr = _damage(0)
    with pytest.raises(ValueError):
        soft_outer.decode(v, info, llr, max_combinations=budget)
