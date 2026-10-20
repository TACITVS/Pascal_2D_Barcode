"""Public pilot priors must match independent encoders across payloads."""

from __future__ import annotations

import numpy as np
import pytest

from research.density import reliable_density, standard_assist


@pytest.mark.parametrize("profile", [
    "qr/L", "qr/M", "qr/Q", "qr/H", "datamatrix/ECC200",
])
@pytest.mark.parametrize("length", [128, 800])
def test_pilots_are_payload_independent(profile: str, length: int) -> None:
    for seed in (81, 345):
        data = np.random.default_rng(seed).bytes(length)
        symbol = reliable_density.encode(profile, data)
        pattern = standard_assist.known_pattern(profile, symbol.grid.shape)
        known = np.isfinite(pattern)
        assert known.any()
        assert not known.all()
        assert np.array_equal(pattern[known], symbol.grid[known])


def test_conditioned_posterior_signs() -> None:
    data = np.random.default_rng(17).bytes(128)
    symbol = reliable_density.encode("qr/L", data)
    image, all_cx, all_cy = reliable_density.render(
        np.pad(symbol.grid, 4),
        reliable_density.Channel(3.0, 0.7, 0, 0),
        np.random.default_rng(2))
    pattern = standard_assist.known_pattern("qr/L", symbol.grid.shape)
    score = standard_assist.conditioned_scores(
        image, all_cx[4:-4], all_cy[4:-4], 3.0, 0.7, 6.0, pattern)
    unknown = ~np.isfinite(pattern)
    assert np.array_equal((score < 0)[unknown], symbol.grid[unknown])
