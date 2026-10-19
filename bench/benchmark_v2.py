"""Smallest readable printed width: QR vs PASCAL-MDS v1 vs v2 levels A/B/C.

Same simulated phone photos as benchmark.py (rotation, perspective tilt,
lighting gradient, blur, noise, JPEG 75, clutter outside each code's quiet
zone).  For every system, payload and blur, widths are tried in increasing
order (16 photos each) until two consecutive widths decode >= 90%; the first
of those is the smallest readable width.  Results append to
bench/out/v2_widths.jsonl, so an interrupted run resumes.

    python bench/benchmark_v2.py [--trials 16]
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import zlib
from multiprocessing import Pool
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "research" / "v2"))
sys.path.insert(0, str(HERE.parent / "research"))

import benchmark as b  # noqa: E402

random.seed(7)
TEXT_300 = ("Meeting notes 18 Oct: the new barcode reads at half the printed size of a QR Code in simulation. "
            "Next: field tests with printed sheets at 0.5, 1, 1.5 and 2 m, normal room light, three phones. "
            "Contact Jane Doe (jane.doe@example.com, +1-555-0100) for the test kit; budget code PX-2207.")
PAYLOADS = {
    "URL (53 B)": b.PAYLOADS["URL (53 B)"],
    "contact (118 B)": b.PAYLOADS["contact (118 B)"],
    "notes (300 B)": TEXT_300[:300],
    "binary (500 B)": bytes(random.randrange(256) for _ in range(500)),
}
SYSTEMS = ("QR", "PASCAL", "V2-A", "V2-B", "V2-C")
WIDTHS = [24, 30, 36, 44, 52, 62, 75, 90, 110, 135, 165, 200, 245, 300, 370, 450, 550, 670]


def as_bytes(p):
    return p if isinstance(p, bytes) else p.encode()


def matrix(system: str, payload):
    if system.startswith("V2"):
        import dense

        _, grid = dense.encode(payload, system[-1])
        return grid, dense.QUIET
    if system == "QR":
        import segno

        q = segno.make_qr(payload, error="m", boost_error=False)
        return np.array([list(r) for r in q.matrix], dtype=np.uint8), 4
    from pascal_mds import encode

    return np.array(encode(payload, "M").modules, dtype=np.uint8), 2


def decodes(system: str, img, payload) -> bool:
    want = as_bytes(payload)
    if system == "QR":
        import zxingcpp

        return any(r.bytes == want for r in zxingcpp.read_barcodes(img, formats=zxingcpp.BarcodeFormat.QRCode))
    if system == "PASCAL":
        from pascal_mds.reader import read

        return any(d.decoded.data == want for d in read(img))
    import reader2

    return any(r.data == want for r in reader2.read(img, levels=system[-1]))


_CACHE: dict = {}


def job(args):
    system, name, width, blur, seed = args
    key = (system, name)
    if key not in _CACHE:
        _CACHE[key] = matrix(system, PAYLOADS[name])
    grid, quiet = _CACHE[key]
    rng = np.random.default_rng(seed)
    img = b.capture(grid, quiet, b.Condition(width=float(width), blur=blur), rng)
    return decodes(system, img, PAYLOADS[name])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=16)
    ap.add_argument("--blurs", default="0.7,1.2,2.0")
    a = ap.parse_args()
    out = HERE / "out" / "v2_widths.jsonl"
    out.parent.mkdir(exist_ok=True)
    done = set()
    if out.exists():
        for line in out.read_text().splitlines():
            r = json.loads(line)
            done.add((r["system"], r["payload"], r["blur"]))
    with Pool() as pool, out.open("a") as log:
        for blur in map(float, a.blurs.split(",")):
            for name in PAYLOADS:
                for system in SYSTEMS:
                    if (system, name, blur) in done:
                        continue
                    try:
                        grid, _ = matrix(system, PAYLOADS[name])
                        modules = grid.shape[1]
                    except ValueError:
                        rec = {"system": system, "payload": name, "blur": blur, "modules": None,
                               "rates": {}, "min_width": None, "note": "payload does not fit"}
                        log.write(json.dumps(rec) + "\n")
                        log.flush()
                        print(f"{blur} {name:16s} {system:7s} does not fit", flush=True)
                        continue
                    rates, ok_run, min_w = {}, 0, None
                    for w in WIDTHS:
                        jobs = [(system, name, w, blur, zlib.crc32(repr((name, w, blur, t)).encode()))
                                for t in range(a.trials)]
                        r = sum(pool.map(job, jobs)) / a.trials
                        rates[w] = r
                        if r >= 0.9:
                            ok_run += 1
                            if min_w is None:
                                min_w = w
                            if ok_run >= 2:
                                break
                        else:
                            ok_run, min_w = 0, None
                    rec = {"system": system, "payload": name, "blur": blur, "modules": modules,
                           "rates": rates, "min_width": min_w}
                    log.write(json.dumps(rec) + "\n")
                    log.flush()
                    print(f"{blur} {name:16s} {system:7s} {modules:>3}x{modules:<3} min width {min_w}  "
                          + " ".join(f"{w}:{r:.2f}" for w, r in rates.items()), flush=True)


if __name__ == "__main__":
    main()
