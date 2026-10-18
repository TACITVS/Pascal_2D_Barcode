"""Model-based soft detector for dense symbols (step 2-3).

Per photo: estimate the blur from known pilot modules, predict each module's
footprint on the 7x7 sample grid (the impulse response R), and compute
log-likelihood ratios with a Gaussian model in which undecided neighbours
are interference and decided ones are subtracted:

    z = y - L + D * sum_{known n} x_n R_n + D/2 * sum_{unknown n} R_n
    z = -D x_i R_i + w,   w ~ N(0, C),  C = s^2 I + D^2/4 sum_{unknown} R_n R_n^T
    LLR_i = a^T C^-1 z + a^T C^-1 a / 2,   a = D R_i        (> 0 means light)

so each stage is one linear filter plus a bias.  Compared here with the MLP
detectors of multistage.py on the same realistic channel.
"""

from __future__ import annotations

import argparse
from functools import lru_cache

import numpy as np

from capacity import DARK, LIGHT, OFFS, Channel, bilinear, render
from multistage import STAGES, known_offsets, stage_rows

D = LIGHT - DARK
RAD = 3  # neighbourhood radius in modules (7 x 7 neighbours)
NB = [(dr, dc) for dr in range(-RAD, RAD + 1) for dc in range(-RAD, RAD + 1)]


@lru_cache(maxsize=None)
def response_grid(pitch: float, blur: float) -> np.ndarray:
    """R on the half-module lattice: R[(dy+4.5)*2, (dx+4.5)*2] = darkening
    (0..1) at displacement (dx, dy) modules from a single dark module's
    centre, averaged over sub-pixel phases."""
    lattice = np.arange(-4.5, 4.51, 0.5)
    acc = np.zeros((len(lattice), len(lattice)))
    ch = Channel(pitch, blur, 0.0, 0, 2)
    rng = np.random.default_rng(0)
    n = 13
    for _ in range(16):
        mods = np.zeros((n, n), int)
        mods[n // 2, n // 2] = 1
        img, cx, cy = render(mods, ch, rng)
        x0, y0 = cx[n // 2], cy[n // 2]
        gx, gy = np.meshgrid(lattice, lattice)
        acc += (LIGHT - bilinear(img, x0 + gx * pitch, y0 + gy * pitch)) / D
    return acc / 16


def footprints(pitch: float, blur: float) -> np.ndarray:
    """F[n, j]: darkening of sample j (7x7 offsets around module i) caused
    by neighbour n of module i."""
    R = response_grid(pitch, round(blur, 2))
    F = np.zeros((len(NB), len(OFFS) ** 2))
    for ni, (dr, dc) in enumerate(NB):
        j = 0
        for oy in OFFS:
            for ox in OFFS:
                dx, dy = ox - dc, oy - dr
                if abs(dx) <= 4.5 and abs(dy) <= 4.5:
                    F[ni, j] = R[int(round((dy + 4.5) * 2)), int(round((dx + 4.5) * 2))]
                j += 1
    return F


def samples(img, cx, cy, rows, cols, ch, rng):
    px = cx[cols] + (rng.normal(0, ch.grid_error, len(cols)) if ch.grid_error else 0)
    py = cy[rows] + (rng.normal(0, ch.grid_error, len(rows)) if ch.grid_error else 0)
    return np.stack([bilinear(img, px + ox * ch.pitch, py + oy * ch.pitch) for oy in OFFS for ox in OFFS], 1)


def stage_filter(F: np.ndarray, known: set, noise: float):
    """(w, bias, known_idx, unknown_idx) for one stage."""
    centre = NB.index((0, 0))
    unk = [i for i, o in enumerate(NB) if o != (0, 0) and o not in known]
    kn = [i for i, o in enumerate(NB) if o in known]
    C = noise ** 2 * np.eye(F.shape[1]) + (D ** 2 / 4) * F[unk].T @ F[unk]
    a = D * F[centre]
    w = np.linalg.solve(C, a)
    return w, 0.5 * a @ w, kn, unk


def stage_llr(y, x_known, F, flt):
    """y: (m, 49) samples; x_known: (m, len(kn)) values of known neighbours."""
    w, bias, kn, unk = flt
    z = y - LIGHT + D * (x_known @ F[kn]) + (D / 2) * F[unk].sum(0)
    return z @ w + bias


QUIET, BAND = 4, 3  # light quiet-zone modules, then a known pilot band


def known_mask(side: int) -> np.ndarray:
    d = np.minimum(np.minimum.outer(np.arange(side), np.arange(side)),
                   np.minimum.outer(np.arange(side)[::-1], np.arange(side)[::-1]))
    return d < QUIET + BAND


def estimate_blur(img, cx, cy, mods, ch, rng, grid=np.arange(0.4, 3.01, 0.05)):
    """Least-squares blur fit on the known pilot band; neighbours outside the
    band count at their mean (0.5)."""
    side = mods.shape[0]
    known = known_mask(side)
    d = np.minimum(np.minimum.outer(np.arange(side), np.arange(side)),
                   np.minimum.outer(np.arange(side)[::-1], np.arange(side)[::-1]))
    rr, cc = np.nonzero((d >= QUIET) & (d < QUIET + BAND))
    y = samples(img, cx, cy, rr, cc, ch, rng)
    x = np.stack([np.where(known[rr + dr, cc + dc], mods[rr + dr, cc + dc], 0.5) for dr, dc in NB], 1)
    best = None
    for b in grid:
        F = footprints(ch.pitch, float(b))
        err = ((y - (LIGHT - D * (x @ F))) ** 2).mean()
        if best is None or err < best[0]:
            best = (err, float(b))
    return best[1], float(np.sqrt(best[0]))


def rate_from_llr(llr, x):
    s = np.where(x == 0, 1.0, -1.0)
    return float(1 - np.mean(np.logaddexp(0, -s * llr)) / np.log(2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pitch", type=float, default=1.2)
    ap.add_argument("--blur", type=float, default=0.7)
    ap.add_argument("--frames", type=int, default=12)
    ap.add_argument("--side", type=int, default=104)
    ap.add_argument("--jitter", type=float, default=0.25)
    a = ap.parse_args()
    ch = Channel(a.pitch, a.blur, 6.0, 75, 2, a.jitter, 0.1)
    rng = np.random.default_rng(5)
    # the pilot band: modules whose 7x7 neighbourhood is fully known
    band = QUIET + BAND + RAD
    rates = {"oracle": [[] for _ in STAGES], "estimated": [[] for _ in STAGES], "nominal": [[] for _ in STAGES]}
    blur_err = []
    for _ in range(a.frames):
        mods = rng.integers(0, 2, (a.side, a.side))
        q = np.minimum(np.minimum.outer(np.arange(a.side), np.arange(a.side)),
                       np.minimum.outer(np.arange(a.side)[::-1], np.arange(a.side)[::-1])) < QUIET
        mods[q] = 0
        img, cx, cy = render(mods, ch, rng)
        true_blur = render.last_blur
        est, resid = estimate_blur(img, cx, cy, mods, ch, rng)
        blur_err.append(est - true_blur)
        noise = ch.noise
        for name, b in (("oracle", true_blur), ("estimated", est), ("nominal", ch.blur)):
            F = footprints(ch.pitch, b)
            for k in range(4):
                known = set(known_offsets_radius(k))
                flt = stage_filter(F, known, noise)
                rr, cc = stage_rows_inner(a.side, k, band)
                y = samples(img, cx, cy, rr, cc, ch, rng)
                xk = np.stack([mods[rr + NB[i][0], cc + NB[i][1]] for i in flt[2]], 1) if flt[2] else np.zeros((len(rr), 0))
                llr = stage_llr(y, xk, F, flt)
                rates[name][k].append(rate_from_llr(llr, mods[rr, cc]))
    print(f"channel {ch}")
    print(f"blur estimate error: mean {np.mean(blur_err):+.3f} px, rms {np.sqrt(np.mean(np.square(blur_err))):.3f} px")
    for name, r in rates.items():
        per = [float(np.mean(v)) for v in r]
        print(f"{name:9s} stage rates " + ", ".join(f"{x:.3f}" for x in per) + f"   mean {np.mean(per):.3f}")


def known_offsets_radius(stage: int):
    """Like multistage.known_offsets but over the radius-3 neighbourhood."""
    r0, c0 = STAGES[stage]
    done = set(STAGES[:stage])
    return [(dr, dc) for dr, dc in NB if (dr, dc) != (0, 0) and ((r0 + dr) % 2, (c0 + dc) % 2) in done]


def stage_rows_inner(side: int, stage: int, margin: int):
    rr, cc = stage_rows(side, stage)
    keep = (rr >= margin) & (rr < side - margin) & (cc >= margin) & (cc < side - margin)
    return rr[keep], cc[keep]


if __name__ == "__main__":
    main()
