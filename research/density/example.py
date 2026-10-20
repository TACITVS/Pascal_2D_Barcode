"""Encode arbitrary bytes, render one simulated capture, and decode it.

This demonstration supplies registration and estimates blur from the frame.
Its PNG is a new research format requiring this configured Python reader.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

from benchmark_density import dense, reader2, turbo
from capacity import Channel, render


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="binary payload; otherwise deterministic random bytes")
    parser.add_argument("--bytes", type=int, default=800)
    parser.add_argument("--rate", type=float, default=0.85)
    parser.add_argument("--width", type=float, default=160)
    parser.add_argument("--seed", type=int, default=23)
    parser.add_argument("--out", type=Path, default=Path("/tmp/pascal-density-example"))
    args = parser.parse_args()
    data = args.input.read_bytes() if args.input else np.random.default_rng(args.seed).bytes(args.bytes)
    v, grid = turbo.encode(data, args.rate)
    quiet = dense.QUIET
    pitch = args.width / (v.S + 2 * quiet)
    image, cx, cy = render(np.pad(grid, quiet), Channel(pitch, 0.7, 6, 75, 2, 0.25),
                          np.random.default_rng(args.seed))
    left, top = cx[quiet] - pitch / 2, cy[quiet] - pitch / 2
    side = v.S * pitch
    corners = np.array([[left, top], [left + side, top],
                        [left + side, top + side], [left, top + side]])
    blur, _ = reader2.estimate(reader2.Photo(image.astype(np.float32), corners, v.S, False), (1.0,))
    decoded, history = turbo.decode(v, image, cx[quiet:quiet + v.S], cy[quiet:quiet + v.S],
                                    pitch, blur, rounds=16)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.with_suffix(".bin").write_bytes(data)
    clean = (255 * (1 - np.pad(grid, quiet))).astype(np.uint8)
    Image.fromarray(clean).resize((clean.shape[1] * 6, clean.shape[0] * 6),
                                  Image.Resampling.NEAREST).save(args.out.with_suffix(".png"))
    Image.fromarray(image.astype(np.uint8)).save(args.out.with_suffix(".capture.png"))
    summary = {"research_format": "PM257-TURBO-v0", "payload_bytes": len(data),
               "S": v.S, "rate": v.rate, "capacity_bytes_with_tag": v.capacity,
               "width_with_quiet": args.width, "estimated_blur": blur,
               "decoded_exactly": decoded == data, "history": history,
               "geometry": "supplied", "real_camera_validation": False}
    args.out.with_suffix(".json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    raise SystemExit(0 if decoded == data else 1)


if __name__ == "__main__":
    main()
