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
    as y = light(x) * (1 - kappa * darkening), with light(x) a quadratic
    surface fitted to the quiet zone; kappa (contrast) and the blur are fitted
    to the frame by estimate()."""

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
        self.kappa = 1.0
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
        """Relative darkening (light - y) / light on the 7 x 7 window grid."""
        y = window_samples(self.gray, self.h, rows, cols)
        lt = _quad_eval(self.fit_light, (cols + 0.5) / self.S - 0.5, (rows + 0.5) / self.S - 0.5)[:, None]
        return (lt - y) / np.maximum(lt, 1.0)

    def normalised(self, rows, cols):
        """Samples on the detector's scale: light -> LIGHT, full dark -> DARK."""
        return LIGHT - D * self.darkening(rows, cols) / self.kappa


def estimate(ph: Photo):
    """Blur and contrast by least squares on the frame modules (data
    neighbours at their mean); noise from the quiet zone 3-4 modules out.
    Sets ph.kappa; returns (blur_px, noise in detector grey levels)."""
    S, Q = ph.S, QUIET
    known = ph.known_grid()
    fr, fc = np.nonzero(known[Q:Q + S, Q:Q + S] >= 0)
    d = ph.darkening(fr, fc)
    kg = np.pad(known, det.RAD, constant_values=0)
    x = np.stack([kg[fr + Q + det.RAD + dr, fc + Q + det.RAD + dc] for dr, dc in NB], 1).astype(float)
    x[x < 0] = 0.5
    pitch = round(ph.pitch, 2)

    def fit(b):
        F = det.footprints(pitch, b)
        m = x @ F + 0.5 * (1 - F.sum(0))
        kappa = float((d * m).sum() / max((m * m).sum(), 1e-9))
        return float(((d - kappa * m) ** 2).mean()), b, kappa

    # coarse grid, then refine around the best point
    best = min(fit(round(b, 2)) for b in np.arange(0.3, 3.51, 0.25))
    best = min(fit(round(b, 2)) for b in np.arange(max(0.3, best[1] - 0.2), best[1] + 0.21, 0.05))
    _, blur, kappa = best
    ph.kappa = max(kappa, 0.05)
    # Model mismatch: frame residual beyond what the unknown data neighbours
    # explain.  Crisp, pixel-snapped renderings (screens, screenshots) or
    # sharpening break the footprint model; counting the misfit as noise
    # keeps the soft information honest instead of confidently wrong.
    F = det.footprints(pitch, blur)
    m = x @ F + 0.5 * (1 - F.sum(0))
    resid = (D / ph.kappa) * (d - ph.kappa * m)
    unknown_var = (D * D / 4) * ((x == 0.5).astype(float) @ (F * F))
    mismatch2 = max(0.0, float((resid ** 2).mean() - unknown_var.mean()))
    ring = [(r, c) for r in range(-Q, S + Q) for c in range(-Q, S + Q)
            if min(r, c, S - 1 - r, S - 1 - c) in (-3, -4)]
    rr = np.array([p[0] for p in ring])
    cc = np.array([p[1] for p in ring])
    vals = ph.normalised(rr, cc)[:, len(OFFS) ** 2 // 2]
    return blur, float(max(3.0, np.sqrt(np.var(vals) + mismatch2)))


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


def decode_symbol(gray, corners, S, mirrored, level, blur=None, noise=None, kappa=None):
    """Decode one hypothesis.  blur/noise/kappa: pass the estimates from a
    previous hypothesis on the same symbol (they do not depend on level or
    orientation) to skip re-estimating them."""
    ph = Photo(gray, corners, S, mirrored)
    if blur is None:
        blur, noise = estimate(ph)
    else:
        ph.kappa = kappa
    F = det.footprints(round(ph.pitch, 2), round(blur, 2))
    v = version(S, level)
    Q, R = QUIET, det.RAD
    known = ph.known_grid()
    state = np.pad(known.astype(np.int16), R, constant_values=0)  # -1 = undecided data
    off = Q + R
    info = []
    filters = {}
    for k, code in enumerate(codes(S, level)):
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
            key = (k, tuple(sorted(known_set)))
            flt = filters.get(key)
            if flt is None:
                flt = filters[key] = det.stage_filter(F, known_set, noise)
            kn = flt[2]
            xk = nb_vals[sel][:, kn].astype(float) if kn else np.zeros((len(sel), 0))
            llr[sel] = det.stage_llr(y[sel], xk, F, flt)
        sc = scramble(S, level, k, len(rr))
        llr = np.where(sc == 1, -llr, llr)
        if k == 0 and unsatisfied_fraction(code, llr) > REJECT_ABOVE:
            return None  # wrong level, orientation or format: checks look random
        bits, ok = Decoder(code).decode(np.clip(llr, -30, 30), iters=80)
        if not ok:
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
            ph = Photo(gray, corners, S, False)
            blur, noise = estimate(ph)
            for mirrored in (False, True):
                for level in levels:
                    res = decode_symbol(gray, corners, S, mirrored, level, blur, noise, ph.kappa)
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
