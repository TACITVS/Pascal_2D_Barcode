"""PB-COMPARE-TEST-2026-10-20-v1: source preservation and identical packets."""

from __future__ import annotations

import struct

import pytest

from compression_compare import candidates, choose, unpack_envelope


@pytest.mark.parametrize("data", [
    b"", bytes(range(256)) * 2, b"hello https://example.org/path\n" * 20,
    "Acentos: informação, correção, compressão.".encode(),
])
def test_every_available_representation_roundtrips(data: bytes) -> None:
    for representation in candidates(data):
        assert unpack_envelope(representation.envelope(len(data))) == data


def test_selection_counts_header_and_never_exceeds_raw() -> None:
    data = bytes(range(256)) * 3
    selected = choose(data)
    assert len(selected.envelope(len(data))) <= len(data) + 5


@pytest.mark.parametrize("packet", [
    b"", b"\x10\x00", b"\x00\x00\x00\x00\x00",
    b"\x1f\x00\x00\x00\x00", struct.pack(">BI", 0x10, 100) + b"short",
])
def test_invalid_or_inconsistent_envelopes_are_rejected(packet: bytes) -> None:
    with pytest.raises(ValueError):
        unpack_envelope(packet)
