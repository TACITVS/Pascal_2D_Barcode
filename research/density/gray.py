"""PM257-GRAY-2026-10-19: multilevel global optical-code prototype.

Two or three separately coded bit planes share each grey-intensity module.
An optical Gaussian detector and all LDPC planes exchange extrinsic soft
information. Registered, calibrated linear print/camera channel only.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from scipy.special import expit, logsumexp

try:
    from . import turbo
except ImportError:
    import turbo


@dataclass(frozen=True)
class Version:
    S: int
    rates: tuple[float, ...]
    info_bits: int
    blocks: tuple[int, ...]

    @property
    def capacity(self) -> int:
        room = sum(b - turbo.dense.RS_PARITY - 1 for b in self.blocks)
        return room - (1 if room - 1 <= 31 else 2) - 8


@lru_cache(maxsize=64)
def version(size: int, rates: tuple[float, ...]) -> Version:
    if len(rates) not in (2, 3):
        raise ValueError("two or three planes required")
    info = sum(turbo.version(size, rate).info_bits for rate in rates)
    total = info // 8
    nb = max(1, -(-total // turbo.dense.RS_BLOCK))
    blocks = tuple(total // nb + (i < total % nb) for i in range(nb))
    return Version(size, rates, info, blocks)


def mapping(size: int, rate: float, plane: int):
    code, permutation, mask = turbo.code_and_mapping(size, rate)
    # Plane-specific masks ensure equal-rate planes do not share physical bits.
    rng = np.random.default_rng(turbo.dense._seed("gray-plane", size, round(rate * 100), plane))
    return code, rng.permutation(len(permutation)), rng.integers(0, 2, len(mask), dtype=np.uint8)


def encode(data: bytes, rates: tuple[float, ...] = (0.7, 0.7),
           size: int | None = None) -> tuple[Version, np.ndarray]:
    for side in ([size] if size is not None else turbo.dense.SIZES):
        v = version(side, rates)
        if len(data) <= v.capacity:
            break
    else:
        raise ValueError("payload does not fit")
    info = turbo.encode_outer(v, data)
    position = 0
    region = np.zeros((v.S - 4) ** 2)
    for j, rate in enumerate(rates):
        code, permutation, mask = mapping(v.S, rate, j)
        word = turbo.ldpc_encode(code, info[position:position + code.k]) ^ mask
        position += code.k
        physical = np.zeros(code.n, dtype=np.uint8)
        physical[permutation] = word
        region += (1 << (len(rates) - 1 - j)) * physical
    grid = turbo.dense.frame_modules(v.S).astype(float)
    grid[2:-2, 2:-2] = region.reshape(v.S - 4, v.S - 4) / ((1 << len(rates)) - 1)
    return v, grid


def decode(v: Version, image: np.ndarray, cx: np.ndarray, cy: np.ndarray,
           pitch: float, blur: float, noise: float = 8.0, rounds: int = 16,
           scale: float = 0.8) -> tuple[bytes | None, list[dict[str, object]]]:
    frame = turbo.dense.frame_modules(v.S).astype(float)
    frame[frame < 0] = 0
    operator = turbo.NativeOperator(image, frame, cx, cy, pitch, blur, noise)
    maps = [mapping(v.S, rate, j) for j, rate in enumerate(v.rates)]
    decoders = [turbo.SoftIRA(row[0]) for row in maps]
    planes = len(v.rates)
    prior = np.zeros((planes, v.S - 4, v.S - 4))
    values = np.arange(1 << planes) / ((1 << planes) - 1)
    labels = np.array([[(i >> (planes - 1 - j)) & 1 for j in range(planes)]
                       for i in range(1 << planes)])
    weights = np.array([1 << (planes - 1 - j) for j in range(planes)]) / ((1 << planes) - 1)
    history = []
    for step in range(rounds):
        probabilities = expit(-prior)
        mean = np.einsum("j,jrc->rc", weights, probabilities)
        variance = np.einsum("j,jrc->rc", weights ** 2, probabilities * (1 - probabilities))
        observation, precision = operator.gaussian_message(mean, variance)
        likelihood = -0.5 * precision[..., None] * (observation[..., None] - values) ** 2
        bit_priors = [-np.logaddexp(0, (2 * labels[:, j] - 1)[None, None, :] * prior[j, ..., None])
                      for j in range(planes)]
        posterior = likelihood + sum(bit_priors)
        info, feedback, checks = [], [], []
        for j, (code, permutation, mask) in enumerate(maps):
            extrinsic = posterior - bit_priors[j]
            llr = (logsumexp(extrinsic[..., labels[:, j] == 0], axis=-1)
                   - logsumexp(extrinsic[..., labels[:, j] == 1], axis=-1))
            physical = llr.ravel()[permutation]
            channel = np.clip(scale * np.where(mask, -physical, physical), -30, 30)
            word, external, ok = decoders[j].decode(channel)
            checks.append(bool(ok))
            info.append(word[:code.k])
            next_prior = np.zeros(code.n)
            next_prior[permutation] = np.where(mask, -external, external)
            feedback.append(np.clip(next_prior.reshape(prior.shape[1:]), -15, 15))
        result = turbo.decode_outer(v, np.concatenate(info)) if all(checks) else None
        history.append({"round": step + 1, "checks_satisfied": checks,
                        "payload_valid": result is not None})
        if result is not None:
            return result, history
        prior = 0.5 * prior + 0.5 * np.stack(feedback)
    return None, history
