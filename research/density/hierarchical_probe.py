"""PM257-DENSITY-PROBE-2026-10-19: native-pixel hierarchical modulation probe.

Research only: geometry and blur are supplied, not estimated from a photo.
Three independent bits map to an odd-weight 2x2 black/white tile. The first
bit controls weight 1 vs 3; the other two locate the minority module.
Likelihoods marginalize the central tile's undecoded bits, with a Gaussian
moment approximation to other tiles. Every frame is rendered independently.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.special import logsumexp, ndtr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from capacity import Channel, render  # noqa: E402


@dataclass(frozen=True)
class Observation:
    values: np.ndarray
    cx: np.ndarray
    cy: np.ndarray
    pitch: float
    blur: float
    noise: float


def patterns() -> tuple[np.ndarray, np.ndarray]:
    labels = np.array([[b, r, c] for b in range(2) for r in range(2)
                       for c in range(2)], dtype=np.uint8)
    out = np.repeat(labels[:, :1], 4, axis=1).astype(float)
    for j, (b, r, c) in enumerate(labels):
        out[j, 2 * r + c] = 1 - int(b)
    return labels, out


def modulate(bits: np.ndarray) -> np.ndarray:
    modules = np.repeat(np.repeat(bits[0], 2, axis=0), 2, axis=1)
    rr, cc = np.indices(bits.shape[1:])
    modules[2 * rr + bits[1], 2 * cc + bits[2]] ^= 1
    return modules


def pixel_profile(pitch: float, blur: float, distance: np.ndarray) -> np.ndarray:
    """Exact box-module * Gaussian * unit sensor-pixel response in 1-D."""
    def primitive(x: np.ndarray) -> np.ndarray:
        z = x / blur
        return x * ndtr(z) + blur * np.exp(-0.5 * z * z) / np.sqrt(2 * np.pi)

    a, b = pitch / 2, 0.5
    return (primitive(distance + a + b) - primitive(distance - a + b)
            - primitive(distance + a - b) + primitive(distance - a - b))


def tile_moments(bits: np.ndarray, stage: int) -> tuple[np.ndarray, np.ndarray]:
    side = bits.shape[1]
    mean = np.full((side, side, 4), 0.5)
    match stage:
        case 0:
            covariance = np.eye(4) / 4
        case 1:
            mean[:] = (0.25 + 0.5 * bits[0])[..., None]
            covariance = np.eye(4) / 4 - np.ones((4, 4)) / 16
        case 2:
            mean[:] = bits[0, ..., None]
            for r in range(2):
                sel = bits[1] == r
                mean[sel, 2 * r:2 * r + 2] = 0.5
            # Average of the two possible known-row conditional covariances.
            covariance = np.kron(np.eye(2), np.array([[1, -1], [-1, 1]])) / 8
        case _:
            raise ValueError("stage must be 0, 1 or 2")
    return mean, covariance


def llrs(ob: Observation, bits: np.ndarray, stage: int, margin: int = 4) -> tuple[np.ndarray, np.ndarray]:
    labels, alphabet = patterns()
    means, covariance = tile_moments(bits, stage)
    side = bits.shape[1]
    rr, cc = np.meshgrid(np.arange(margin, side - margin),
                         np.arange(margin, side - margin), indexing="ij")
    rows, cols = rr.ravel(), cc.ravel()
    output = np.empty(len(rows))
    # A native 7x7 sensor-pixel patch, never 49 interpolated observations.
    sy, sx = np.meshgrid(np.arange(-3, 4), np.arange(-3, 4), indexing="ij")
    sy, sx = sy.ravel(), sx.ravel()
    offsets = [(r, c) for r in range(-3, 4) for c in range(-3, 4)]
    cache: dict[tuple[float, float], tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = {}
    for j, (r, c) in enumerate(zip(rows, cols)):
        centre_x = ob.cx[2 * c] + ob.pitch / 2
        centre_y = ob.cy[2 * r] + ob.pitch / 2
        ix, iy = int(round(centre_x - 0.5)), int(round(centre_y - 0.5))
        dx, dy = ix + 0.5 - centre_x, iy + 0.5 - centre_y
        key = round(dx, 5), round(dy, 5)
        cached = cache.get(key)
        if cached is None:
            response = []
            for dr, dc in offsets:
                cell = []
                for mr, mc in [(0, 0), (0, 1), (1, 0), (1, 1)]:
                    px = dx + sx - (2 * dc + mc - 0.5) * ob.pitch
                    py = dy + sy - (2 * dr + mr - 0.5) * ob.pitch
                    cell.append(pixel_profile(ob.pitch, ob.blur, px)
                                * pixel_profile(ob.pitch, ob.blur, py))
                response.append(cell)
            response = np.asarray(response)
            central = offsets.index((0, 0))
            other = np.delete(response, central, axis=0)
            cov = (ob.noise / 200) ** 2 * np.eye(49)
            cov += np.einsum("tij,ik,tkl->jl", other, covariance, other)
            central_means = alphabet @ response[central]
            filtered = np.linalg.solve(cov, central_means.T).T
            bias = -0.5 * np.sum(central_means * filtered, axis=1)
            cached = response, filtered, bias, 0.5 * (1 - response.sum(axis=(0, 1)))
            cache[key] = cached
        response, filtered, bias, outside = cached
        neighbour_means = np.stack([means[r + dr, c + dc] for dr, dc in offsets])
        neighbour_means[offsets.index((0, 0))] = 0
        interference = np.einsum("ti,tij->j", neighbour_means, response) + outside
        observation = (225 - ob.values[iy + sy, ix + sx]) / 200 - interference
        scores = filtered @ observation + bias
        allowed = np.ones(len(labels), dtype=bool)
        for previous in range(stage):
            allowed &= labels[:, previous] == bits[previous, r, c]
        output[j] = (logsumexp(scores[allowed & (labels[:, stage] == 0)])
                     - logsumexp(scores[allowed & (labels[:, stage] == 1)]))
    return output, bits[stage, rows, cols]


def information(llr: np.ndarray, truth: np.ndarray, scale: float) -> float:
    signs = 1 - 2 * truth.astype(float)
    return float(1 - np.logaddexp(0, -scale * signs * llr).mean() / np.log(2))


def probe(pitch: float, blur: float, frames: int, side: int, seed: int) -> dict[str, object]:
    rng = np.random.default_rng(seed)
    measurements: list[list[tuple[np.ndarray, np.ndarray]]] = [[], [], []]
    start = time.perf_counter()
    for frame in range(frames):
        bits = rng.integers(0, 2, (3, side, side), dtype=np.uint8)
        channel = Channel(pitch, blur, 6.0, 75, 2, 0.25, 0.0)
        image, cx, cy = render(modulate(bits), channel, rng)
        observation = Observation(image, cx, cy, pitch, render.last_blur, 8.0)
        for stage in range(3):
            measurements[stage].append(llrs(observation, bits, stage))
        elapsed = time.perf_counter() - start
        print(f"pitch={pitch} blur={blur} [{frame + 1}/{frames}] elapsed={elapsed:.1f}s "
              f"ETA={elapsed * (frames - frame - 1) / (frame + 1):.1f}s", flush=True)
    scales, rates = [], []
    for stage in range(3):
        split = max(1, frames // 3)
        validation = measurements[stage][:split]
        test = measurements[stage][split:]
        scale = max([0.0625, 0.125, 0.25, 0.5, 1.0, 2.0],
                    key=lambda s: np.mean([information(a, b, s) for a, b in validation]))
        scales.append(scale)
        rates.append([information(a, b, scale) for a, b in test])
    means = [float(np.mean(x)) for x in rates]
    return {"pitch": pitch, "blur": blur, "frames": frames, "stage_scales": scales,
            "stage_information_estimates": means, "per_frame_information": rates,
            "density_estimate": sum(max(0, x) for x in means) / (4 * pitch * pitch),
            "limits": "supplied geometry and blur; previous stages supplied correctly; no frame or ECC overhead"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pitches", default="1.0,1.2,1.5")
    parser.add_argument("--blur", type=float, default=0.7)
    parser.add_argument("--frames", type=int, default=6)
    parser.add_argument("--side", type=int, default=20)
    parser.add_argument("--out", type=Path, default=Path("research/density/probe.json"))
    args = parser.parse_args()
    result = []
    for pitch in map(float, args.pitches.split(",")):
        row = probe(pitch, args.blur, args.frames, args.side, 20261019)
        result.append(row)
        args.out.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(row), flush=True)


if __name__ == "__main__":
    main()
