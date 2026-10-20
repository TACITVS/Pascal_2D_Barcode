"""PB-COMPARE-2026-10-20-v2: identical compression opportunities for 2D codes.

This is an encoded-area and clean-roundtrip comparison, not a camera
reliability benchmark. Every format gets the same five-byte application
envelope and eight-byte integrity allowance. No external dictionary is used.
"""

from __future__ import annotations

import argparse
import bz2
import hashlib
import importlib.metadata
import io
import json
import lzma
import platform
import struct
import time
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import brotli
import numpy as np
from PIL import Image
import segno
import zstandard
import zxingcpp

try:
    from .benchmark_density import make_symbol, turbo
    from .analyze_screen_photo import decode_crop
    from .screen_targets import payload_bytes
except ImportError:
    from benchmark_density import make_symbol, turbo
    from analyze_screen_photo import decode_crop
    from screen_targets import payload_bytes

from pascal_mds.codec import pack_text, unpack_text


@dataclass(frozen=True)
class Sample:
    name: str
    data: bytes


@dataclass(frozen=True)
class Representation:
    mode: int
    name: str
    body: bytes

    def envelope(self, original_length: int) -> bytes:
        # Version 1 occupies the high nibble; codec occupies the low nibble.
        return struct.pack(">BI", 0x10 | self.mode, original_length) + self.body


@dataclass(frozen=True)
class Encoded:
    grid: np.ndarray
    quiet: int


def candidates(data: bytes) -> list[Representation]:
    return [
        Representation(0, "raw", data),
        Representation(1, "compact_text", pack_text(data)),
        Representation(2, "zlib_deflate_9", zlib.compress(data, 9)),
        Representation(3, "bzip2_9", bz2.compress(data, 9)),
        Representation(4, "xz_lzma_9", lzma.compress(data, preset=9)),
        Representation(5, "brotli_11", brotli.compress(data, quality=11)),
        Representation(6, "zstd_19", zstandard.ZstdCompressor(level=19).compress(data)),
    ]


def unpack_envelope(packet: bytes) -> bytes:
    if len(packet) < 5:
        raise ValueError("truncated compression header")
    flags, length = struct.unpack(">BI", packet[:5])
    if flags >> 4 != 1 or length > 1_000_000:
        raise ValueError("unsupported envelope or excessive decoded length")
    body = packet[5:]
    match flags & 15:
        case 0:
            data = body
        case 1:
            data = unpack_text(body)
        case 2:
            data = zlib.decompress(body)
        case 3:
            data = bz2.decompress(body)
        case 4:
            data = lzma.decompress(body)
        case 5:
            data = brotli.decompress(body)
        case 6:
            data = zstandard.ZstdDecompressor().decompress(body, max_output_size=length)
        case _:
            raise ValueError("unknown compression method")
    if len(data) != length:
        raise ValueError("decoded length mismatch")
    return data


def choose(data: bytes) -> Representation:
    options = candidates(data)
    return min(options, key=lambda item: (len(item.envelope(len(data))), item.mode))


def samples() -> list[Sample]:
    source_text = Path(__file__).with_name("README.md").read_bytes()[:1200]
    records = [
        {"device": "sensor-01", "time_s": 60 * i,
         "temperature_c": round(23.0 + i * 0.13, 2),
         "humidity_pct": 54 + i % 3, "status": "normal"}
        for i in range(8)
    ]
    card = (
        "BEGIN:VCARD\nVERSION:3.0\nFN:Example Person\n"
        "ORG:Example Workshop\nTEL:+55-34-0000-0000\n"
        "EMAIL:person@example.org\nURL:https://example.org/contact\n"
        "ADR:;;Example Street 123;Example City;;;Brazil\nEND:VCARD\n"
    ).encode()
    image = Image.frombytes("L", (16, 16), payload_bytes(17, 256))
    stream = io.BytesIO()
    image.save(stream, format="PNG", optimize=False)
    return [
        Sample("random_128", payload_bytes(1, 128)),
        Sample("actual_B2_random_800", payload_bytes(1, 800)),
        Sample("study_text_1200", source_text),
        Sample("telemetry_json", json.dumps(records, separators=(",", ":")).encode()),
        Sample("contact_vcard", card),
        Sample("already_compressed_png", stream.getvalue()),
    ]


def encode_profile(profile: str, packet: bytes) -> Encoded:
    family, setting = profile.split("/")
    match family:
        case "turbo" | "dense":
            _, grid, quiet = make_symbol(profile, packet)
            return Encoded(grid, quiet)
        case "qr":
            wire = packet + turbo.tag(packet)
            qr = segno.make_qr(wire, error=setting, mode="byte",
                               encoding="iso-8859-1", boost_error=False)
            return Encoded(np.asarray(qr.matrix, dtype=np.uint8), 4)
        case "datamatrix":
            wire = packet + turbo.tag(packet)
            options = {} if setting == "binaryECI" else {"eci": "0"}
            barcode = zxingcpp.create_barcode(
                wire, zxingcpp.BarcodeFormat.DataMatrix, **options)
            image = np.asarray(barcode.to_image(scale=1, add_quiet_zones=False))
            return Encoded((image < 128).astype(np.uint8), 1)
        case _:
            raise ValueError("unknown format")


def decode_clean(profile: str, encoded: Encoded) -> bytes | None:
    modules = np.pad(encoded.grid, encoded.quiet)
    image = np.repeat(np.repeat(225 - 200 * modules.astype(np.float32),
                                4, axis=0), 4, axis=1)
    family, _ = profile.split("/")
    match family:
        case "turbo" | "dense":
            packet, _ = decode_crop(
                image, 4.0, {"S": encoded.grid.shape[0],
                             "quiet": encoded.quiet, "profile": profile})
            return packet
        case "qr" | "datamatrix":
            format_id = (zxingcpp.BarcodeFormat.QRCode if family == "qr"
                         else zxingcpp.BarcodeFormat.DataMatrix)
            decoded = zxingcpp.read_barcode(
                np.clip(image, 0, 255).astype(np.uint8), formats=format_id)
            if decoded is None:
                return None
            wire = bytes(decoded.bytes)
            if len(wire) < 8 or turbo.tag(wire[:-8]) != wire[-8:]:
                return None
            return wire[:-8]
        case _:
            raise ValueError("unknown format")


def markdown_report(document: dict[str, Any]) -> str:
    lines = [
        "# PB-COMPARE-01: equal-compression barcode comparison", "",
        "All sizes count the five-byte compression envelope, the common",
        "eight-byte integrity allowance, each format's native framing/ECC",
        "and its quiet zone. Area is measured in square modules at equal",
        "module pitch. No photographic reliability is established.", "",
        "| Input | Source bytes | Selected method | Envelope bytes | Turbo .85 | Data Matrix | QR-L | QR-M |",
        "|---|---:|---|---:|---:|---:|---:|---:|",
    ]
    rows = document["rows"]
    for sample in document["samples"]:
        selected = [r for r in rows if r["sample"] == sample["name"]
                    and r["representation"] == "adaptive"]
        by_profile = {r["profile"]: r for r in selected}

        def dimensions(profile: str) -> str:
            row = by_profile[profile]
            if not row["fits"]:
                return "Does not fit"
            value = f'{row["width_with_quiet"]}x{row["height_with_quiet"]}'
            return value if row["clean_exact"] else value + " (read failed)"

        lines.append(
            f'| {sample["name"]} | {sample["source_bytes"]} | '
            f'{sample["selected_method"]} | {sample["selected_envelope_bytes"]} | '
            f'{dimensions("turbo/0.85")} | {dimensions("datamatrix/ECC200")} | '
            f'{dimensions("qr/L")} | {dimensions("qr/M")} |')
    lines += [
        "", "The JSON contains every raw/adaptive result for Turbo rates .55/.65/.85,",
        "Dense-A, QR L/M/Q/H, and Data Matrix ECC200. Different ECC profiles do",
        "Data Matrix ECC200 uses ECI 0 to suppress an optional binary-ECI identifier;",
        "the default binary-ECI writer is also recorded as a sensitivity control.",
        "not imply equal robustness. The Data Matrix encoder may choose its",
        "supported shape; dimensions and area are both recorded.",
        "", "The common application envelope makes this a binary-payload comparison;",
        "it does not optimize each format's native text modes. No Base64 is used.",
        "The original source bytes and logical encoded packet hashes are identical",
        "across formats. Compression selection includes headers and uses no",
        "external dictionary. Every accepted read is decompressed and compared",
        "byte-for-byte with its original source.",
        "", "Our clean reader is supplied exact geometry; the standard readers",
        "locate their clean symbols. This is not a camera read-rate comparison.",
        "External photographic fixture markers are absent from every clean test;",
        "they must be included equally in a future assisted photo comparison.",
        "", "The original frozen density study and physical reference HTML are unchanged.",
    ]
    return "\n".join(lines) + "\n"


def run(out: Path) -> dict[str, Any]:
    corpus = samples()
    profiles = ["turbo/0.55", "turbo/0.65", "turbo/0.85", "dense/A",
                "qr/L", "qr/M", "qr/Q", "qr/H", "datamatrix/ECC200",
                "datamatrix/binaryECI"]
    rows: list[dict[str, Any]] = []
    descriptions: list[dict[str, Any]] = []
    started = time.perf_counter()
    total = len(corpus) * 2 * len(profiles)
    done = 0
    for sample in corpus:
        options = candidates(sample.data)
        for option in options:
            assert unpack_envelope(option.envelope(len(sample.data))) == sample.data
        selected = min(options, key=lambda item: (len(item.envelope(len(sample.data))), item.mode))
        descriptions.append({
            "name": sample.name, "source_bytes": len(sample.data),
            "source_sha256": hashlib.sha256(sample.data).hexdigest(),
            "selected_method": selected.name,
            "selected_envelope_bytes": len(selected.envelope(len(sample.data))),
            "candidate_envelope_bytes": {o.name: len(o.envelope(len(sample.data))) for o in options},
        })
        representations = [("raw", options[0]), ("adaptive", selected)]
        for label, option in representations:
            packet = option.envelope(len(sample.data))
            packet_hash = hashlib.sha256(packet + turbo.tag(packet)).hexdigest()
            for profile in profiles:
                row: dict[str, Any] = {
                    "sample": sample.name, "representation": label,
                    "profile": profile, "source_bytes": len(sample.data),
                    "method": option.name, "envelope_bytes": len(packet),
                    "logical_wire_bytes_including_tag": len(packet) + 8,
                    "logical_wire_sha256": packet_hash,
                    "fits": False, "clean_exact": False, "accepted_wrong": False,
                }
                try:
                    encoded = encode_profile(profile, packet)
                except ValueError as error:
                    row["not_fit_reason"] = str(error)
                else:
                    height, width = encoded.grid.shape
                    height_q, width_q = height + 2 * encoded.quiet, width + 2 * encoded.quiet
                    decoded = decode_clean(profile, encoded)
                    original = unpack_envelope(decoded) if decoded is not None else None
                    row.update({
                        "fits": True, "symbol_width": int(width),
                        "symbol_height": int(height), "quiet": encoded.quiet,
                        "width_with_quiet": int(width_q), "height_with_quiet": int(height_q),
                        "area_modules": int(height_q * width_q),
                        "source_bits_per_module_area": 8 * len(sample.data) / (height_q * width_q),
                        "clean_exact": original == sample.data,
                        "accepted_wrong": original is not None and original != sample.data,
                    })
                rows.append(row)
                done += 1
                elapsed = time.perf_counter() - started
                eta = elapsed * (total - done) / done
                print(f'[{done}/{total}] {sample.name} {label} {profile} '
                      f'fits={row["fits"]} exact={row["clean_exact"]} '
                      f'elapsed={elapsed:.1f}s ETA={eta:.1f}s', flush=True)
    for sample in corpus:
        for label in ("raw", "adaptive"):
            comparable = [r for r in rows if r["sample"] == sample.name
                          and r["representation"] == label]
            assert len({r["logical_wire_sha256"] for r in comparable}) == 1
    document = {
        "experiment": "PB-COMPARE-2026-10-20-v2",
        "kind": "nominal_encoded_area_and_clean_roundtrip",
        "compression_header_bytes": 5, "common_integrity_bytes": 8,
        "external_dictionaries": False, "photographic_validation": False,
        "clean_pixel_pitch": 4, "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "python": platform.python_version(), "zlib": zlib.ZLIB_RUNTIME_VERSION,
        "packages": {name: importlib.metadata.version(name) for name in
                     ("numpy", "Pillow", "segno", "zxing-cpp", "brotli", "zstandard")},
        "samples": descriptions, "rows": rows,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=2) + "\n")
    out.with_suffix(".md").write_text(markdown_report(document))
    print("COMPRESSION_REPORT_JSON " + json.dumps(document, separators=(",", ":")), flush=True)
    print(markdown_report(document), flush=True)
    failures = [r for r in rows if r["fits"] and not r["clean_exact"]]
    if failures:
        raise RuntimeError(f"{len(failures)} fitting symbols did not roundtrip exactly")
    return document


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("compression-comparison.json"))
    args = parser.parse_args()
    run(args.out)


if __name__ == "__main__":
    main()
