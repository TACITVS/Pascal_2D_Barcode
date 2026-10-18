"""Read PASCAL-MDS symbols from photographs or screenshots (needs numpy).

Pipeline (SPEC.md section 6):

1. adaptive binarisation and connected components of dark pixels;
2. the convex hull of a component holding the solid L contains three exact
   symbol corners; the fourth comes from the hull or a parallelogram guess;
3. for every orientation and size, a homography is scored against the known
   frame (L + timing tracks + quiet zone); the best hypothesis wins;
4. corners are refined by fitting straight lines to sub-pixel edge points on
   all four sides;
5. modules are sampled in grey levels against a threshold surface fitted to
   the frame, giving a per-module confidence used to mark erasures;
6. GF(257) errors-and-erasures decoding (codec.decode_bytes).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .codec import Decoded, decode_bytes, read_bytes, symbol_confidence
from .layout import SIZES

# --------------------------------------------------------------- image input


def load_gray(image) -> np.ndarray:
    """float32 grey image in [0, 255] from a path, PIL image or array."""
    if isinstance(image, (str, bytes)) or hasattr(image, "__fspath__"):
        from PIL import Image

        image = Image.open(image)
    if hasattr(image, "convert"):
        image = np.asarray(image.convert("L"))
    arr = np.asarray(image)
    if arr.ndim == 3:
        arr = arr[..., :3] @ np.array([0.299, 0.587, 0.114])
    return arr.astype(np.float32)


def _box_mean(img: np.ndarray, radius: int) -> np.ndarray:
    pad = np.pad(img, radius + 1, mode="edge").astype(np.float64)
    ii = pad.cumsum(0).cumsum(1)
    k = 2 * radius + 1
    s = ii[k:, k:] - ii[:-k, k:] - ii[k:, :-k] + ii[:-k, :-k]
    return (s / (k * k))[: img.shape[0], : img.shape[1]]


def binarize_adaptive(gray: np.ndarray) -> np.ndarray:
    # Window capped at ~65 px (like zxing's block binarizer): a window that
    # grows with the photo can exceed a small symbol on a dark page and pull
    # its threshold down.  Large symbols are covered by the detection pyramid.
    radius = max(7, min(32, min(gray.shape) // 16))
    mean = _box_mean(gray, radius)
    return gray < mean - 6.0


def binarize_otsu(gray: np.ndarray) -> np.ndarray:
    hist = np.bincount(np.clip(gray, 0, 255).astype(np.uint8).ravel(), minlength=256)
    total = hist.sum()
    cum = np.cumsum(hist)
    cum_mean = np.cumsum(hist * np.arange(256))
    w0 = cum / total
    w1 = 1 - w0
    with np.errstate(divide="ignore", invalid="ignore"):
        m0 = cum_mean / cum
        m1 = (cum_mean[-1] - cum_mean) / (total - cum)
        between = w0 * w1 * (m0 - m1) ** 2
    if not np.isfinite(between).any():
        return np.zeros(gray.shape, bool)
    t = int(np.nanargmax(between))
    return gray <= t


# ------------------------------------------------- connected components (runs)


@dataclass
class Component:
    rows: np.ndarray      # row of each run
    starts: np.ndarray    # first column of each run
    ends: np.ndarray      # one past the last column
    pixels: int

    def bbox(self) -> tuple[int, int, int, int]:
        return (int(self.rows.min()), int(self.starts.min()),
                int(self.rows.max()) + 1, int(self.ends.max()))


def components(mask: np.ndarray, min_side: int = 18) -> list[Component]:
    h, w = mask.shape
    padded = np.zeros((h, w + 2), dtype=np.int8)
    padded[:, 1:-1] = mask
    diff = np.diff(padded, axis=1)
    sr, sc = np.nonzero(diff == 1)
    er, ec = np.nonzero(diff == -1)
    # runs are emitted in row-major order for both arrays
    n_runs = len(sr)
    parent = list(range(n_runs))

    def find(a: int) -> int:
        root = a
        while parent[root] != root:
            root = parent[root]
        while parent[a] != root:
            parent[a], a = root, parent[a]
        return root

    row_start = np.searchsorted(sr, np.arange(h + 1)).tolist()
    starts, ends = sc.tolist(), ec.tolist()
    for y in range(1, h):
        a, a_end = row_start[y - 1], row_start[y]
        b, b_end = row_start[y], row_start[y + 1]
        while a < a_end and b < b_end:
            # 8-connectivity: [s1, e1) touches [s2, e2) if s1 <= e2 and s2 <= e1
            if starts[a] <= ends[b] and starts[b] <= ends[a]:
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[max(ra, rb)] = min(ra, rb)
            if ends[a] < ends[b]:
                a += 1
            else:
                b += 1
    roots = np.array([find(i) for i in range(n_runs)])
    order = np.argsort(roots, kind="stable")
    roots_sorted = roots[order]
    cuts = np.flatnonzero(np.diff(roots_sorted)) + 1
    out = []
    for group in np.split(order, cuts):
        if len(group) == 0:
            continue
        rows = sr[group]
        if rows.max() - rows.min() + 1 < min_side:
            continue
        s, e = sc[group], ec[group]
        if e.max() - s.min() < min_side:
            continue
        out.append(Component(rows, s, e, int((e - s).sum())))
    return out


# ------------------------------------------------------------------ geometry


def convex_hull(points: np.ndarray) -> np.ndarray:
    pts = sorted(set(map(tuple, points.tolist())))
    if len(pts) <= 2:
        return np.array(pts, dtype=float)

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return np.array(lower[:-1] + upper[:-1], dtype=float)


def component_hull(comp: Component) -> np.ndarray:
    """Hull of the component in (x, y) pixel-corner coordinates."""
    ys = comp.rows
    order = np.lexsort((comp.starts, ys))
    ys_s = ys[order]
    first = np.r_[True, ys_s[1:] != ys_s[:-1]]
    row_ids = ys_s[first]
    left = np.minimum.reduceat(comp.starts[order], np.flatnonzero(first))
    right = np.maximum.reduceat(comp.ends[order], np.flatnonzero(first))
    pts = np.concatenate([
        np.stack([left, row_ids], 1), np.stack([left, row_ids + 1], 1),
        np.stack([right, row_ids], 1), np.stack([right, row_ids + 1], 1),
    ])
    return convex_hull(pts)


def polygon_area(p: np.ndarray) -> float:
    x, y = p[:, 0], p[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def hull_quad(hull: np.ndarray) -> np.ndarray | None:
    """Four hull vertices spanning a near-maximal quadrilateral, clockwise
    in image coordinates (y down)."""
    if len(hull) < 4:
        return None
    centre = hull.mean(0)
    a = hull[np.argmax(((hull - centre) ** 2).sum(1))]
    c = hull[np.argmax(((hull - a) ** 2).sum(1))]
    d = c - a
    side = (hull[:, 0] - a[0]) * d[1] - (hull[:, 1] - a[1]) * d[0]
    if side.max() <= 0 or side.min() >= 0:
        return None
    b = hull[np.argmax(side)]
    e = hull[np.argmin(side)]
    quad = np.array([a, b, c, e], dtype=float)
    if polygon_area(quad) < 0:  # make clockwise on screen (positive with y down)
        quad = quad[::-1]
    return quad


def homography(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """3x3 H with dst ~ H @ src (least squares for more than four points)."""
    rows = []
    rhs = []
    for (x, y), (u, v) in zip(src, dst):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        rhs.append(u)
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        rhs.append(v)
    sol, *_ = np.linalg.lstsq(np.array(rows, float), np.array(rhs, float), rcond=None)
    return np.append(sol, 1.0).reshape(3, 3)


def apply_h(h: np.ndarray, x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    w = h[2, 0] * x + h[2, 1] * y + h[2, 2]
    return (h[0, 0] * x + h[0, 1] * y + h[0, 2]) / w, (h[1, 0] * x + h[1, 1] * y + h[1, 2]) / w


def sample(gray: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Bilinear sample at pixel-corner coordinates (pixel (i, j) covers
    [j, j+1) x [i, i+1), so its centre is (j + 0.5, i + 0.5))."""
    h, w = gray.shape
    xf = np.clip(x - 0.5, 0, w - 1.001)
    yf = np.clip(y - 0.5, 0, h - 1.001)
    x0 = xf.astype(int)
    y0 = yf.astype(int)
    fx = xf - x0
    fy = yf - y0
    g00 = gray[y0, x0]
    g01 = gray[y0, x0 + 1]
    g10 = gray[y0 + 1, x0]
    g11 = gray[y0 + 1, x0 + 1]
    return (g00 * (1 - fx) * (1 - fy) + g01 * fx * (1 - fy)
            + g10 * (1 - fx) * fy + g11 * fx * fy)


# ----------------------------------------------------------- frame templates


def _frame_template(n: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Module-centre coordinates (x, y) and expected darkness (+1/-1) of the
    frame and of the light quiet-zone ring just outside it."""
    xs, ys, ex = [], [], []
    for i in range(n):
        # left column (solid) and bottom row (solid)
        xs += [0.5, i + 0.5]
        ys += [i + 0.5, n - 0.5]
        ex += [1, 1]
        # top row and right column (timing; dark on even index from the TL/BR)
        if 0 < i < n - 1:
            xs += [i + 0.5, n - 0.5]
            ys += [0.5, i + 0.5]
            ex += [1 if i % 2 == 0 else -1, 1 if i % 2 == 0 else -1]
        # quiet zone ring, one module outside
        xs += [-0.5, i + 0.5, i + 0.5, n + 0.5]
        ys += [i + 0.5, -0.5, n + 0.5, i + 0.5]
        ex += [-1, -1, -1, -1]
    return np.array(xs), np.array(ys), np.array(ex, float)


_TEMPLATES = {n: _frame_template(n) for n in SIZES}


def frame_score(gray: np.ndarray, h: np.ndarray, n: int) -> float:
    xs, ys, ex = _TEMPLATES[n]
    px, py = apply_h(h, xs, ys)
    g = -sample(gray, px, py)
    g = g - g.mean()
    denom = np.sqrt((g * g).sum() * ((ex - ex.mean()) ** 2).sum())
    return float((g * (ex - ex.mean())).sum() / denom) if denom > 0 else 0.0


def corners_h(corners: np.ndarray, n: int) -> np.ndarray:
    """corners = TL, TR, BR, BL in image coordinates."""
    src = np.array([[0, 0], [n, 0], [n, n], [0, n]], float)
    return homography(src, corners)


# --------------------------------------------------------- edge refinement


def _side_rays(n: int):
    """For each side of a size-n frame: (positions along the side, edge
    points, outward normal), at modules whose frame cell is dark."""
    idx = np.arange(n) + 0.5
    timing = np.arange(n) % 2 == 0
    zeros, full = np.zeros(n), np.full(n, float(n))
    return {
        "left": (idx, np.stack([zeros, idx], 1), np.array([-1.0, 0.0])),
        "bottom": (idx, np.stack([idx, full], 1), np.array([0.0, 1.0])),
        "top": (idx[timing], np.stack([idx, zeros], 1)[timing], np.array([0.0, -1.0])),
        "right": (idx[timing], np.stack([full, idx], 1)[timing], np.array([1.0, 0.0])),
    }


def _intersect(l1, l2) -> np.ndarray | None:
    (p, d), (q, e) = l1, l2
    m = np.array([d, -e]).T
    if abs(np.linalg.det(m)) < 1e-9:
        return None
    s, _ = np.linalg.solve(m, q - p)
    return p + s * d


def _outer_envelope(u: np.ndarray, d: np.ndarray, tol: float):
    """Line d = a + b u through the outermost edge points (smallest depth).

    Rays that start on a light timing gap or a light data module find their
    first dark sample deeper inside; they lie on the inner side of the true
    edge and are trimmed away iteratively."""
    keep = np.ones(len(u), bool)
    coef = None
    for _ in range(6):
        if keep.sum() < 3:
            return None
        a = np.stack([np.ones(keep.sum()), u[keep]], 1)
        coef, *_ = np.linalg.lstsq(a, d[keep], rcond=None)
        resid = d - (coef[0] + coef[1] * u)
        new_keep = (resid <= tol) & (resid >= -4 * tol)
        if (new_keep == keep).all():
            break
        keep = new_keep
    return coef


def _fit_sides(gray, h, sides, depths, tol) -> np.ndarray | None:
    """sides: name -> (positions along side, edge points, outward normal) in
    the coordinates of h; depths ascend from outside (negative) to inside."""
    lines = {}
    for name, (u, pts, normal) in sides.items():
        px = pts[:, 0:1] - depths[None, :] * normal[0]
        py = pts[:, 1:2] - depths[None, :] * normal[1]
        prof = sample(gray, *apply_h(h, px, py))
        light = float(np.median(prof[:, :3]))
        dark = float(np.percentile(prof, 5))
        if light - dark < 12:
            return None
        thr = (light + dark) / 2
        us, ds = [], []
        for i in range(len(u)):
            idx = np.flatnonzero(prof[i] < thr)
            if len(idx) == 0 or idx[0] == 0:
                continue
            j = idx[0]
            v0, v1 = prof[i, j - 1], prof[i, j]
            frac = (v0 - thr) / (v0 - v1) if v0 != v1 else 0.5
            us.append(u[i])
            ds.append(depths[j - 1] + frac * (depths[j] - depths[j - 1]))
        if len(us) < 3:
            return None
        coef = _outer_envelope(np.array(us), np.array(ds), tol)
        if coef is None:
            return None
        ends = []
        for t in (u.min(), u.max()):
            base = pts[0] + (pts[-1] - pts[0]) * ((t - u[0]) / (u[-1] - u[0]))
            ends.append(base - (coef[0] + coef[1] * t) * normal)
        ends = np.array(ends)
        ix, iy = apply_h(h, ends[:, 0], ends[:, 1])
        lines[name] = (np.array([ix[0], iy[0]]), np.array([ix[1] - ix[0], iy[1] - iy[0]]))
    corners = [
        _intersect(lines["left"], lines["top"]),
        _intersect(lines["top"], lines["right"]),
        _intersect(lines["right"], lines["bottom"]),
        _intersect(lines["bottom"], lines["left"]),
    ]
    if any(c is None for c in corners):
        return None
    return np.array(corners)


def refine_corners(gray: np.ndarray, h: np.ndarray, n: int) -> np.ndarray | None:
    """Edge rays at every dark frame module of a size-n symbol."""
    return _fit_sides(gray, h, _side_rays(n), np.linspace(-1.2, 0.6, 37), 0.25)


# ------------------------------------------------------------- sampling


def _quad_fit(xs, ys, vals):
    a = np.stack([np.ones_like(xs), xs, ys, xs * xs, xs * ys, ys * ys], 1)
    coef, *_ = np.linalg.lstsq(a, vals, rcond=None)
    return coef


def _quad_eval(coef, xs, ys):
    return coef[0] + coef[1] * xs + coef[2] * ys + coef[3] * xs * xs + coef[4] * xs * ys + coef[5] * ys * ys


def sample_modules(gray: np.ndarray, h: np.ndarray, n: int):
    """Return (bits n x n, confidence n x n, contrast)."""
    # threshold surface from the frame (dark) and timing gaps + quiet zone (light)
    xs, ys, ex = _TEMPLATES[n]
    vals = sample(gray, *apply_h(h, xs, ys))
    dark, light = ex > 0, ex < 0
    sx, sy = xs / n - 0.5, ys / n - 0.5
    dcoef = _quad_fit(sx[dark], sy[dark], vals[dark])
    lcoef = _quad_fit(sx[light], sy[light], vals[light])
    # module centres, averaged over a small 3x3 patch
    offs = np.array([-0.18, 0.0, 0.18])
    cy, cx = np.mgrid[0:n, 0:n] + 0.5
    acc = np.zeros((n, n))
    for oy in offs:
        for ox in offs:
            ix, iy = apply_h(h, cx + ox, cy + oy)
            acc += sample(gray, ix, iy)
    acc /= 9
    nx, ny = cx / n - 0.5, cy / n - 0.5
    dlev = _quad_eval(dcoef, nx, ny)
    llev = _quad_eval(lcoef, nx, ny)
    thr = (dlev + llev) / 2
    half = np.maximum((llev - dlev) / 2, 1e-3)
    bits = (acc < thr).astype(np.uint8)
    conf = np.clip(np.abs(acc - thr) / half, 0, 1)
    return bits, conf, float(np.median(llev - dlev))


def equalized_modules(gray: np.ndarray, h: np.ndarray, n: int):
    """Second reading of the modules: a 3 x 3 linear equalizer learned per
    photo by least squares from the known frame and the quiet-zone ring.

    It absorbs what a fixed threshold cannot: phone sharpening halos, screen
    texture and blur that spill neighbouring modules into each other.
    Returns (bits, confidence) like sample_modules, or None."""
    pad = 2
    m = n + 2 * pad
    cy, cx = np.mgrid[-pad:n + pad, -pad:n + pad] + 0.5
    acc = np.zeros((m, m))
    for oy in (-0.18, 0.0, 0.18):
        for ox in (-0.18, 0.0, 0.18):
            acc += sample(gray, *apply_h(h, cx + ox, cy + oy))
    v = (acc / 9 - 128.0) / 128.0
    known = np.full((m, m), -1)
    known[:pad, :] = known[-pad:, :] = 0
    known[:, :pad] = known[:, -pad:] = 0
    for r in range(n):
        for c in range(n):
            if r == 0 or c == 0 or r == n - 1 or c == n - 1:
                known[r + pad, c + pad] = _frame_value(r, c, n)
    # 3 x 3 neighbourhood features for every interior position
    win = np.stack([v[1 + dr:m - 1 + dr, 1 + dc:m - 1 + dc]
                    for dr in (-1, 0, 1) for dc in (-1, 0, 1)], -1)
    feats = np.concatenate([win, np.ones(win.shape[:2] + (1,))], -1)
    k = known[1:-1, 1:-1]
    x, y = feats[k >= 0], k[k >= 0].astype(float)
    if len(y) < 40:
        return None
    w, *_ = np.linalg.lstsq(x, y, rcond=None)
    pred = (feats @ w)[pad - 1:pad - 1 + n, pad - 1:pad - 1 + n]
    return (pred > 0.5).astype(np.uint8), np.clip(np.abs(pred - 0.5) * 2, 0, 1)


def _frame_value(r: int, c: int, n: int) -> int:
    if c == 0 or r == n - 1:
        return 1
    if r == 0:
        return 1 if c % 2 == 0 else 0
    return 1 if r % 2 == 0 else 0


# ------------------------------------------------------------------ driver


@dataclass
class Detection:
    decoded: Decoded
    corners: np.ndarray  # TL, TR, BR, BL (image coordinates)


def _hypotheses(quad: np.ndarray):
    """Corner sets TL, TR, BR, BL for each choice of the L corner, with the
    fourth (top-right) corner from the hull and from a parallelogram."""
    for k in range(4):
        bl, tl, tr, br = (quad[(k + i) % 4] for i in range(4))
        yield np.array([tl, tr, br, bl])
        yield np.array([tl, tl + br - bl, br, bl])


# Size-free probes, in units of the symbol side: just inside the L (dark) and
# in the quiet zone outside every side (light).
_U = np.linspace(0.04, 0.96, 24)
_IN, _OUT = 0.008, -0.03
_SOLID_X = np.concatenate([np.full(24, _IN), _U, np.full(24, _OUT), _U, _U, np.full(24, 1 - _OUT)])
_SOLID_Y = np.concatenate([_U, np.full(24, 1 - _IN), _U, np.full(24, 1 - _OUT), np.full(24, _OUT), _U])
_SOLID_E = np.concatenate([np.ones(48), -np.ones(96)])


def _pearson(values: np.ndarray, expected: np.ndarray) -> float:
    g = -(values - values.mean())
    e = expected - expected.mean()
    denom = np.sqrt((g * g).sum() * (e * e).sum())
    return float((g * e).sum() / denom) if denom > 0 else 0.0


def solid_score(gray: np.ndarray, corners: np.ndarray) -> float:
    h = corners_h(corners, 1)
    return _pearson(sample(gray, *apply_h(h, _SOLID_X, _SOLID_Y)), _SOLID_E)


def timing_score(gray: np.ndarray, corners: np.ndarray, n: int) -> float:
    """Correlation of both timing tracks with their alternating pattern."""
    h = corners_h(corners, n)
    idx = np.arange(1, n - 1) + 0.5
    xs = np.concatenate([idx, np.full(n - 2, n - 0.5)])
    ys = np.concatenate([np.full(n - 2, 0.5), idx])
    alt = np.where(np.arange(1, n - 1) % 2 == 0, 1.0, -1.0)
    return _pearson(sample(gray, *apply_h(h, xs, ys)), np.concatenate([alt, alt]))


def refine_free(gray: np.ndarray, corners: np.ndarray) -> np.ndarray | None:
    """Size-independent refinement with dense rays across all four sides."""
    h = corners_h(corners, 1)
    u = np.linspace(0.02, 0.98, 97)
    zeros, ones = np.zeros_like(u), np.ones_like(u)
    sides = {
        "left": (u, np.stack([zeros, u], 1), np.array([-1.0, 0.0])),
        "bottom": (u, np.stack([u, ones], 1), np.array([0.0, 1.0])),
        "top": (u, np.stack([u, zeros], 1), np.array([0.0, -1.0])),
        "right": (u, np.stack([ones, u], 1), np.array([1.0, 0.0])),
    }
    return _fit_sides(gray, h, sides, np.linspace(-0.04, 0.035, 41), 0.004)


def locate(gray: np.ndarray, quad: np.ndarray):
    hyps = sorted(_hypotheses(quad), key=lambda c: -solid_score(gray, c))
    best = None
    for corners in hyps[:2]:
        if solid_score(gray, corners) < 0.5:
            continue
        for _ in range(4):
            refined = refine_free(gray, corners)
            if refined is None or solid_score(gray, refined) < solid_score(gray, corners) - 0.02:
                break
            corners = refined
        scores = sorted(((timing_score(gray, corners, n), n) for n in SIZES), reverse=True)
        t, n = scores[0]
        if t < 0.4:
            continue
        for _ in range(3):
            refined = refine_corners(gray, corners_h(corners, n), n)
            if refined is None:
                break
            if timing_score(gray, refined, n) + 0.02 < timing_score(gray, corners, n):
                break
            moved = np.abs(refined - corners).max()
            corners = refined
            if moved < 0.05:
                break
        total = frame_score(gray, corners_h(corners, n), n)
        if best is None or total > best[2]:
            best = (corners, n, total)
    if best is None or best[2] < 0.55:
        return None
    return best


def decode_at(gray: np.ndarray, corners: np.ndarray, n: int) -> Decoded | None:
    h = corners_h(corners, n)
    readings = [sample_modules(gray, h, n)[:2]]
    eq = equalized_modules(gray, h, n)
    if eq is not None:
        readings.append(eq)
    for bits, conf in readings:
        modules, confidence = bits.tolist(), conf.tolist()
        reads = [(read_bytes(modules, m), symbol_confidence(confidence, m), m) for m in (False, True)]
        result = decode_bytes(n, reads)
        if result is not None:
            return result
    return None


def candidate_quads(gray: np.ndarray, mask: np.ndarray, limit: int = 40):
    comps = components(mask)
    scored = []
    for comp in comps:
        y0, x0, y1, x1 = comp.bbox()
        bw, bh = x1 - x0, y1 - y0
        if max(bw, bh) > 6 * min(bw, bh):
            continue
        # a bare L frame (data modules not touching it) fills only ~5-9% of its box
        if comp.pixels < 0.03 * bw * bh:
            continue
        hull = component_hull(comp)
        quad = hull_quad(hull)
        if quad is None:
            continue
        ha = polygon_area(hull)
        if ha <= 0 or polygon_area(quad) < 0.75 * ha:
            continue
        scored.append((comp.pixels, quad))
    scored.sort(key=lambda t: -t[0])
    return [q for _, q in scored[:limit]]


def read(image, max_side: int = 1600) -> list[Detection]:
    """Decode every PASCAL-MDS symbol found in an image.

    Detection runs on an image pyramid (the working image, then halves while
    the long side stays >= 320 px): fine screen or print texture can break a
    large symbol's frame into pieces at full resolution, and a coarser level
    joins them again.  Symbols already decoded are skipped."""
    from PIL import Image

    gray = load_gray(image)
    base = max(1.0, max(gray.shape) / max_side)
    found: list[Detection] = []
    scale = base
    while max(gray.shape) / scale >= 320 or scale == base:
        if scale == 1.0:
            level = gray
        else:
            size = (round(gray.shape[1] / scale), round(gray.shape[0] / scale))
            level = np.asarray(Image.fromarray(gray).resize(size, Image.BOX), dtype=np.float32)
        for binarize in (binarize_adaptive, binarize_otsu):
            for quad in candidate_quads(level, binarize(level)):
                if any(_inside(quad.mean(0) * scale, d.corners) for d in found):
                    continue
                located = locate(level, quad)
                if located is None:
                    continue
                corners, n, _ = located
                decoded = decode_at(level, corners, n)
                if decoded is not None:
                    found.append(Detection(decoded, corners * scale))
        scale *= 2
        if scale > base * 4:
            break
    return found


def _inside(p: np.ndarray, poly: np.ndarray) -> bool:
    sign = None
    for i in range(4):
        a, b = poly[i], poly[(i + 1) % 4]
        cross = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
        s = cross > 0
        if sign is None:
            sign = s
        elif s != sign:
            return False
    return True


def read_one(image) -> Decoded:
    results = read(image)
    if not results:
        from .codec import DecodeError

        raise DecodeError("no PASCAL-MDS symbol decoded")
    return results[0].decoded
