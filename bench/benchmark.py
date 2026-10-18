"""PASCAL-MDS vs QR Code vs Data Matrix under simulated phone-camera capture.

Requires: numpy, opencv-python-headless, segno, zxing-cpp (bench-only deps).

    python bench/benchmark.py [--trials 30] [--out bench/out]

Every symbology encodes the same payload at a comparable error-correction
level (QR "M", PASCAL-MDS "M"; Data Matrix has one fixed level) and is printed
at the SAME physical symbol width (quiet zone excluded, which is conservative
for PASCAL-MDS: QR's required quiet zone is twice as wide).  Each simulated
photo applies random rotation, perspective, lighting gradient, contrast loss,
optical blur, sensor noise and JPEG compression; clutter is placed outside
each symbology's own required quiet zone.  QR and Data Matrix are decoded by
zxing-cpp; PASCAL-MDS by pascal_mds.reader.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import zlib
from dataclasses import dataclass
from multiprocessing import Pool
from pathlib import Path

import cv2
import numpy as np
import segno
import zxingcpp

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pascal_mds import encode  # noqa: E402
from pascal_mds.reader import read  # noqa: E402

PAYLOADS = {
    "short URL (24 B)": "https://example.com/menu",
    "URL (53 B)": "https://www.example.com/products/item?id=12345&ref=qr",
    "Wi-Fi (52 B)": "WIFI:S:HomeNetwork;T:WPA;P:correct-horse-battery;;",
    "contact (118 B)": "BEGIN:VCARD\nVERSION:3.0\nN:Doe;Jane\nTEL:+1-555-0100\n"
                       "EMAIL:jane.doe@example.com\nURL:https://jane.example\nEND:VCARD",
}
SYSTEMS = ("QR", "DataMatrix", "PASCAL")
QUIET = {"QR": 4, "DataMatrix": 1, "PASCAL": 2}


def matrix_for(system: str, text: str) -> np.ndarray:
    if system == "QR":
        q = segno.make_qr(text, error="m", boost_error=False)
        return np.array([list(r) for r in q.matrix], dtype=np.uint8)
    if system == "DataMatrix":
        bc = zxingcpp.create_barcode(text, zxingcpp.BarcodeFormat.DataMatrix)
        img = np.array(bc.to_image(scale=1, add_quiet_zones=False))
        return (img < 128).astype(np.uint8)
    return np.array(encode(text, "M").modules, dtype=np.uint8)


@dataclass(frozen=True)
class Condition:
    width: float = 160.0      # printed symbol width in camera pixels
    blur: float = 0.7         # Gaussian sigma, camera pixels
    noise: float = 4.0
    tilt: float = 0.08        # corner jitter as a fraction of the width
    damage: float = 0.0       # fraction of symbol area covered by blotches
    jpeg: int = 75


def capture(matrix: np.ndarray, quiet: int, cond: Condition, rng: np.random.Generator) -> np.ndarray:
    rows, cols = matrix.shape
    k = 8  # source pixels per module
    margin = int(0.7 * max(rows, cols)) + quiet
    src = np.full(((rows + 2 * margin) * k, (cols + 2 * margin) * k), 225, np.uint8)
    # clutter outside the required quiet zone
    for _ in range(14):
        h, w = rng.integers(k, 6 * k, 2)
        y, x = rng.integers(0, src.shape[0] - h), rng.integers(0, src.shape[1] - w)
        qy0, qy1 = (margin - quiet) * k, (margin + rows + quiet) * k
        qx0, qx1 = (margin - quiet) * k, (margin + cols + quiet) * k
        if y + h > qy0 and y < qy1 and x + w > qx0 and x < qx1:
            continue
        src[y:y + h, x:x + w] = rng.integers(20, 120)
    sym = np.where(matrix == 1, 25, 225).astype(np.uint8)
    sym = np.kron(sym, np.ones((k, k), np.uint8))
    src[margin * k:(margin + rows) * k, margin * k:(margin + cols) * k] = sym
    if cond.damage > 0:
        area = rows * cols * k * k
        covered = 0.0
        while covered < cond.damage * area:
            rad = rng.uniform(0.8, 2.5) * k
            cy = margin * k + rng.uniform(0, rows * k)
            cx = margin * k + rng.uniform(0, cols * k)
            colour = int(rng.choice([25, 225, 128]))
            cv2.circle(src, (int(cx), int(cy)), int(rad), colour, -1)
            covered += np.pi * rad * rad
    # camera geometry: symbol width -> cond.width px, random rotation + tilt
    ss = 3
    scale = cond.width / (cols * k)
    canvas = int((cols + 2 * margin) * k * scale * 1.15)
    centre = np.array([canvas / 2, canvas / 2])
    ang = rng.uniform(0, 2 * np.pi)
    rot = np.array([[np.cos(ang), -np.sin(ang)], [np.sin(ang), np.cos(ang)]])
    sx, sy = src.shape[1], src.shape[0]
    corners = np.array([[0, 0], [sx, 0], [sx, sy], [0, sy]], float)
    dst = (corners - [sx / 2, sy / 2]) * scale @ rot.T + centre
    dst += rng.uniform(-1, 1, (4, 2)) * cond.tilt * cond.width
    hmat = cv2.getPerspectiveTransform(corners.astype(np.float32), (dst * ss).astype(np.float32))
    big = cv2.warpPerspective(src, hmat, (canvas * ss, canvas * ss), flags=cv2.INTER_AREA, borderValue=215)
    img = cv2.resize(big, (canvas, canvas), interpolation=cv2.INTER_AREA).astype(np.float32)
    # lighting: gradient and contrast loss
    yy, xx = np.mgrid[0:canvas, 0:canvas] / canvas
    gain = 1.0 - rng.uniform(0, 0.35) * (rng.uniform(-1, 1) * xx + rng.uniform(-1, 1) * yy + 1) / 2
    img = img * gain
    if cond.blur > 0:
        img = cv2.GaussianBlur(img, (0, 0), cond.blur)
    img += rng.normal(0, cond.noise, img.shape)
    img = np.clip(img, 0, 255).astype(np.uint8)
    ok, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, cond.jpeg])
    return cv2.imdecode(enc, cv2.IMREAD_GRAYSCALE)


def decodes(system: str, img: np.ndarray, text: str) -> bool:
    if system == "PASCAL":
        return any(d.decoded.data == text.encode() for d in read(img))
    fmt = zxingcpp.BarcodeFormat.QRCode if system == "QR" else zxingcpp.BarcodeFormat.DataMatrix
    return any(r.bytes == text.encode() for r in zxingcpp.read_barcodes(img, formats=fmt))


def _job(args):
    system, name, cond, seed = args
    rng = np.random.default_rng(seed)
    text = PAYLOADS[name]
    img = capture(_MATRICES[(system, name)], QUIET[system], cond, rng)
    return decodes(system, img, text)


_MATRICES = {(s, p): matrix_for(s, t) for s in SYSTEMS for p, t in PAYLOADS.items()}


def sweep(pool, param: str, values, trials: int, base: Condition):
    out = {}
    for name in PAYLOADS:
        for system in SYSTEMS:
            jobs, keys = [], []
            for v in values:
                cond = Condition(**{**base.__dict__, param: v})
                for t in range(trials):
                    seed = zlib.crc32(repr((param, name, float(v), t)).encode())
                    jobs.append((system, name, cond, seed))
                    keys.append(v)
            res = pool.map(_job, jobs, chunksize=4)
            rates = {v: sum(r for r, kv in zip(res, keys) if kv == v) / trials for v in values}
            out[f"{name}|{system}"] = rates
            print(f"  {param:7s} {name:18s} {system:10s} " +
                  " ".join(f"{rates[v]:.2f}" for v in values), flush=True)
    return out


def capacity_table():
    rows = []
    for name, text in PAYLOADS.items():
        row = {"payload": name}
        for system in SYSTEMS:
            m = _MATRICES[(system, name)]
            q = QUIET[system]
            row[system] = {
                "modules": f"{m.shape[1]}x{m.shape[0]}",
                "area_with_quiet_zone": (m.shape[0] + 2 * q) * (m.shape[1] + 2 * q),
            }
        rows.append(row)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=30)
    ap.add_argument("--out", default=str(Path(__file__).parent / "out"))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    results = {"capacity": capacity_table(), "trials": args.trials}
    for row in results["capacity"]:
        print(row)
    t0 = time.time()
    with Pool() as pool:
        print("resolution sweep (symbol width in camera pixels)")
        results["width"] = sweep(pool, "width", [30, 40, 50, 60, 75, 90, 110, 140], args.trials, Condition())
        print("defocus sweep (blur sigma, px, at width 140)")
        results["blur"] = sweep(pool, "blur", [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5], args.trials,
                                Condition(width=140))
        print("damage sweep (fraction of symbol area blotted, width 220)")
        results["damage"] = sweep(pool, "damage", [0.0, 0.03, 0.06, 0.09, 0.12, 0.16, 0.2], args.trials,
                                  Condition(width=220))
    results["seconds"] = round(time.time() - t0)
    (out / "results.json").write_text(json.dumps(results, indent=1))
    print("wrote", out / "results.json", f"in {results['seconds']} s")


if __name__ == "__main__":
    main()
