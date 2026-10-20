"""Check independent standard writers, tag rejection and clean assistance."""

from __future__ import annotations

import numpy as np
import pytest

from research.density import reliable_density as experiment


@pytest.mark.parametrize("profile", ["qr/L", "qr/M", "datamatrix/ECC200"])
@pytest.mark.parametrize("length", [128, 800])
def test_standard_symbol_clean_roundtrip(profile: str, length: int) -> None:
    data = np.random.default_rng(200 + length).bytes(length)
    symbol = experiment.encode(profile, data)
    modules = np.pad(symbol.grid, symbol.quiet)
    image = np.repeat(np.repeat(225.0 - 200.0 * modules, 4, axis=0),
                      4, axis=1)
    cx = ((np.arange(modules.shape[1]) + 0.5) * 4)[
        symbol.quiet:-symbol.quiet]
    cy = ((np.arange(modules.shape[0]) + 0.5) * 4)[
        symbol.quiet:-symbol.quiet]
    decoded, _ = experiment.standard_decode(
        profile, symbol, image, cx, cy, 4.0, 0.7, 6.0)
    assert decoded == data


def test_wire_integrity_rejects_change() -> None:
    data = b"not an expected-payload decoding hint"
    wire = data + experiment.turbo.tag(data)
    assert experiment.verified_wire(wire) == data
    assert experiment.verified_wire(bytes([wire[0] ^ 1]) + wire[1:]) is None


def test_deconvolution_has_correct_signs() -> None:
    grid = np.random.default_rng(31).integers(0, 2, (24, 24))
    image, cx, cy = experiment.render(
        np.pad(grid, 4), experiment.Channel(3.0, 0.7, 0.0, 0),
        np.random.default_rng(44))
    llr = experiment.deconvolved_llr(
        image, cx[4:-4], cy[4:-4], 3.0, 0.7, 6.0)
    assert np.array_equal(llr < 0, grid)
