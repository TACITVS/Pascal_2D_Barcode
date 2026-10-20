"""Image-to-byte tests for nonuniform constellations and unequal protection."""

from __future__ import annotations

import numpy as np
import pytest

from research.density import shaped_gray, turbo
from capacity import Channel, render


@pytest.mark.parametrize("fine_weight", [0.18, 0.25, 1 / 3])
@pytest.mark.parametrize("length", [128, 800])
def test_image_roundtrip(fine_weight: float, length: int) -> None:
    data = np.random.default_rng(166 + length).bytes(length)
    v, grid = shaped_gray.encode(data, (0.85, 0.55), fine_weight)
    levels = np.unique(np.round(grid[2:-2, 2:-2], 6))
    assert np.allclose(levels, [0, fine_weight, 1 - fine_weight, 1])
    image, cx, cy = render(
        np.pad(grid, 4), Channel(4.0, 0.7, 0.0, 0),
        np.random.default_rng(984))
    result, _ = shaped_gray.decode(
        v, image, cx[4:-4], cy[4:-4], 4.0, blur=0.7, rounds=8)
    assert result == data
    info = turbo.encode_outer(v, data)
    assert turbo.decode_outer(v, info) == data


@pytest.mark.parametrize("weight", [0, 0.5, 1])
def test_invalid_constellation(weight: float) -> None:
    with pytest.raises(ValueError):
        shaped_gray.encode(b"example", fine_weight=weight)
