"""Confidence accounting applies to the whole predeclared family."""

from __future__ import annotations

from research.density import validate_reliable


def test_family_includes_paired_receivers() -> None:
    groups = [
        {"profile": "turbo/0.55", "widths": [64, 66]},
        {"profile": "qr/L", "widths": [72, 80]},
        {"profile": "shaped/0.85+0.55+0.25", "widths": [128]},
    ]
    assert validate_reliable.family_size(groups) == 7


def test_confidence_is_simultaneous() -> None:
    low, high = validate_reliable.interval(1024, 1024, 0.05, 48)
    assert abs(low - (0.05 / 96) ** (1 / 1024)) < 1e-12
    assert low > 0.99 and high == 1.0
    one_low, _ = validate_reliable.interval(1023, 1024, 0.05, 48)
    assert one_low > 0.99
    two_low, _ = validate_reliable.interval(1022, 1024, 0.05, 48)
    assert two_low < 0.99


def test_zero_successes_remain_bounded() -> None:
    low, high = validate_reliable.interval(0, 1024, 0.05, 48)
    assert low == 0
    assert 0 < high < 0.01
