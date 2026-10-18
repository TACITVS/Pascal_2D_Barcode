"""How many bits per camera pixel can a printed 2D code carry?

Research step 1 (see research/README.md).  We simulate the same print ->
camera channel as bench/benchmark.py, but with random module patterns on an
axis-aligned grid of pitch p camera pixels per module, and estimate the
information rate per module R(p) that a code could achieve with each kind of
receiver.  Density = R(p) / p^2 bits per camera pixel^2.

Estimators (all rates are for i.i.d. uniform inputs, so they lower-bound the
channel capacity):

* hard  - threshold each module separately, then an ideal code on the
          resulting discrete channel (how QR and PASCAL-MDS v1 read).
* soft  - each module from a window of grey samples; ISI treated as noise.
* joint - chain rule: module i from its window plus the already-decoded
          causal neighbours (raster order).  Achievable by multistage /
          decision-feedback decoding with ideal codes.
* genie - every neighbour known (an upper reference for joint decoding).
* mfb   - binary only, no JPEG: matched-filter bound, an exact upper bound on
          the binary symmetric information rate of the linear Gaussian part.

Bound used for soft/joint/genie: for any model q, I(X; Y) >= H(X) - CE(q),
CE = E[-log2 q(x | y)], estimated on held-out data.  A better model only
tightens the bound; the bound never depends on the model being "right".
For joint: I(X;Y)/n = (1/n) sum_i I(X_i; Y | X_<i) >= I(X_i; Y_window, X_causal)
for i.i.d. X, by the chain rule and data processing.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict, dataclass
from multiprocessing import Pool
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from sklearn.neural_network import MLPClassifier  # noqa: E402

DARK, LIGHT = 25.0, 225.0
SS = 8  # optical supersampling per camera pixel


@dataclass(frozen=True)
class Channel:
    pitch: float        # camera pixels per module
    blur: float = 0.7   # optical blur sigma, camera pixels (before pixel integration)
    noise: float = 4.0  # sensor noise sigma, grey levels
    jpeg: int = 75      # 0 = no compression
    levels: int = 2     # reflectance levels per module
    blur_jitter: float = 0.0  # per-image blur varies uniformly by +-this fraction, unknown to the receiver
    grid_error: float = 0.0   # receiver's module-centre estimate is off by N(0, this) camera px


def render(mods: np.ndarray, ch: Channel, rng: np.random.Generator):
    """mods: (R, C) ints in [0, levels).  Returns camera image and the
    camera-pixel coordinates (x, y) of every module centre."""
    rows, cols = mods.shape
    phase = rng.uniform(0, 1, 2)  # sub-pixel grid offset, in camera pixels
    w = int(np.ceil(cols * ch.pitch + 2))
    h = int(np.ceil(rows * ch.pitch + 2))
    xs = (np.arange(w * SS) + 0.5) / SS - phase[0]
    ys = (np.arange(h * SS) + 0.5) / SS - phase[1]
    ci = np.clip(np.floor(xs / ch.pitch).astype(int), 0, cols - 1)
    ri = np.clip(np.floor(ys / ch.pitch).astype(int), 0, rows - 1)
    shade = LIGHT - (LIGHT - DARK) * mods / (ch.levels - 1)
    hi = shade[ri[:, None], ci[None, :]].astype(np.float32)
    blur = ch.blur * (1 + rng.uniform(-ch.blur_jitter, ch.blur_jitter))
    if blur > 0:
        hi = cv2.GaussianBlur(hi, (0, 0), blur * SS)
    img = cv2.resize(hi, (w, h), interpolation=cv2.INTER_AREA).astype(np.float64)
    img += rng.normal(0, ch.noise, img.shape)
    img = np.clip(img, 0, 255)
    if ch.jpeg:
        ok, enc = cv2.imencode(".jpg", img.astype(np.uint8), [cv2.IMWRITE_JPEG_QUALITY, ch.jpeg])
        img = cv2.imdecode(enc, cv2.IMREAD_GRAYSCALE).astype(np.float64)
    cx = phase[0] + (np.arange(cols) + 0.5) * ch.pitch
    cy = phase[1] + (np.arange(rows) + 0.5) * ch.pitch
    render.last_blur = blur  # the blur actually applied (for diagnostics only)
    return img, cx, cy


def bilinear(img, x, y):
    x = np.clip(x - 0.5, 0, img.shape[1] - 1.001)
    y = np.clip(y - 0.5, 0, img.shape[0] - 1.001)
    x0, y0 = x.astype(int), y.astype(int)
    fx, fy = x - x0, y - y0
    return (img[y0, x0] * (1 - fx) * (1 - fy) + img[y0, x0 + 1] * fx * (1 - fy)
            + img[y0 + 1, x0] * (1 - fx) * fy + img[y0 + 1, x0 + 1] * fx * fy)


OFFS = np.array([-1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5])
NEIGH = [(dr, dc) for dr in range(-2, 3) for dc in range(-2, 3) if (dr, dc) != (0, 0)]
CAUSAL = [(dr, dc) for dr, dc in NEIGH if dr < 0 or (dr == 0 and dc < 0)]


def dataset(ch: Channel, n_target: int, rng: np.random.Generator):
    """Features for modules at least 2 modules from the image edge."""
    side = max(24, int(360 / ch.pitch))
    feats, nbrs, labels, centre = [], [], [], []
    count = 0
    while count < n_target:
        mods = rng.integers(0, ch.levels, (side, side))
        img, cx, cy = render(mods, ch, rng)
        r = np.arange(3, side - 3)
        rr, cc = np.meshgrid(r, r, indexing="ij")
        rr, cc = rr.ravel(), cc.ravel()
        px = cx[cc] + rng.normal(0, ch.grid_error, len(cc)) if ch.grid_error else cx[cc]
        py = cy[rr] + rng.normal(0, ch.grid_error, len(rr)) if ch.grid_error else cy[rr]
        grid = [bilinear(img, px + ox * ch.pitch, py + oy * ch.pitch) for oy in OFFS for ox in OFFS]
        f = (np.stack(grid, 1) - 125.0) / 100.0
        frac = np.stack([px % 1.0, py % 1.0], 1)
        feats.append(np.hstack([f, frac]))
        centre.append(bilinear(img, px, py))
        nbrs.append(np.stack([mods[rr + dr, cc + dc] for dr, dc in NEIGH], 1))
        labels.append(mods[rr, cc])
        count += len(rr)
    return (np.vstack(feats)[:n_target], np.vstack(nbrs)[:n_target],
            np.concatenate(labels)[:n_target], np.concatenate(centre)[:n_target])


def entropy_rate_from_confusion(conf: np.ndarray) -> float:
    """I(X; X_hat) in bits for uniform X from a count matrix conf[x, xhat]."""
    p = conf / conf.sum()
    px = p.sum(1, keepdims=True)
    py = p.sum(0, keepdims=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        t = p * np.log2(p / (px * py))
    return float(np.nansum(t))


def _nll(model, x, y):
    prob = model.predict_proba(x)
    col = np.searchsorted(model.classes_, y)
    return -np.log2(np.clip(prob[np.arange(len(y)), col], 1e-12, 1.0))


def ce_rate(xtr, ytr, xte, yte, levels: int, seed: int) -> tuple[float, float]:
    """H(X) - CE on held-out test data, with a standard error.  Two models
    are trained; the one with lower loss on a separate validation split is
    evaluated on the test split (so the selection does not bias the bound)."""
    nval = len(ytr) // 8
    best = None
    for s, lr in ((seed, 2e-3), (seed + 1, 1e-3)):
        model = MLPClassifier(hidden_layer_sizes=(96, 64), max_iter=150, early_stopping=True,
                              n_iter_no_change=10, random_state=s, batch_size=512, learning_rate_init=lr)
        model.fit(xtr[nval:], ytr[nval:])
        val = _nll(model, xtr[:nval], ytr[:nval]).mean()
        if best is None or val < best[0]:
            best = (val, model)
    nll = _nll(best[1], xte, yte)
    return float(np.log2(levels) - nll.mean()), float(nll.std() / np.sqrt(len(nll)))


def matched_filter_bound(ch: Channel, rng: np.random.Generator, trials: int = 64) -> float:
    """Binary inputs, linear Gaussian channel (no JPEG): with every other
    module known, module i is BPSK with amplitude ||d||/2 in noise sigma."""
    zn = np.random.default_rng(1).normal(size=200_000)
    caps = []
    for _ in range(trials):
        seed = int(rng.integers(1 << 31))
        mods = np.zeros((7, 7), int)
        a, *_ = render(mods, Channel(ch.pitch, ch.blur, 0.0, 0, 2), np.random.default_rng(seed))
        mods[3, 3] = 1
        b, *_ = render(mods, Channel(ch.pitch, ch.blur, 0.0, 0, 2), np.random.default_rng(seed))
        amp = np.sqrt(((a - b) ** 2).sum()) / 2
        snr_term = 2 * amp * (amp + ch.noise * zn) / ch.noise ** 2
        caps.append(1 - np.mean(np.logaddexp(0, -snr_term)) / np.log(2))
    return float(np.mean(caps))


def run_config(args):
    ch, n_train, n_test, seed = args
    rng = np.random.default_rng(seed)
    t0 = time.time()
    f, nb, y, centre = dataset(ch, n_train + n_test, rng)
    tr, te = slice(0, n_train), slice(n_train, n_train + n_test)
    out = {"channel": asdict(ch)}
    # hard decisions on the centre sample (nearest level)
    levels = LIGHT - (LIGHT - DARK) * np.arange(ch.levels) / (ch.levels - 1)
    xhat = np.argmin(np.abs(centre[te, None] - levels[None, :]), 1)
    conf = np.zeros((ch.levels, ch.levels))
    np.add.at(conf, (y[te], xhat), 1)
    out["hard"] = entropy_rate_from_confusion(conf)
    nb_scaled = nb / max(1, ch.levels - 1)
    cidx = [NEIGH.index(c) for c in CAUSAL]
    for name, X in (("soft", f), ("joint", np.hstack([f, nb_scaled[:, cidx]])),
                    ("genie", np.hstack([f, nb_scaled]))):
        rate, se = ce_rate(X[tr], y[tr], X[te], y[te], ch.levels, seed)
        out[name] = max(0.0, rate)
        out[name + "_se"] = se
    # More side information never lowers I, so each bound also bounds the larger sets.
    out["joint"] = max(out["joint"], out["soft"])
    out["genie"] = max(out["genie"], out["joint"])
    if ch.levels == 2:
        out["mfb"] = matched_filter_bound(ch, rng)
    out["seconds"] = round(time.time() - t0, 1)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pitches", default="0.6,0.8,1.0,1.2,1.5,2.0,2.5")
    ap.add_argument("--blurs", default="0.7,1.2,2.0")
    ap.add_argument("--levels", default="2,4")
    ap.add_argument("--noises", default="4")
    ap.add_argument("--realistic", action="store_true",
                    help="also run noise x1.5, blur jitter 25%%, grid error 0.1 px")
    ap.add_argument("--train", type=int, default=120_000)
    ap.add_argument("--test", type=int, default=40_000)
    ap.add_argument("--out", default=str(Path(__file__).parent / "capacity_results.json"))
    a = ap.parse_args()
    # Results are appended to <out>.jsonl as each configuration finishes, and
    # configurations already present there are skipped, so a run can resume.
    partial = Path(a.out).with_suffix(".jsonl")
    done = []
    if partial.exists():
        done = [json.loads(line) for line in partial.read_text().splitlines() if line.strip()]
    done_keys = {json.dumps(r["channel"], sort_keys=True) for r in done}
    jobs = []
    for lv in map(int, a.levels.split(",")):
        for nz in map(float, a.noises.split(",")):
            for b in map(float, a.blurs.split(",")):
                for p in map(float, a.pitches.split(",")):
                    seed = int(1000 * p) + 7 * lv + int(100 * b) + int(10 * nz)
                    jobs.append((Channel(pitch=p, blur=b, noise=nz, levels=lv), a.train, a.test, seed))
                    if a.realistic:
                        jobs.append((Channel(pitch=p, blur=b, noise=1.5 * nz, levels=lv, blur_jitter=0.25,
                                             grid_error=0.1), a.train, a.test, seed + 1))
    jobs = [j for j in jobs if json.dumps(asdict(j[0]), sort_keys=True) not in done_keys]
    print(f"{len(done)} configurations already done, {len(jobs)} to run", flush=True)
    results = list(done)
    with Pool() as pool, partial.open("a") as log:
        for r in pool.imap_unordered(run_config, jobs):
            log.write(json.dumps(r) + "\n")
            log.flush()
            c = r["channel"]
            dens = {k: r[k] / c["pitch"] ** 2 for k in ("hard", "soft", "joint", "genie", "mfb") if k in r}
            tag = "real" if c["grid_error"] else "ideal"
            print(f"{tag:5s} L={c['levels']} noise={c['noise']} blur={c['blur']} p={c['pitch']:.1f}  " +
                  "  ".join(f"{k}={r[k]:.3f}" for k in ("hard", "soft", "joint", "genie", "mfb") if k in r) +
                  "   bits/px2: " + " ".join(f"{k}={v:.3f}" for k, v in dens.items()) +
                  f"  ({r['seconds']}s)", flush=True)
            results.append(r)
    results.sort(key=lambda r: tuple(r["channel"][k] for k in ("grid_error", "levels", "noise", "blur", "pitch")))
    Path(a.out).write_text(json.dumps(results, indent=1))
    print("wrote", a.out)


if __name__ == "__main__":
    main()
