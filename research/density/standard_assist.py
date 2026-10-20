"""PB-STANDARD-ASSIST-2026-10-20-v1: independent QR/Data Matrix pilot priors.

Generate known function modules from the public layout rules, never from
the tested symbol. QR's data and mask-dependent format cells stay unknown.
Data Matrix region borders are known. Offer hard candidates after forcing
these pilots and after conditioning a Gaussian solve on their values.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Iterator

import numpy as np
import segno
from scipy.sparse.linalg import LinearOperator, cg

try:
    from .hierarchical_probe import pixel_profile
except ImportError:
    from hierarchical_probe import pixel_profile


@lru_cache(maxsize=32)
def known_pattern(profile: str, shape: tuple[int, int]) -> np.ndarray:
    """NaN marks unknown cells; finite values are payload-independent pilots."""
    height, width = shape
    pattern = np.full(shape, np.nan)
    family, setting = profile.split("/")
    match family:
        case "qr":
            if height != width:
                return pattern
            qr = segno.make_qr(
                b"\x00", version=(width - 17) // 4, error=setting,
                mask=0, mode="byte", encoding="iso-8859-1",
                boost_error=False)
            kinds = np.asarray(list(qr.matrix_iter(
                scale=1, border=0, verbose=True)))
            unknown = np.isin(kinds, [
                segno.consts.TYPE_DATA_LIGHT, segno.consts.TYPE_DATA_DARK,
                segno.consts.TYPE_FORMAT_LIGHT, segno.consts.TYPE_FORMAT_DARK,
            ])
            template = np.asarray(qr.matrix)
            pattern[~unknown] = template[~unknown]
        case "datamatrix":
            # Square ECC200 region counts, ISO layout as independently
            # tabulated in zxing-cpp v3.1.1 core/src/datamatrix/DMVersion.cpp.
            regions = {
                10: 1, 12: 1, 14: 1, 16: 1, 18: 1, 20: 1, 22: 1,
                24: 1, 26: 1, 32: 2, 36: 2, 40: 2, 44: 2, 48: 2,
                52: 2, 64: 4, 72: 4, 80: 4, 88: 4, 96: 4,
                104: 4, 120: 6, 132: 6, 144: 6,
            }
            if height != width or width not in regions:
                return pattern
            side = width // regions[width]
            for r in range(0, height, side):
                for c in range(0, width, side):
                    pattern[r, c:c + side] = np.arange(side) % 2 == 0
                    pattern[r + side - 1, c:c + side] = 1
                    pattern[r + 1:r + side - 1, c] = 1
                    pattern[r + 1:r + side - 1, c + side - 1] = (
                        np.arange(1, side - 1) % 2)
        case _:
            raise ValueError("unsupported standard family")
    pattern.setflags(write=False)
    return pattern


def conditioned_scores(
    image: np.ndarray, cx: np.ndarray, cy: np.ndarray,
    pitch: float, blur: float, noise: float, pattern: np.ndarray,
) -> np.ndarray:
    """Exact Gaussian posterior sign, to the CG solver tolerance.

    Unknown modules have mean 1/2 and variance 1/4; known pilots have
    their known means and zero variance. This is a Gaussian approximation
    to binary modules, not an exact binary posterior or soft RS decoder.
    """
    height, width = image.shape
    ax = pixel_profile(
        pitch, blur, np.arange(width)[:, None] + 0.5 - cx[None, :])
    ay = pixel_profile(
        pitch, blur, np.arange(height)[:, None] + 0.5 - cy[None, :])
    known = np.isfinite(pattern)
    mean = np.where(known, pattern, 0.5)
    variance = np.where(known, 0.0, 0.25)
    residual = ((225 - image.astype(float)) / 200 - ay @ mean @ ax.T)
    noise2 = (noise / 200) ** 2
    ux, sx, _ = np.linalg.svd(ax, full_matrices=False)
    uy, sy, _ = np.linalg.svd(ay, full_matrices=False)
    power = (sy[:, None] * sx[None, :]) ** 2
    shrink = 0.25 * power / (noise2 + 0.25 * power)
    shape = image.shape

    def multiply(flat: np.ndarray) -> np.ndarray:
        value = flat.reshape(shape)
        projected = ay.T @ value @ ax
        return (noise2 * value + ay @ (variance * projected) @ ax.T).ravel()

    def precondition(flat: np.ndarray) -> np.ndarray:
        value = flat.reshape(shape)
        modes = uy.T @ value @ ux
        return ((value - uy @ (shrink * modes) @ ux.T) / noise2).ravel()

    count = image.size
    solved, status = cg(
        LinearOperator((count, count), matvec=multiply, dtype=float),
        residual.ravel(),
        M=LinearOperator((count, count), matvec=precondition, dtype=float),
        rtol=1e-6, maxiter=100)
    if status != 0:
        # A failed iterative solve supplies no extra candidate.
        return np.full(pattern.shape, np.nan)
    return -(ay.T @ solved.reshape(shape) @ ax)


def _chase(
    scores: np.ndarray, pattern: np.ndarray,
) -> Iterator[np.ndarray]:
    known = np.isfinite(pattern)
    grid = scores < 0
    grid[known] = pattern[known] > 0.5
    order = np.argsort(
        np.where(known, np.inf, np.abs(scores)).ravel(), kind="stable")[:3]
    for choice in range(8):
        hypothesis = grid.copy()
        for bit, location in enumerate(order):
            if choice & (1 << bit):
                hypothesis.flat[location] ^= True
        yield hypothesis


def candidates(
    profile: str, image: np.ndarray, cx: np.ndarray, cy: np.ndarray,
    pitch: float, blur: float, noise: float, unconditioned_llr: np.ndarray,
) -> Iterator[tuple[str, np.ndarray]]:
    pattern = known_pattern(profile, (len(cy), len(cx)))
    for grid in _chase(unconditioned_llr, pattern):
        yield "public_pilots_chase", grid
    scores = conditioned_scores(image, cx, cy, pitch, blur, noise, pattern)
    if not np.isfinite(scores).all():
        return
    for grid in _chase(scores, pattern):
        yield "conditioned_gaussian_chase", grid
