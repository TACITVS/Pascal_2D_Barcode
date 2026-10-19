"""PM257-AUDIT-EVIDENCE-2026-10-19: reproduce analytic audit diagnostics.

Pure Python; no model training. Prints JSON for the original capacity split,
the byte-alphabet counting bound, the pad-rank guarantee, and Wilson 15/16.
"""

from __future__ import annotations

import json
import math
import sys
from fractions import Fraction
from pathlib import Path
from statistics import NormalDist

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pascal_mds.layout import LEVELS, SIZES, _volume, acceptable, version  # noqa: E402


def capacity_split() -> list[dict[str, object]]:
    rows = []
    for pitch in [0.6, 0.8, 1.0, 1.2, 1.5, 2.0, 2.5]:
        per_photo = (max(24, int(360 / pitch)) - 6) ** 2
        train = set(range(15000 // per_photo, 119999 // per_photo + 1))
        test = set(range(120000 // per_photo, 159999 // per_photo + 1))
        shared = train.intersection(test)
        exposed = sum(max(0, min(160000, (g + 1) * per_photo)
                          - max(120000, g * per_photo)) for g in shared)
        rows.append({"pitch": pitch, "samples_per_photo": per_photo,
                     "training_photos": len(train), "test_photos": len(test),
                     "shared_photos": len(shared), "exposed_test_fraction": exposed / 40000})
    return rows


def byte_bound() -> dict[str, object]:
    worst, worst_case, exceeding = Fraction(0), None, 0
    for n in SIZES:
        for level in LEVELS:
            v = version(n, level)
            for erased in range(v.r - v.guard + 1):
                for errors in range((v.r - v.guard - erased) // 2 + 1):
                    if not acceptable(v, errors, erased):
                        continue
                    bound = Fraction(257 ** v.K * _volume(v.N - erased, errors),
                                     256 ** (v.N - erased))
                    exceeding += bound > Fraction(1, 10 ** 10)
                    if bound > worst:
                        worst, worst_case = bound, [n, level, errors, erased]
    return {"generic_byte_bound_max": float(worst), "worst_case": worst_case,
            "accepted_configurations_above_target": exceeding,
            "interpretation": "A looser upper bound, not a measured violation or lower bound."}


def main() -> None:
    n, p, z = 16, 15 / 16, NormalDist().inv_cdf(0.975)
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    result = {"id": "PM257-AUDIT-EVIDENCE-2026-10-19", "capacity_split": capacity_split(),
              "byte_bound": byte_bound(), "wilson_15_of_16": [centre - half, centre + half],
              "pad_rank_bits": {str(r): (256 - r).bit_length() - 1
                                for r in [4, 18, 42, 76, 152, 255]}}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
