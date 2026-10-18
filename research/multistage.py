"""Does a practical receiver reach the joint-decoding rates of capacity.py?

Multistage decoding over four interleaved sub-lattices (cosets of 2Z x 2Z):
stage k decodes coset k from the grey image plus the already-decoded modules
of cosets < k, each coset protected by its own IRA-LDPC code.  The per-stage
detector is a small MLP posterior q(x | window, known neighbours) whose
log-odds feed belief propagation.

By the chain rule the stage rates sum to the joint information rate, so with
good codes the total approaches the "joint" curve of capacity.py.  Grid
positions are assumed known to the receiver up to the channel's grid_error.
"""

from __future__ import annotations

import argparse
import json
import time

import numpy as np
from sklearn.neural_network import MLPClassifier

from capacity import NEIGH, Channel, bilinear, render, OFFS
from ldpc import Decoder, encode, make_ira

STAGES = [(0, 0), (1, 1), (0, 1), (1, 0)]  # coset (r % 2, c % 2) in decoding order


def known_offsets(stage: int) -> list[tuple[int, int]]:
    """Neighbour offsets whose coset is decoded before this stage."""
    r0, c0 = STAGES[stage]
    done = set(STAGES[:stage])
    return [(dr, dc) for dr, dc in NEIGH if ((r0 + dr) % 2, (c0 + dc) % 2) in done]


def features(img, cx, cy, rows, cols, ch, rng):
    px = cx[cols] + (rng.normal(0, ch.grid_error, len(cols)) if ch.grid_error else 0)
    py = cy[rows] + (rng.normal(0, ch.grid_error, len(rows)) if ch.grid_error else 0)
    grid = [bilinear(img, px + ox * ch.pitch, py + oy * ch.pitch) for oy in OFFS for ox in OFFS]
    return np.hstack([(np.stack(grid, 1) - 125.0) / 100.0, np.stack([px % 1.0, py % 1.0], 1)])


def stage_rows(side: int, stage: int):
    r0, c0 = STAGES[stage]
    r = np.arange(3 + ((r0 - 3) % 2), side - 3, 2)
    c = np.arange(3 + ((c0 - 3) % 2), side - 3, 2)
    rr, cc = np.meshgrid(r, c, indexing="ij")
    return rr.ravel(), cc.ravel()


def train_stage_models(ch: Channel, side: int, images: int, seed: int):
    rng = np.random.default_rng(seed)
    data = [([], []) for _ in STAGES]
    for _ in range(images):
        mods = rng.integers(0, 2, (side, side))
        img, cx, cy = render(mods, ch, rng)
        for k in range(4):
            rr, cc = stage_rows(side, k)
            f = features(img, cx, cy, rr, cc, ch, rng)
            nb = [mods[rr + dr, cc + dc] for dr, dc in known_offsets(k)]
            x = np.hstack([f, np.stack(nb, 1)]) if nb else f
            data[k][0].append(x)
            data[k][1].append(mods[rr, cc])
    models, rates = [], []
    for k in range(4):
        x = np.vstack(data[k][0])
        y = np.concatenate(data[k][1])
        n = len(y)
        te = slice(0, n // 5)
        tr = slice(n // 5, n)
        m = MLPClassifier(hidden_layer_sizes=(96, 64), max_iter=150, early_stopping=True,
                          n_iter_no_change=10, random_state=seed + k, batch_size=512, learning_rate_init=2e-3)
        m.fit(x[tr], y[tr])
        p = m.predict_proba(x[te])[np.arange(n // 5), y[te]]
        rates.append(float(1 + np.mean(np.log2(np.clip(p, 1e-12, 1)))))
        models.append(m)
    return models, rates


def llr_from(model, x):
    p1 = np.clip(model.predict_proba(x)[:, 1], 1e-9, 1 - 1e-9)
    return np.log((1 - p1) / p1)  # > 0 means bit 0


def simulate(ch: Channel, side: int, models, codes, trials: int, seed: int):
    rng = np.random.default_rng(seed)
    decs = [Decoder(c) for c in codes]
    ok = 0
    for _ in range(trials):
        mods = rng.integers(0, 2, (side, side))  # filler outside the coded cosets
        cws = []
        for k in range(4):
            rr, cc = stage_rows(side, k)
            u = rng.integers(0, 2, codes[k].k)
            cw = encode(codes[k], u)
            perm = np.random.default_rng(100 + k).permutation(len(rr))  # spread each codeword
            mods[rr[perm], cc[perm]] = cw
            cws.append((rr[perm], cc[perm], cw))
        img, cx, cy = render(mods, ch, rng)
        # uncoded border modules act as known pilots; coded ones start unknown
        est = mods.copy()
        for rr, cc, _ in cws:
            est[rr, cc] = -1
        good = True
        for k in range(4):
            rr, cc, cw = cws[k]
            f = features(img, cx, cy, rr, cc, ch, rng)
            nb = [est[rr + dr, cc + dc] for dr, dc in known_offsets(k)]
            x = np.hstack([f, np.stack(nb, 1)]) if nb else f
            bits, conv = decs[k].decode(llr_from(models[k], x), iters=80)
            if not conv or not np.array_equal(bits, cw):
                good = False
                break
            est[rr, cc] = bits
        ok += good
    return ok / trials


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pitch", type=float, default=1.2)
    ap.add_argument("--blur", type=float, default=0.7)
    ap.add_argument("--realistic", action="store_true")
    ap.add_argument("--side", type=int, default=104)
    ap.add_argument("--train-images", type=int, default=40)
    ap.add_argument("--trials", type=int, default=20)
    ap.add_argument("--backoffs", default="0.04,0.07,0.10,0.14")
    a = ap.parse_args()
    ch = (Channel(a.pitch, a.blur, 6.0, 75, 2, 0.25, 0.1) if a.realistic
          else Channel(a.pitch, a.blur))
    t0 = time.time()
    models, rates = train_stage_models(ch, a.side, a.train_images, seed=11)
    print(f"channel {ch}\nstage information rates (bits/module): " + ", ".join(f"{r:.3f}" for r in rates)
          + f"  mean {np.mean(rates):.3f}   [{time.time() - t0:.0f}s]", flush=True)
    n_stage = len(stage_rows(a.side, 0)[0])
    results = []
    for back in map(float, a.backoffs.split(",")):
        codes = []
        for k, r in enumerate(rates):
            rate = max(0.05, min(0.97, r - back))
            kk = int(round(rate * n_stage))
            codes.append(make_ira(kk, n_stage - kk, dv=3, seed=k))
        succ = simulate(ch, a.side, models, codes, a.trials, seed=99)
        info = sum(c.k for c in codes)
        area = (len(stage_rows(a.side, 0)[0]) * 4) * a.pitch ** 2
        dens = info / area
        results.append({"backoff": back, "success": succ, "bits_per_module": info / (4 * n_stage),
                         "bits_per_px2": dens})
        print(f"backoff {back:.2f}: rate {info / (4 * n_stage):.3f} bits/module = {dens:.3f} bits/px2, "
              f"frames decoded {succ:.0%}", flush=True)
    print(json.dumps({"channel": ch.__dict__, "stage_rates": rates, "results": results}))


if __name__ == "__main__":
    main()
