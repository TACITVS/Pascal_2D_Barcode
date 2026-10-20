"""PB-SHAPED-GRAY-2026-10-20-v1: unequal-protection four-level prototype.

Geometric shaping uses levels 0, a, 1-a, 1, with independent LDPC rates for
the coarse and fine bits. This is not probabilistic amplitude shaping:
all four labels remain equiprobable. Geometry and linear tone calibration
are supplied. Optical messages, LDPC posteriors and outer GMD are joint.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.special import expit, logsumexp

try:
    from . import gray, soft_outer, turbo
except ImportError:
    import gray
    import soft_outer
    import turbo


@dataclass(frozen=True)
class Version:
    S: int
    rates: tuple[float, float]
    fine_weight: float
    info_bits: int
    blocks: tuple[int, ...]

    @property
    def capacity(self) -> int:
        return gray.version(self.S, self.rates).capacity


def encode(
    data: bytes, rates: tuple[float, float] = (0.85, 0.55),
    fine_weight: float = 0.25, size: int | None = None,
) -> tuple[Version, np.ndarray]:
    if not 0 < fine_weight < 0.5:
        raise ValueError("fine weight must lie strictly between zero and 0.5")
    base, grid = gray.encode(data, rates, size)
    labels = np.rint(3 * grid[2:-2, 2:-2]).astype(np.uint8)
    grid[2:-2, 2:-2] = (
        (1 - fine_weight) * (labels >> 1) + fine_weight * (labels & 1))
    return Version(base.S, rates, fine_weight,
                   base.info_bits, base.blocks), grid


def decode(
    v: Version, image: np.ndarray, cx: np.ndarray, cy: np.ndarray,
    pitch: float, blur: float, noise: float = 8.0, rounds: int = 16,
) -> tuple[bytes | None, list[dict[str, object]]]:
    frame = turbo.dense.frame_modules(v.S).astype(float)
    frame[frame < 0] = 0
    operator = turbo.NativeOperator(
        image, frame, cx, cy, pitch, blur, noise)
    maps = [gray.mapping(v.S, rate, j) for j, rate in enumerate(v.rates)]
    decoders = [turbo.SoftIRA(row[0]) for row in maps]
    prior = np.zeros((2, v.S - 4, v.S - 4))
    labels = np.asarray([[0, 0], [0, 1], [1, 0], [1, 1]])
    weights = np.asarray([1 - v.fine_weight, v.fine_weight])
    values = labels @ weights
    history: list[dict[str, object]] = []
    for step in range(rounds):
        probabilities = expit(-prior)
        mean = np.einsum("j,jrc->rc", weights, probabilities)
        variance = np.einsum(
            "j,jrc->rc", weights ** 2,
            probabilities * (1 - probabilities))
        observation, precision = operator.gaussian_message(mean, variance)
        likelihood = (-0.5 * precision[..., None]
                      * (observation[..., None] - values) ** 2)
        bit_priors = [
            -np.logaddexp(
                0, (2 * labels[:, j] - 1)[None, None, :]
                * prior[j, ..., None])
            for j in range(2)
        ]
        posterior = likelihood + sum(bit_priors)
        info, reliability, feedback, checks = [], [], [], []
        for j, (code, permutation, mask) in enumerate(maps):
            extrinsic = posterior - bit_priors[j]
            llr = (logsumexp(extrinsic[..., labels[:, j] == 0], axis=-1)
                   - logsumexp(extrinsic[..., labels[:, j] == 1], axis=-1))
            physical = llr.ravel()[permutation]
            channel = np.clip(
                0.8 * np.where(mask, -physical, physical), -30, 30)
            word, external, ok = decoders[j].decode(channel)
            info.append(word[:code.k])
            reliability.append((channel + external)[:code.k])
            checks.append(bool(ok))
            next_prior = np.zeros(code.n)
            next_prior[permutation] = np.where(mask, -external, external)
            feedback.append(np.clip(
                next_prior.reshape(prior.shape[1:]), -15, 15))
        bits = np.concatenate(info)
        legacy = turbo.decode_outer(v, bits) if all(checks) else None
        result = (legacy if legacy is not None else soft_outer.decode(
            v, bits, np.concatenate(reliability)))
        history.append({
            "round": step + 1, "checks_satisfied": checks,
            "legacy_valid": legacy is not None,
            "payload_valid": result is not None,
        })
        if result is not None:
            return result, history
        prior = 0.5 * prior + 0.5 * np.stack(feedback)
    return None, history
