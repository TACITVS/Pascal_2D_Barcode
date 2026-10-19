"""PM257-ML-CERT-2026-10-19: exact checkable optical ML certificates.

The optical operator is explicitly quantized to rational coefficients.
A parity-polytope LP proposes a dual witness; integer arithmetic checks it.
An unverified/unsuccessful LP is never reported as a certificate. The witness
proves unique minimum squared optical error among this binary IRA code's
words, under the specified rational model, not under arbitrary real optics.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
from scipy.optimize import linprog
from scipy.sparse import csr_matrix

try:
    from . import turbo
except ImportError:
    import turbo


@dataclass(frozen=True)
class Cut:
    indices: tuple[int, ...]
    coefficients: tuple[int, ...]
    bound: int


def checked_margin(gradient: list[int], candidate: list[int], cuts: list[Cut],
                   weights: list[int], denominator: int) -> int:
    """Exact lower margin numerator; positive certifies strict optimality."""
    if denominator <= 0 or len(weights) != len(cuts) or any(w < 0 for w in weights):
        raise ValueError("invalid dual witness")
    residual = [int(c) * denominator for c in gradient]
    penalty = 0
    for cut, weight in zip(cuts, weights):
        penalty += weight * cut.bound
        for i, coefficient in zip(cut.indices, cut.coefficients):
            residual[i] += weight * coefficient
    lower = sum(min(0, r) for r in residual) - penalty
    target = sum(c * x for c, x in zip(gradient, candidate)) * denominator
    return lower - target


def optical_gradient(operator: turbo.NativeOperator, image: np.ndarray,
                     grid: np.ndarray, bits: int = 8) -> tuple[np.ndarray, dict[str, object]]:
    """Integer gradient of ||b - 200 Ay X Ax^T||² for quantized 1-D H.

    All dimensions used in this prototype fit signed int64; a conservative
    bound is checked before exact matrix multiplication. A reviewer can
    reconstruct the model from the matrices and b returned in the witness.
    """
    scale = 1 << bits
    ax = np.rint(operator.ax * scale).astype(np.int64)
    ay = np.rint(operator.ay * scale).astype(np.int64)
    # operator.residual already subtracts the frame in normalized darkness.
    # Quantize that fixed residual once; this defines the certificate model.
    b = np.rint(operator.residual * 200 * scale ** 2).astype(np.int64)
    point = grid[2:-2, 2:-2].astype(np.int64)
    row_x = max(int(x) for x in ax.sum(axis=1))
    row_y = max(int(x) for x in ay.sum(axis=1))
    col_x = max(int(x) for x in ax.sum(axis=0))
    col_y = max(int(x) for x in ay.sum(axis=0))
    residual_bound = 200 * row_x * row_y + int(np.abs(b).max())
    bound = 2 * 200 * col_x * col_y * residual_bound
    if bound >= 2 ** 63:
        raise OverflowError("certificate arithmetic would exceed int64")
    residual = 200 * ay @ point @ ax.T - b
    # A spectral shift makes the relaxation useful: x_i^2=x_i for bits.
    # Gershgorin supplies an EXACT integer lower bound on each 1-D Gram.
    gx, gy = ax.T @ ax, ay.T @ ay
    lower_x = max(0, int(np.min(2 * np.diag(gx) - np.abs(gx).sum(axis=1))))
    lower_y = max(0, int(np.min(2 * np.diag(gy) - np.abs(gy).sum(axis=1))))
    shift = 200 ** 2 * lower_x * lower_y
    bound += shift
    if bound >= 2 ** 63:
        raise OverflowError("shifted certificate gradient would exceed int64")
    gradient = 2 * 200 * ay.T @ residual @ ax + shift * (1 - 2 * point)
    model = {"quantization_bits": bits, "ax": ax.tolist(), "ay": ay.tolist(),
             "b": b.tolist(), "physical_point": point.tolist(),
             "gradient_int64_bound": bound, "spectral_shift": shift}
    return gradient, model


def certify(v: turbo.Version, payload: bytes, image: np.ndarray,
            cx: np.ndarray, cy: np.ndarray, pitch: float, blur: float,
            max_rounds: int = 30) -> dict[str, object]:
    _, grid = turbo.encode(payload, v.rate, v.S)
    operator = turbo.NativeOperator(image, grid, cx, cy, pitch, blur, 8.0)
    physical_gradient, model = optical_gradient(operator, image, grid)
    code, permutation, mask = turbo.code_and_mapping(v.S, v.rate)
    physical_word = grid[2:-2, 2:-2].ravel()[permutation]
    candidate = (physical_word ^ mask).astype(int).tolist()
    gradient = (physical_gradient.ravel()[permutation]
                * (1 - 2 * mask.astype(np.int64))).tolist()
    d = turbo.SoftIRA(code).decoder
    neighbourhoods = [d.c[start:end].tolist() for start, end in
                      zip(d.check_starts, np.r_[d.check_starts[1:], len(d.c)])]
    assert all(sum(candidate[i] for i in group) % 2 == 0 for group in neighbourhoods)
    # Valid for every distinct binary word; excludes only the candidate.
    cuts = [Cut(tuple(range(code.n)), tuple(2 * x - 1 for x in candidate),
                sum(candidate) - 1)]
    seen: set[tuple[tuple[int, ...], tuple[int, ...]]] = set()
    unit = max(max(abs(c) for c in gradient), 1)
    objective = np.asarray(gradient, float) / unit
    start = time.perf_counter()
    for step in range(max_rounds):
        rows, columns, values = [], [], []
        for j, cut in enumerate(cuts):
            rows.extend([j] * len(cut.indices))
            columns.extend(cut.indices)
            values.extend(cut.coefficients)
        matrix = csr_matrix((values, (rows, columns)), shape=(len(cuts), code.n))
        result = linprog(objective, A_ub=matrix,
                         b_ub=np.array([cut.bound for cut in cuts], float),
                         bounds=(0, 1), method="highs")
        if not result.success:
            break
        denominator = 1 << 20
        weights = [max(0, round(float(-x) * unit * denominator))
                   for x in result.ineqlin.marginals]
        margin = checked_margin(gradient, candidate, cuts, weights, denominator)
        if margin > 0:
            return {"status": "certified_unique_ml", "model": model,
                    "version": {"S": v.S, "rate": v.rate},
                    "gradient": gradient, "candidate": candidate,
                    "cuts": [{"indices": cut.indices, "coefficients": cut.coefficients,
                              "bound": cut.bound} for cut in cuts],
                    "weights": weights, "denominator": denominator,
                    "strict_margin_numerator": str(margin),
                    "rounds": step + 1, "seconds": time.perf_counter() - start}
        added = 0
        for group in neighbourhoods:
            positive = [i for i in group if result.x[i] > 0.5]
            if len(positive) % 2 == 0:
                closest = min(group, key=lambda i: abs(result.x[i] - 0.5))
                if closest in positive:
                    positive.remove(closest)
                else:
                    positive.append(closest)
            subset = set(positive)
            coefficients = tuple(1 if i in subset else -1 for i in group)
            bound = len(subset) - 1
            violation = sum(a * result.x[i] for i, a in zip(group, coefficients)) - bound
            key = tuple(group), coefficients
            if violation > 1e-7 and key not in seen:
                cuts.append(Cut(tuple(group), coefficients, bound))
                seen.add(key)
                added += 1
        if not added:
            break
    return {"status": "uncertified", "rounds": step + 1,
            "cuts": len(cuts), "seconds": time.perf_counter() - start}


def verify(witness: dict[str, object]) -> bool:
    """Recompute the integer gradient and check the dual bound independently."""
    try:
        return _verify(witness)
    except (ValueError, TypeError, KeyError, IndexError, OverflowError):
        return False


def _verify(witness: dict[str, object]) -> bool:
    if witness.get("status") != "certified_unique_ml":
        return False
    def integers(value: object) -> bool:
        return (type(value) is int or
                isinstance(value, (list, tuple)) and all(integers(x) for x in value))

    model = witness["model"]
    for field in ("ax", "ay", "physical_point", "b", "spectral_shift"):
        if not integers(model[field]):
            return False
    for field in ("gradient", "candidate", "weights", "denominator"):
        if not integers(witness[field]):
            return False
    for cut in witness["cuts"]:
        if not all(integers(cut[field]) for field in ("indices", "coefficients", "bound")):
            return False
    ax = np.asarray(model["ax"], dtype=np.int64)
    ay = np.asarray(model["ay"], dtype=np.int64)
    point = np.asarray(model["physical_point"], dtype=np.int64)
    b = np.asarray(model["b"], dtype=np.int64)
    if (any(a.ndim != 2 for a in (ax, ay, point, b)) or
            point.shape != (ay.shape[1], ax.shape[1]) or
            b.shape != (ay.shape[0], ax.shape[0]) or
            not np.all((point == 0) | (point == 1))):
        return False
    # Python integers prevent overflow in the independent recomputation.
    ax, ay, point, b = (a.astype(object) for a in (ax, ay, point, b))
    gx, gy = ax.T @ ax, ay.T @ ay
    lx = max(0, min(2 * int(gx[i, i]) - sum(abs(int(x)) for x in gx[i])
                    for i in range(len(gx))))
    ly = max(0, min(2 * int(gy[i, i]) - sum(abs(int(x)) for x in gy[i])
                    for i in range(len(gy))))
    shift = 200 ** 2 * lx * ly
    if int(model["spectral_shift"]) != shift:
        return False
    physical_gradient = (2 * 200 * ay.T @ (200 * ay @ point @ ax.T - b) @ ax
                         + shift * (1 - 2 * point))
    gradient = list(map(int, witness["gradient"]))
    v = witness["version"]
    code, permutation, mask = turbo.code_and_mapping(int(v["S"]), float(v["rate"]))
    candidate = list(map(int, witness["candidate"]))
    if len(candidate) != code.n or any(x not in (0, 1) for x in candidate):
        return False
    if ((np.asarray(point, dtype=np.uint8).ravel()[permutation] ^ mask).tolist()
            != candidate):
        return False
    expected = (physical_gradient.ravel()[permutation]
                * (1 - 2 * mask.astype(np.int64))).tolist()
    if gradient != expected:
        return False
    cuts = [Cut(tuple(row["indices"]), tuple(row["coefficients"]), int(row["bound"]))
            for row in witness["cuts"]]
    decoder = turbo.SoftIRA(code).decoder
    groups = [tuple(decoder.c[start:end].tolist()) for start, end in
              zip(decoder.check_starts, np.r_[decoder.check_starts[1:], len(decoder.c)])]
    if not all(sum(candidate[i] for i in group) % 2 == 0 for group in groups):
        return False
    exclusion = Cut(tuple(range(code.n)), tuple(2 * x - 1 for x in candidate),
                    sum(candidate) - 1)
    if not cuts or cuts[0] != exclusion:
        return False
    group_set = set(groups)
    for cut in cuts[1:]:
        positives = sum(x == 1 for x in cut.coefficients)
        if (cut.indices not in group_set or len(cut.indices) != len(cut.coefficients)
                or any(x not in (-1, 1) for x in cut.coefficients)
                or positives % 2 != 1 or cut.bound != positives - 1):
            return False
    return checked_margin(gradient, witness["candidate"], cuts,
                          witness["weights"], int(witness["denominator"])) > 0


if __name__ == "__main__":
    import argparse
    import gzip
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("witness", type=Path)
    args = parser.parse_args()
    opener = gzip.open if args.witness.suffix == ".gz" else open
    with opener(args.witness, "rt") as source:
        valid = verify(json.load(source))
    print("VERIFIED unique ML under the published rational model" if valid else "INVALID witness")
    raise SystemExit(0 if valid else 1)
