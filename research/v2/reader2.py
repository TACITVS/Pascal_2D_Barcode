"""PASCAL-MDS v2 photo reader (prototype).  See dense.py for the format."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

import dense
from dense import LEVELS, QUIET, STAGES, codes, coset_positions, decode_info_bits, frame_modules, scramble, version
from ldpc import Decoder
from pascal_mds.reader import (apply_h, binarize_adaptive, binarize_otsu, candidate_quads, homography, load_gray,
                               locate, sample)

import v2_detector as det  # model-based detector (footprints, filters)

D, LIGHT = det.D, det.LIGHT
NB = det.NB
OFFS = det.OFFS


@dataclass
class Result:
    data: bytes
    S: int
    level: str
    mirrored: bool
    blur_px: float
    pitch_px: float
    corners: np.ndarray


def module_h(corners: np.ndarray, S: int, mirrored: bool) -> np.ndarray:
    """Homography from module coordinates (x right, y down) to the image.
    Mirrored: logical (x, y) sits at physical (S - y, S - x)."""
    src = np.array([[0, 0], [S, 0], [S, S], [0, S]], float)
    if mirrored:
        src = np.stack([S - src[:, 1], S - src[:, 0]], 1)
    return homography(src, corners)


def window_samples(gray, h, rows, cols):
    """(m, 49) grey values on the 7 x 7 half-module grid around modules."""
    cx, cy = cols + 0.5, rows + 0.5
    return np.stack([sample(gray, *apply_h(h, cx + ox, cy + oy)) for oy in OFFS for ox in OFFS], 1)


def _quad_fit(xs, ys, vals):
    a = np.stack([np.ones_like(xs), xs, ys, xs * xs, xs * ys, ys * ys], 1)
    return np.linalg.lstsq(a, vals, rcond=None)[0]


def _quad_eval(c, xs, ys):
    return c[0] + c[1] * xs + c[2] * ys + c[3] * xs * xs + c[4] * xs * ys + c[5] * ys * ys


class Photo:
    """Grey image + geometry of one located symbol.  Illumination is modelled
    as (y / light(x)) ** gamma = 1 - kappa * darkening, with light(x) a
    quadratic surface fitted to the quiet zone; gamma (the camera's tone
    curve), kappa (contrast) and the blur are fitted to the frame by
    estimate()."""

    def __init__(self, gray, corners, S, mirrored):
        self.gray, self.S, self.mirrored = gray, S, mirrored
        self.h = module_h(corners, S, mirrored)
        Q = QUIET
        ring = [(r, c) for r in range(-Q, S + Q) for c in range(-Q, S + Q)
                if min(r, c, S - 1 - r, S - 1 - c) <= -2]
        rr = np.array([p[0] for p in ring])
        cc = np.array([p[1] for p in ring])
        vals = sample(gray, *apply_h(self.h, cc + 0.5, rr + 0.5))
        self.fit_light = _quad_fit((cc + 0.5) / S - 0.5, (rr + 0.5) / S - 0.5, vals)
        self.kappa, self.gamma = 1.0, 1.0
        c = S / 2
        x0, y0 = apply_h(self.h, np.array([c - 1, c + 1]), np.array([c, c]))
        x1, y1 = apply_h(self.h, np.array([c, c]), np.array([c - 1, c + 1]))
        self.pitch = float(np.sqrt(np.hypot(x0[1] - x0[0], y0[1] - y0[0]) * np.hypot(x1[1] - x1[0], y1[1] - y1[0])) / 2)

    def known_grid(self) -> np.ndarray:
        """(S+2Q) x (S+2Q): 0/1 for frame and quiet-zone modules, -1 data."""
        S, Q = self.S, QUIET
        g = np.zeros((S + 2 * Q, S + 2 * Q), dtype=np.int8)
        g[Q:Q + S, Q:Q + S] = frame_modules(S)
        return g

    def darkening(self, rows, cols):
        """Relative darkening 1 - (y / light) ** gamma on the 7 x 7 window grid."""
        y = window_samples(self.gray, self.h, rows, cols)
        lt = _quad_eval(self.fit_light, (cols + 0.5) / self.S - 0.5, (rows + 0.5) / self.S - 0.5)[:, None]
        return 1 - np.clip(y / np.maximum(lt, 1.0), 0, 1.5) ** self.gamma

    def normalised(self, rows, cols):
        """Samples on the detector's scale: light -> LIGHT, full dark -> DARK."""
        return LIGHT - D * self.darkening(rows, cols) / self.kappa


# Candidate tone curves.  Phones store gamma-encoded, tone-mapped pixels,
# and overexposed screens bloom, so the half-light at a module edge reads
# lighter than mid-grey.  The frame fit does not predict decoding well (on
# simulated photos it prefers 1.5 while 1.0 decodes better), so read() tries
# the linear model first and the best-fitting curve only if that fails.
GAMMAS = (1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0)


# Most modules a refit samples (evenly spaced over the known ones); enough
# for the four model parameters and the 49 noise levels, and keeps a refit
# on a large symbol fast.
MAX_FIT_MODULES = 1500


def estimate(ph: Photo, gammas=(1.0,), known=None):
    """Tone curve, blur and contrast by least squares on the known modules
    (data neighbours at their mean); noise per window position.  known:
    (S+2Q) x (S+2Q) grid of 0/1 known modules and -1 unknown; default the
    frame and quiet zone, after a stage decodes also its modules.
    Sets ph.gamma and ph.kappa; returns (blur_px, noise): noise is the
    standard deviation, in detector grey levels, of each of the 49 window
    samples."""
    S, Q = ph.S, QUIET
    if known is None:
        known = ph.known_grid()
    fr, fc = np.nonzero(known[Q:Q + S, Q:Q + S] >= 0)
    if len(fr) > MAX_FIT_MODULES:
        keep = np.linspace(0, len(fr) - 1, MAX_FIT_MODULES).astype(int)
        fr, fc = fr[keep], fc[keep]
    y = window_samples(ph.gray, ph.h, fr, fc)
    lt = _quad_eval(ph.fit_light, (fc + 0.5) / S - 0.5, (fr + 0.5) / S - 0.5)[:, None]
    rel = np.clip(y / np.maximum(lt, 1.0), 0, 1.5)
    kg = np.pad(known, det.RAD, constant_values=0)
    x = np.stack([kg[fr + Q + det.RAD + dr, fc + Q + det.RAD + dc] for dr, dc in NB], 1).astype(float)
    x[x < 0] = 0.5
    unknown = (x == 0.5).astype(float)
    pitch = round(ph.pitch, 2)

    def fit(gamma, b):
        """(misfit, gamma, blur, kappa, per-position excess variance).
        With the linear model alone the misfit is the plain least-squares
        residual.  Across tone curves it is the residual beyond what the
        unknown data neighbours explain, on the detector scale (measured to
        pick curves that decode the round-2 photos)."""
        d = 1 - rel ** gamma
        F = det.footprints(pitch, b)
        m = x @ F + 0.5 * (1 - F.sum(0))
        kappa = max(float((d * m).sum() / max((m * m).sum(), 1e-9)), 0.05)
        excess = ((D / kappa) * (d - kappa * m)) ** 2 - (D * D / 4) * (unknown @ (F * F))
        misfit = float(((d - kappa * m) ** 2).mean()) if len(gammas) == 1 else float(excess.mean())
        return misfit, gamma, b, kappa, np.maximum(excess.mean(0), 0.0)

    # coarse grid, then refine the blur around the best point
    best = min((fit(g, round(b, 2)) for g in gammas for b in np.arange(0.3, 3.51, 0.25)), key=lambda t: t[0])
    best = min((fit(best[1], round(b, 2)) for b in np.arange(max(0.3, best[2] - 0.2), best[2] + 0.21, 0.05)),
               key=lambda t: t[0])
    _, ph.gamma, blur, ph.kappa, mismatch2 = best
    # Model mismatch per window position: crisp, pixel-snapped renderings,
    # sharpening halos and screen bloom break the footprint model mostly at
    # module edges.  Counting each position's misfit as its own noise keeps
    # the soft information honest there and lets the clean module centres
    # carry the decision.
    ring = [(r, c) for r in range(-Q, S + Q) for c in range(-Q, S + Q)
            if min(r, c, S - 1 - r, S - 1 - c) in (-3, -4)]
    rr = np.array([p[0] for p in ring])
    cc = np.array([p[1] for p in ring])
    vals = ph.normalised(rr, cc)[:, len(OFFS) ** 2 // 2]
    return blur, np.maximum(3.0, np.sqrt(np.var(vals) + mismatch2))


# Fraction of parity checks violated by the raw hard decisions.  A wrong
# hypothesis (level, mirror, or a v1 symbol) gives ~0.5; a decodable photo
# clearly less (measured: right 0.00-0.33 down to the decode limit, wrong
# 0.46-0.55), so hypotheses above 0.42 are rejected without decoding.
REJECT_ABOVE = 0.42


def unsatisfied_fraction(code, llr) -> float:
    hard = (llr < 0).astype(np.uint8)
    s = np.zeros(code.m, np.uint8)
    np.add.at(s, code.h1_rows, hard[code.h1_cols])
    s = (s + hard[code.k:]) & 1
    s[1:] ^= hard[code.k:-1]
    return float(s.mean())


# LLR scales tried in turn when a stage fails to decode.  The detector's
# Gaussian model is overconfident on real photos (screen bloom, sharpening,
# tone mapping): on the round-2 photos scaling the LLRs down by 2-4x
# recovered most of the information an oracle scale gives.  A success is
# verified by the parity checks and the outer code, so the retries cost
# time only on stages that fail and never change a successful decode.
LLR_SCALES = (1.0, 0.5, 0.25)


def stage_llrs(ph: Photo, F, noise, state, k: int, filters: dict) -> np.ndarray:
    """LLRs (> 0: light) of stage k's modules given the decided ones in state
    ((S+2Q+2R)^2, -1 = undecided); filters caches one filter per pattern of
    known neighbours."""
    S, Q, R = ph.S, QUIET, det.RAD
    off = Q + R
    rr, cc = coset_positions(S, k)
    y = ph.normalised(rr, cc)
    nb_vals = np.stack([state[rr + off + dr, cc + off + dc] for dr, dc in NB], 1)
    llr = np.empty(len(rr))
    masks = nb_vals >= 0
    keys, inverse = np.unique(np.packbits(masks, axis=1), axis=0, return_inverse=True)
    inverse = inverse.ravel()
    for gi in range(len(keys)):
        sel = np.flatnonzero(inverse == gi)
        known_set = {NB[i] for i in np.flatnonzero(masks[sel[0]]) if NB[i] != (0, 0)}
        key = tuple(sorted(known_set))
        flt = filters.get(key)
        if flt is None:
            flt = filters[key] = det.stage_filter(F, known_set, noise)
        kn = flt[2]
        xk = nb_vals[sel][:, kn].astype(float) if kn else np.zeros((len(sel), 0))
        llr[sel] = det.stage_llr(y[sel], xk, F, flt)
    return llr


def decode_symbol(gray, corners, S, mirrored, level, est=None, gammas=(1.0,)):
    """Decode one hypothesis.  est: (blur, noise, kappa, gamma) from a
    previous hypothesis on the same symbol (they do not depend on level or
    orientation) to skip re-estimating them.  gammas: tone curves the
    refits may choose from.

    After each stage decodes, the model is refitted on the frame plus every
    module decoded so far.  The frame alone is a thin band with few
    patterns; on the round-3 photos the refit raised the late stages'
    information by up to 0.2 bit per module (e.g. 0.70 -> 0.91)."""
    ph = Photo(gray, corners, S, mirrored)
    if est is None:
        blur, noise = estimate(ph, gammas)
    else:
        blur, noise, ph.kappa, ph.gamma = est
    v = version(S, level)
    Q, R = QUIET, det.RAD
    state = np.pad(ph.known_grid().astype(np.int16), R, constant_values=0)  # -1 = undecided data
    off = Q + R
    info = []
    for k, code in enumerate(codes(S, level)):
        if k:
            blur, noise = estimate(ph, gammas, state[R:-R, R:-R])
        F = det.footprints(round(ph.pitch, 2), round(blur, 2))
        llr = stage_llrs(ph, F, noise, state, k, {})
        rr, cc = coset_positions(S, k)
        sc = scramble(S, level, k, len(rr))
        llr = np.where(sc == 1, -llr, llr)
        if k == 0 and unsatisfied_fraction(code, llr) > REJECT_ABOVE:
            return None  # wrong level, orientation or format: checks look random
        for scale in LLR_SCALES:
            bits, ok = Decoder(code).decode(np.clip(scale * llr, -30, 30), iters=80)
            if ok:
                break
        else:
            return None
        info.append(bits[:code.k])
        state[rr + off, cc + off] = bits ^ sc
    data = decode_info_bits(v, np.concatenate(info))
    if data is None:
        return None
    return Result(data, S, level, mirrored, blur, ph.pitch, corners)


def read(image, max_side: int = 2400, levels: str = "ABC") -> list[Result]:
    gray = load_gray(image)
    scale = max(1.0, max(gray.shape) / max_side)
    if scale > 1:
        from PIL import Image
        size = (round(gray.shape[1] / scale), round(gray.shape[0] / scale))
        gray = np.asarray(Image.fromarray(gray).resize(size, Image.BOX), dtype=np.float32)
    found: list[Result] = []
    for binarize in (binarize_adaptive, binarize_otsu):
        for quad in candidate_quads(gray, binarize(gray)):
            if any(_inside(quad.mean(0), f.corners / scale) for f in found):
                continue
            loc = locate(gray, quad)
            if loc is None:
                continue
            corners, n_cells, _ = loc
            S = 2 * n_cells
            if S not in dense.SIZES:
                continue
            res = None
            tried = set()
            for gammas in ((1.0,), GAMMAS):
                ph = Photo(gray, corners, S, False)
                blur, noise = estimate(ph, gammas)
                if ph.gamma in tried:
                    continue
                tried.add(ph.gamma)
                est = (blur, noise, ph.kappa, ph.gamma)
                for mirrored in (False, True):
                    for level in levels:
                        res = decode_symbol(gray, corners, S, mirrored, level, est, gammas)
                        if res:
                            break
                    if res:
                        break
                if res:
                    break
            if res:
                res.corners = res.corners * scale
                found.append(res)
    return found


def _inside(p, poly) -> bool:
    sign = None
    for i in range(4):
        a, b = poly[i], poly[(i + 1) % 4]
        s = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]) > 0
        if sign is None:
            sign = s
        elif s != sign:
            return False
    return True
