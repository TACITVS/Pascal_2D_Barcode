"""Image-to-byte tests for nonuniform constellations and unequal protection."""

from __future__ import annotations

import numpy as np
import pytest

from research.density import shaped_gray, turbo


@pytest.mark.parametrize("fine_weight", [0.18, 0.25, 1 / 3])
@pytest.mark.parametrize("length", [128, 800])
def test_image_roundtrip(fine_weight: float, length: int) -> None:
    data = np.random.default_rng(166 + length).bytes(length)
    v, grid = shaped_gray.encode(data, (0.85, 0.55), fine_weight)
    levels = np.unique(np.round(grid[2:-2, 2:-2], 6))
    assert np.allclose(levels, [0, fine_weight, 1 - fine_weight, 1])
    image = np.repeat(np.repeat(225.0 - 200.0 * grid, 4, axis=0),
                      4, axis=1)
    centers = (np.arange(v.S) + 0.5) * 4
    result, _ = shaped_gray.decode(
        v, image, centers, centers, 4.0, blur=0.7, rounds=8)
    assert result == data
    info = turbo.encode_outer(v, data)
    assert turbo.decode_outer(v, info) == data


@pytest.mark.parametrize("weight", [0, 0.5, 1])
def test_invalid_constellation(weight: float) -> None:
    with pytest.raises(ValueError):
        shaped_gray.encode(b"example", fine_weight=weight)
