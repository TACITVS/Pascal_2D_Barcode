"""PM257-TURBO-2026-10-19: global optical-code research prototype.

A single interleaved IRA code protects the whole data region. A separable
native-pixel optical operator exchanges soft information with the LDPC
decoder. Geometry/blur are supplied in these registered-channel experiments.
This is neither a general photo reader nor a capacity-achieving proof.
"""

from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from scipy.special import expit
from scipy.sparse.linalg import LinearOperator, cg

sys.path[:0] = [str(Path(__file__).resolve().parents[1]),
                str(Path(__file__).resolve().parents[1] / "v2")]

import dense  # noqa: E402
from ldpc import Decoder, IRACode, encode as ldpc_encode  # noqa: E402
from pascal_mds.codec import _header  # noqa: E402

try:
    from .hierarchical_probe import pixel_profile
except ImportError:
    from hierarchical_probe import pixel_profile


@dataclass(frozen=True)
class Version:
    S: int
    rate: float
    info_bits: int
    blocks: tuple[int, ...]

    @property
    def capacity(self) -> int:
        room = sum(b - dense.RS_PARITY - 1 for b in self.blocks)
        return room - (1 if room - 1 <= 31 else 2) - 8


@lru_cache(maxsize=64)
def version(size: int, rate: float) -> Version:
    if size not in dense.SIZES or not 0.05 <= rate <= 0.95:
        raise ValueError("unsupported size or rate")
    count = (size - 4) ** 2
    k = int(count * rate)
    total = k // 8
    nb = max(1, -(-total // dense.RS_BLOCK))
    blocks = tuple(total // nb + (i < total % nb) for i in range(nb))
    return Version(size, rate, k, blocks)


@lru_cache(maxsize=64)
def code_and_mapping(size: int, rate: float) -> tuple[IRACode, np.ndarray, np.ndarray]:
    v = version(size, rate)
    count = (size - 4) ** 2
    code = dense.make_ira(v.info_bits, count - v.info_bits,
                          dense._seed("turbo-ira", size, round(rate * 100)))
    rng = np.random.default_rng(dense._seed("turbo-perm", size, round(rate * 100)))
    permutation = rng.permutation(count)
    mask = rng.integers(0, 2, count, dtype=np.uint8)
    return code, permutation, mask


def tag(data: bytes) -> bytes:
    return hashlib.blake2s(b"PM257-TURBO-v0\x00" + data, digest_size=8).digest()


def encode_outer(v: Version, data: bytes) -> np.ndarray:
    payload = data + tag(data)
    stream = list(_header(0, len(payload)) + payload)
    blocks = []
    for length in v.blocks:
        k = length - dense.RS_PARITY
        chunk, stream = stream[:k - 1], stream[k - 1:]
        blocks.append(dense._rs_block(chunk + [0] * (k - len(chunk)), dense.RS_PARITY))
    if stream:
        raise ValueError("payload does not fit")
    interleaved = [blocks[j][i] for i in range(max(v.blocks))
                   for j in range(len(blocks)) if i < len(blocks[j])]
    bits = np.unpackbits(np.array(interleaved, dtype=np.uint8))
    return np.pad(bits, (0, v.info_bits - len(bits)))


def decode_outer(v: Version, bits: np.ndarray) -> bytes | None:
    data = dense.decode_info_bits(v, bits)
    if data is None or len(data) < 8 or tag(data[:-8]) != data[-8:]:
        return None
    return data[:-8]


def encode(data: bytes, rate: float = 0.6, size: int | None = None) -> tuple[Version, np.ndarray]:
    for side in ([size] if size is not None else dense.SIZES):
        v = version(side, rate)
        if len(data) <= v.capacity:
            break
    else:
        raise ValueError("payload does not fit")
    code, permutation, mask = code_and_mapping(v.S, rate)
    word = ldpc_encode(code, encode_outer(v, data)) ^ mask
    data_region = np.zeros(code.n, dtype=np.uint8)
    data_region[permutation] = word
    grid = dense.frame_modules(v.S).astype(np.uint8)
    grid[2:-2, 2:-2] = data_region.reshape(v.S - 4, v.S - 4)
    return v, grid


class SoftIRA:
    """Same sum-product checks as the existing IRA decoder, with extrinsic output."""

    def __init__(self, code: IRACode) -> None:
        self.decoder = Decoder(code)
        d = self.decoder
        self.segment = np.repeat(np.arange(len(d.check_starts)),
                                 np.diff(np.r_[d.check_starts, len(d.r)]))

    def decode(self, channel: np.ndarray, iters: int = 40) -> tuple[np.ndarray, np.ndarray, bool]:
        d = self.decoder
        c, starts = d.c, d.check_starts
        v2c = channel[c].astype(float)
        total = channel.copy()
        for _ in range(iters):
            t = np.tanh(np.clip(v2c, -30, 30) / 2)
            t = np.where(np.abs(t) < 1e-12, 1e-12, t)
            logabs = np.log(np.abs(t))
            negative = t < 0
            logs = np.add.reduceat(logabs, starts)
            signs = np.add.reduceat(negative.astype(np.int64), starts)
            magnitude = np.exp(logs[self.segment] - logabs)
            sign = np.where((signs[self.segment] - negative) % 2, -1.0, 1.0)
            messages = 2 * np.arctanh(np.clip(sign * magnitude, -0.999999999, 0.999999999))
            total = channel.copy()
            np.add.at(total, c, messages)
            bits = (total < 0).astype(np.uint8)
            if not (np.add.reduceat(bits[c], starts) & 1).any():
                return bits, total - channel, True
            v2c = total[c] - messages
        return (total < 0).astype(np.uint8), total - channel, False


class NativeOperator:
    """Exact separable Gaussian-blur + pixel-integration linear model.

    Pixel noise is white in the model. JPEG and blur/geometry error break
    that assumption and are stress tests, not covered by a decoder proof.
    """

    def __init__(self, image: np.ndarray, grid: np.ndarray, cx: np.ndarray,
                 cy: np.ndarray, pitch: float, blur: float, noise: float) -> None:
        h, w = image.shape
        ax_all = pixel_profile(pitch, blur, np.arange(w)[:, None] + 0.5 - cx[None, :])
        ay_all = pixel_profile(pitch, blur, np.arange(h)[:, None] + 0.5 - cy[None, :])
        known = grid.astype(float).copy()
        known[2:-2, 2:-2] = 0
        self.residual = (225 - image.astype(float)) / 200 - ay_all @ known @ ax_all.T
        self.ax, self.ay = ax_all[:, 2:-2], ay_all[:, 2:-2]
        self.ux, self.sx, vxh = np.linalg.svd(self.ax, full_matrices=False)
        self.uy, self.sy, vyh = np.linalg.svd(self.ay, full_matrices=False)
        self.vx, self.vy = vxh.T, vyh.T
        self.singular = self.sy[:, None] * self.sx[None, :]
        self.noise2 = (noise / 200) ** 2

    def extrinsic(self, prior_llr: np.ndarray, heterogeneous: bool = False) -> np.ndarray:
        mean = expit(-np.clip(prior_llr, -20, 20))
        variance = max(float(np.mean(mean * (1 - mean))), 1e-4)
        residual = self.residual - self.ay @ mean @ self.ax.T
        power = self.singular ** 2
        denominator = self.noise2 + variance * power
        compressed = self.uy.T @ residual @ self.ux
        score = self.vy @ (self.singular * compressed / denominator) @ self.vx.T
        q = (self.vy ** 2) @ (power / denominator) @ (self.vx ** 2).T
        if heterogeneous:
            local_variance = np.maximum(mean * (1 - mean), 1e-4)
            shape = residual.shape

            def multiply(flat: np.ndarray) -> np.ndarray:
                value = flat.reshape(shape)
                projected = self.ay.T @ value @ self.ax
                return (self.noise2 * value + self.ay @ (local_variance * projected)
                        @ self.ax.T).ravel()

            def precondition(flat: np.ndarray) -> np.ndarray:
                value = flat.reshape(shape)
                modes = self.uy.T @ value @ self.ux
                shrink = variance * power / denominator
                return ((value - self.uy @ (shrink * modes) @ self.ux.T)
                        / self.noise2).ravel()

            count = residual.size
            solved, _ = cg(LinearOperator((count, count), matvec=multiply, dtype=float),
                           residual.ravel(),
                           M=LinearOperator((count, count), matvec=precondition, dtype=float),
                           rtol=1e-6, maxiter=80)
            score = self.ay.T @ solved.reshape(shape) @ self.ax
            # Own-prior correction is exact when the other variances share
            # their mean; for heterogeneous neighbours this diagonal remains
            # an approximation, although the residual solve above is exact
            # to its reported numerical tolerance.
            q = q / np.maximum(1 + (local_variance - variance) * q, 1e-4)
            return np.clip((q * (0.5 - mean) - score)
                           / np.maximum(1 - local_variance * q, 1e-4), -40, 40)
        return np.clip((q * (0.5 - mean) - score)
                       / np.maximum(1 - variance * q, 1e-4), -40, 40)

    def relaxed_capacity_bound(self) -> float:
        """Gaussian trace-power relaxation, bits over this finite data region."""
        eigenvalues = (self.singular ** 2).ravel()
        active = eigenvalues[eigenvalues > 1e-15]
        floors = self.noise2 / active
        power = self.ax.shape[1] * self.ay.shape[1] / 4
        low, high = float(floors.min()), float(floors.min() + power + 1)
        for _ in range(80):
            level = (low + high) / 2
            if np.maximum(level - floors, 0).sum() > power:
                high = level
            else:
                low = level
        allocation = np.maximum((low + high) / 2 - floors, 0)
        return float(0.5 * np.log2(1 + active * allocation / self.noise2).sum())

    def gaussian_message(self, mean: np.ndarray, local_variance: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Extrinsic scalar Gaussian observations for arbitrary intensity priors."""
        variance = max(float(np.mean(local_variance)), 1e-5)
        residual = self.residual - self.ay @ mean @ self.ax.T
        power = self.singular ** 2
        denominator = self.noise2 + variance * power
        modes = self.uy.T @ residual @ self.ux
        score = self.vy @ (self.singular * modes / denominator) @ self.vx.T
        q = (self.vy ** 2) @ (power / denominator) @ (self.vx ** 2).T
        observation = mean + score / np.maximum(q, 1e-12)
        precision = q / np.maximum(1 - variance * q, 1e-5)
        return observation, precision


def decode(v: Version, image: np.ndarray, cx: np.ndarray, cy: np.ndarray,
           pitch: float, blur: float, noise: float = 8.0, rounds: int = 12,
           scale: float = 0.8, equalizer: str = "average") -> tuple[bytes | None, list[dict[str, object]]]:
    code, permutation, mask = code_and_mapping(v.S, v.rate)
    frame = dense.frame_modules(v.S).astype(float)
    frame[frame < 0] = 0
    operator = NativeOperator(image, frame, cx, cy, pitch, blur, noise)
    decoder = SoftIRA(code)
    prior = np.zeros((v.S - 4, v.S - 4))
    history = []
    for step in range(rounds):
        physical = operator.extrinsic(prior, heterogeneous=equalizer == "cg").ravel()[permutation]
        channel = np.clip(scale * np.where(mask, -physical, physical), -30, 30)
        word, external, ok = decoder.decode(channel)
        result = decode_outer(v, word[:v.info_bits]) if ok else None
        history.append({"round": step + 1, "checks_satisfied": bool(ok),
                        "payload_valid": result is not None})
        if result is not None:
            return result, history
        feedback = np.zeros(code.n)
        feedback[permutation] = np.where(mask, -external, external)
        prior = 0.5 * prior + 0.5 * np.clip(feedback.reshape(prior.shape), -15, 15)
    return None, history
