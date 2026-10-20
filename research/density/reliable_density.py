"""PB-RELIABLE-2026-10-20-v2: registered noisy-image comparison.

This measures allocated physical area, not nominal module counts. Every
receiver gets exact grid geometry, the actual blur and common endpoints.
QR/Data Matrix use ZXing on native pixels, centre samples and a full-grid
Gaussian LMMSE deconvolution, with a bounded Chase hard-decision list.
No decoder receives the expected payload or expected data modules.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import segno
import zxingcpp

try:
    from . import shaped_gray, soft_outer, turbo
    from .hierarchical_probe import pixel_profile
except ImportError:
    import shaped_gray
    import soft_outer
    import turbo
    from hierarchical_probe import pixel_profile

from capacity import Channel, bilinear, render


@dataclass(frozen=True)
class Symbol:
    grid: np.ndarray
    quiet: int
    version: turbo.Version | shaped_gray.Version | None = None

    @property
    def allocated_modules(self) -> int:
        height, width = self.grid.shape
        return (height + 2 * self.quiet) * (width + 2 * self.quiet)


def encode(profile: str, data: bytes) -> Symbol:
    family, setting = profile.split("/")
    match family:
        case "turbo":
            v, grid = turbo.encode(data, rate=float(setting))
            return Symbol(grid, 4, v)
        case "shaped":
            coarse, fine, weight = map(float, setting.split("+"))
            v, grid = shaped_gray.encode(data, (coarse, fine), weight)
            return Symbol(grid, 4, v)
        case "qr":
            qr = segno.make_qr(
                data + turbo.tag(data), error=setting, mode="byte",
                encoding="iso-8859-1", boost_error=False)
            return Symbol(np.asarray(qr.matrix, dtype=np.uint8), 4)
        case "datamatrix":
            barcode = zxingcpp.create_barcode(
                data + turbo.tag(data), zxingcpp.BarcodeFormat.DataMatrix,
                eci="0")
            pixels = np.asarray(
                barcode.to_image(scale=1, add_quiet_zones=False))
            return Symbol((pixels < 128).astype(np.uint8), 1)
        case _:
            raise ValueError("unsupported profile")


def verified_wire(wire: bytes) -> bytes | None:
    if len(wire) < 8 or turbo.tag(wire[:-8]) != wire[-8:]:
        return None
    return wire[:-8]


def read_zxing(
    pixels: np.ndarray, format_id: Any, pure: bool = False,
) -> bytes | None:
    result = zxingcpp.read_barcode(
        np.clip(pixels, 0, 255).astype(np.uint8), formats=format_id,
        is_pure=pure)
    return None if result is None else verified_wire(bytes(result.bytes))


def synthetic_read(
    grid: np.ndarray, format_id: Any,
) -> bytes | None:
    # Receiver padding adds no captured information. It helps the standard
    # parser read a supplied grid. The physical quiet zone is still counted.
    padded = np.pad(grid.astype(np.float32), 4)
    pixels = np.repeat(np.repeat(225 - 200 * padded, 4, axis=0),
                       4, axis=1)
    return read_zxing(pixels, format_id, pure=True)


def deconvolved_llr(
    image: np.ndarray, cx: np.ndarray, cy: np.ndarray,
    pitch: float, blur: float, noise: float,
) -> np.ndarray:
    """Full-grid LMMSE front end, including unknown finder/frame cells.

    All symbol modules have the same independent Bernoulli(1/2) prior.
    Quiet-zone intensity is known white; no payload or pilot truth enters.
    """
    height, width = image.shape
    ax = pixel_profile(
        pitch, blur, np.arange(width)[:, None] + 0.5 - cx[None, :])
    ay = pixel_profile(
        pitch, blur, np.arange(height)[:, None] + 0.5 - cy[None, :])
    ux, sx, vxh = np.linalg.svd(ax, full_matrices=False)
    uy, sy, vyh = np.linalg.svd(ay, full_matrices=False)
    vx, vy = vxh.T, vyh.T
    singular = sy[:, None] * sx[None, :]
    power = singular ** 2
    residual = ((225 - image.astype(float)) / 200
                - ay @ np.full((len(cy), len(cx)), 0.5) @ ax.T)
    denominator = (noise / 200) ** 2 + 0.25 * power
    modes = uy.T @ residual @ ux
    score = vy @ (singular * modes / denominator) @ vx.T
    diagonal = (vy ** 2) @ (power / denominator) @ (vx ** 2).T
    return np.clip(
        -score / np.maximum(1 - 0.25 * diagonal, 1e-4), -40, 40)


def standard_decode(
    profile: str, symbol: Symbol, image: np.ndarray,
    cx: np.ndarray, cy: np.ndarray, pitch: float, blur: float,
    noise: float,
) -> tuple[bytes | None, str]:
    format_id = (zxingcpp.BarcodeFormat.QRCode if profile.startswith("qr/")
                 else zxingcpp.BarcodeFormat.DataMatrix)
    for pure in (False, True):
        result = read_zxing(image, format_id, pure=pure)
        if result is not None:
            return result, "native_pure" if pure else "native"
    x, y = np.meshgrid(cx, cy)
    samples = bilinear(image, x, y)
    _, thresholded = cv2.threshold(
        np.clip(samples, 0, 255).astype(np.uint8), 0, 255,
        cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    grids = [samples < 125, thresholded == 0]
    for name, grid in zip(("centres_fixed", "centres_otsu"), grids):
        result = synthetic_read(grid, format_id)
        if result is not None:
            return result, name
    llr = deconvolved_llr(image, cx, cy, pitch, blur, noise)
    grid = llr < 0
    uncertain = np.argsort(np.abs(llr).ravel(), kind="stable")[:3]
    for pattern in range(8):
        hypothesis = grid.copy()
        for bit, location in enumerate(uncertain):
            if pattern & (1 << bit):
                hypothesis.flat[location] ^= True
        result = synthetic_read(hypothesis, format_id)
        if result is not None:
            return result, "lmmse_chase_" + str(pattern)
    return None, "failed"


def source_hashes() -> dict[str, str]:
    return {
        name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
        for name in ("reliable_density.py", "soft_outer.py", "shaped_gray.py",
                     "gray.py", "turbo.py")
    }


def run(
    payload: int, widths: list[float], profiles: list[str],
    trials: int, seed: int, out: Path, rounds: int = 16,
    blur: float = 0.7, noise: float = 6.0, jpeg: int = 75,
    jitter: float = 0.25,
) -> dict[str, Any]:
    """Checkpoint each frame; exact byte comparison happens after decoding."""
    config = {
        "experiment": "PB-RELIABLE-2026-10-20-v2",
        "payload_bytes": payload, "widths": widths, "profiles": profiles,
        "trials": trials, "seed": seed, "rounds": rounds,
        "blur": blur, "noise": noise, "jpeg": jpeg, "blur_jitter": jitter,
        "source_sha256": source_hashes(),
        "geometry": "oracle_registered_axis_aligned",
        "blur_supplied": "actual_oracle", "endpoints": [25, 225],
        "common_integrity_bytes": 8, "compression": "common_raw_random_bytes",
        "area_includes_native_quiet_zones": True,
        "photographic_validation": False,
        "python": platform.python_version(),
        "packages": {name: importlib.metadata.version(name) for name in
                     ("numpy", "scipy", "opencv-python-headless",
                      "segno", "zxing-cpp")},
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    config_path = out.with_suffix(".config.json")
    checkpoint = out.with_suffix(".jsonl")
    if config_path.exists():
        if json.loads(config_path.read_text()) != config:
            raise ValueError("checkpoint configuration/source mismatch")
    else:
        config_path.write_text(json.dumps(config, indent=2) + "\n")
    rows = ([json.loads(line) for line in checkpoint.read_text().splitlines()
             if line.strip()] if checkpoint.exists() else [])
    completed = {(r["trial"], r["allocated_width"], r["profile"])
                 for r in rows}
    total = trials * len(widths) * len(profiles)
    start = time.perf_counter()
    initial = len(rows)
    with checkpoint.open("a") as log:
        for trial in range(trials):
            data = np.random.default_rng(
                np.random.SeedSequence([seed, payload, trial, 1])).bytes(payload)
            for profile in profiles:
                symbol = encode(profile, data)
                for width in widths:
                    if (trial, width, profile) in completed:
                        continue
                    pitch = width / np.sqrt(symbol.allocated_modules)
                    channel = Channel(
                        pitch=pitch, blur=blur, noise=noise, jpeg=jpeg,
                        blur_jitter=jitter)
                    rng = np.random.default_rng(np.random.SeedSequence(
                        [seed, payload, trial, int(round(width * 1000)), 2]))
                    image, all_cx, all_cy = render(
                        np.pad(symbol.grid, symbol.quiet), channel, rng)
                    actual_blur = float(render.last_blur)
                    quiet = symbol.quiet
                    cx, cy = all_cx[quiet:-quiet], all_cy[quiet:-quiet]
                    decoding_start = time.perf_counter()
                    if isinstance(symbol.version, shaped_gray.Version):
                        decoded, history = shaped_gray.decode(
                            symbol.version, image, cx, cy, pitch,
                            actual_blur, noise=noise, rounds=rounds)
                        results = {"gmd": decoded}
                        diagnostics: Any = history
                    elif symbol.version is not None:
                        old, new, history = soft_outer.decode_pair(
                            symbol.version, image, cx, cy, pitch,
                            actual_blur, noise=noise, rounds=rounds)
                        results = {"legacy": old, "gmd": new}
                        diagnostics = history
                    else:
                        decoded, method = standard_decode(
                            profile, symbol, image, cx, cy, pitch,
                            actual_blur, noise)
                        results = {"assisted": decoded}
                        diagnostics = method
                    row = {
                        "trial": trial, "profile": profile,
                        "allocated_width": width, "pitch": float(pitch),
                        "symbol_shape": list(symbol.grid.shape),
                        "quiet": quiet,
                        "module_area_including_quiet": symbol.allocated_modules,
                        "channel": asdict(channel), "actual_blur": actual_blur,
                        "source_sha256": hashlib.sha256(data).hexdigest(),
                        "decode_seconds": time.perf_counter() - decoding_start,
                        "exact": {key: result == data
                                  for key, result in results.items()},
                        "accepted_wrong": {
                            key: result is not None and result != data
                            for key, result in results.items()},
                        "diagnostics": diagnostics,
                    }
                    rows.append(row)
                    log.write(json.dumps(row, separators=(",", ":")) + "\n")
                    log.flush()
                    if (len(rows) - initial) % 4 == 0 or len(rows) == total:
                        elapsed = time.perf_counter() - start
                        eta = elapsed * (total - len(rows)) / (len(rows) - initial)
                        print(
                            f"[{len(rows)}/{total}] payload={payload} "
                            f"elapsed={elapsed:.1f}s ETA={eta:.1f}s "
                            f"{profile} width={width} exact={row['exact']}",
                            flush=True)
    aggregates = []
    for profile in profiles:
        for width in widths:
            selected = [r for r in rows if r["profile"] == profile
                        and r["allocated_width"] == width]
            for receiver in selected[0]["exact"]:
                aggregates.append({
                    "profile": profile, "receiver": receiver,
                    "allocated_width": width,
                    "trials": len(selected),
                    "successes": sum(r["exact"][receiver] for r in selected),
                    "accepted_wrong": sum(r["accepted_wrong"][receiver]
                                          for r in selected),
                    "mean_decode_seconds": float(np.mean(
                        [r["decode_seconds"] for r in selected])),
                    "symbol_shape": selected[0]["symbol_shape"],
                    "quiet": selected[0]["quiet"],
                })
    document = {"config": config, "results": aggregates}
    out.write_text(json.dumps(document, indent=2) + "\n")
    print("RELIABILITY_DISCOVERY_JSON "
          + json.dumps(document, separators=(",", ":")), flush=True)
    return document


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", type=int, required=True)
    parser.add_argument("--widths", default="48,56,64,72,80,96")
    parser.add_argument("--profiles", default=(
        "turbo/0.55,turbo/0.65,turbo/0.85,qr/L,qr/M,datamatrix/ECC200"))
    parser.add_argument("--trials", type=int, default=16)
    parser.add_argument("--seed", type=int, default=20261020)
    parser.add_argument("--rounds", type=int, default=16)
    parser.add_argument("--blur", type=float, default=0.7)
    parser.add_argument("--noise", type=float, default=6)
    parser.add_argument("--jpeg", type=int, default=75)
    parser.add_argument("--jitter", type=float, default=0.25)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    run(
        args.payload, [float(value) for value in args.widths.split(",")],
        args.profiles.split(","), args.trials, args.seed, args.out,
        args.rounds, args.blur, args.noise, args.jpeg, args.jitter)


if __name__ == "__main__":
    main()
