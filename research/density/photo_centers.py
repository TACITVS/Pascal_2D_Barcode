"""PM257-NATIVE-CENTERS-2026-10-19-v1: experimental photo-reader fallback.

The timing frame supplies geometry and photometric calibration. Otsu's
threshold uses unlabelled centre intensities, never known payload cells.
The original global IRA and outer integrity checks decide acceptance.
This receiver was selected on development photographs, not held-out data.
"""

from __future__ import annotations

import cv2
import numpy as np

try:
    from .benchmark_density import reader2, turbo
except ImportError:
    from benchmark_density import reader2, turbo


def decode_native_centers(
    gray: np.ndarray,
    corners: np.ndarray,
    size: int,
    rate: float,
) -> tuple[bytes | None, dict[str, object]]:
    """Try one frozen centre-sampling/threshold hypothesis on original pixels.

    The intensity-to-LLR scale is an empirical development setting, not a
    calibrated channel likelihood. Only an inner codeword and valid outer
    payload/tag are accepted. Expected bytes are not arguments to this API.
    """
    photo = reader2.Photo(gray, corners, size, False)
    blur, _ = reader2.estimate(photo, (1.0,))
    rows, cols = np.indices((size - 4, size - 4))
    rows, cols = rows.ravel() + 2, cols.ravel() + 2
    samples = photo.normalised(rows, cols)[:, len(reader2.OFFS) ** 2 // 2]
    threshold, _ = cv2.threshold(
        np.clip(samples, 0, 255).astype(np.uint8),
        0,
        255,
        cv2.THRESH_BINARY + cv2.THRESH_OTSU,
    )
    physical_llr = (samples - threshold) / 10.0
    code, permutation, mask = turbo.code_and_mapping(size, rate)
    channel = physical_llr[permutation]
    channel = np.clip(np.where(mask, -channel, channel), -30, 30)
    word, _, ok = turbo.SoftIRA(code).decode(channel, iters=160)
    version = turbo.version(size, rate)
    payload = turbo.decode_outer(version, word[:version.info_bits]) if ok else None
    details = {
        "receiver": "native_center_otsu_v1",
        "gamma": photo.gamma,
        "kappa": photo.kappa,
        "fitted_blur_px": float(blur),
        "threshold": float(threshold),
        "intensity_per_llr": 10.0,
        "max_iterations": 160,
        "checks_satisfied": bool(ok),
        "payload_valid": payload is not None,
        "uses_original_image_pixels": True,
    }
    return payload, details
