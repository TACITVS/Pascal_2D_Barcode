"""PM257-DENSITY-BENCH-2026-10-19: registered image-to-byte density comparison.

All systems receive exact symbol geometry. Turbo receives blur calibration;
Dense receives the same blur calibration initially and keeps its own refits.
Area includes each format's quiet zone. Independent random bytes per frame,
shared initial nuisance draws, blur jitter +/-25%, noise 6, JPEG quality 75.
Progress includes elapsed/ETA; each completed point is saved and resumable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
from scipy.stats import beta

sys.path[:0] = [str(Path(__file__).resolve().parents[1]),
                str(Path(__file__).resolve().parents[1] / "v2"),
                str(Path(__file__).resolve().parents[2])]

import dense  # noqa: E402
import reader2  # noqa: E402
import turbo  # noqa: E402
import gray  # noqa: E402
from capacity import Channel, render  # noqa: E402
from pascal_mds import encode as standard_encode  # noqa: E402
from pascal_mds.reader import decode_at  # noqa: E402


def make_symbol(system: str, payload: bytes):
    family, setting = system.split("/")
    match family:
        case "turbo":
            version, grid = turbo.encode(payload, float(setting))
            return version, grid, dense.QUIET
        case "gray":
            version, grid = gray.encode(payload, tuple(map(float, setting.split("+"))))
            return version, grid, dense.QUIET
        case "dense":
            version, grid = dense.encode(payload + turbo.tag(payload), setting, mode="bytes")
            return version, grid, dense.QUIET
        case "standard":
            symbol = standard_encode(payload + turbo.tag(payload), setting, mode="bytes")
            return symbol.version, np.asarray(symbol.modules, np.uint8), 2
        case _:
            raise ValueError("unknown system")


def trial(system: str, width: float, payload_bytes: int, blur: float,
          seed: int, rounds: int, calibration: str, equalizer: str = "average") -> dict[str, object]:
    payload = np.random.default_rng(seed + 1000000).bytes(payload_bytes)
    v, grid, quiet = make_symbol(system, payload)
    size = grid.shape[0]
    pitch = width / (size + 2 * quiet)
    channel = Channel(pitch, blur, 6.0, 75, 2, 0.25, 0.0)
    image, cx, cy = render(np.pad(grid, quiet), channel, np.random.default_rng(seed))
    actual_blur = float(render.last_blur)
    used_blur = actual_blur if calibration == "oracle" else blur
    left, top = cx[quiet] - pitch / 2, cy[quiet] - pitch / 2
    corners = np.array([[left, top], [left + size * pitch, top],
                        [left + size * pitch, top + size * pitch],
                        [left, top + size * pitch]])
    start = time.perf_counter()
    family, setting = system.split("/")
    if calibration == "estimated" and family in ("turbo", "gray"):
        photograph = reader2.Photo(image.astype(np.float32), corners, size, False)
        used_blur, _ = reader2.estimate(photograph, (1.0,))
    steps = 0
    match family:
        case "turbo":
            result, history = turbo.decode(v, image, cx[quiet:quiet + size], cy[quiet:quiet + size],
                                           pitch, used_blur, rounds=rounds, equalizer=equalizer)
            steps = len(history)
        case "gray":
            result, history = gray.decode(v, image, cx[quiet:quiet + size], cy[quiet:quiet + size],
                                          pitch, used_blur, rounds=rounds)
            steps = len(history)
        case "dense":
            decoded = reader2.decode_symbol(image.astype(np.float32), corners, size, False,
                                            setting, None if calibration == "estimated" else
                                            (used_blur, np.full(49, 8.0), 200 / 225, 1.0))
            raw = decoded.data if decoded is not None else None
            result = raw[:-8] if raw is not None and len(raw) >= 8 and turbo.tag(raw[:-8]) == raw[-8:] else None
        case "standard":
            decoded = decode_at(image.astype(np.float32), corners, size)
            raw = decoded.data if decoded is not None else None
            result = raw[:-8] if raw is not None and len(raw) >= 8 and turbo.tag(raw[:-8]) == raw[-8:] else None
        case _:
            raise ValueError("unknown system")
    return {"success": result == payload, "wrong": result is not None and result != payload,
            "blur": actual_blur, "seconds": time.perf_counter() - start,
            "rounds": steps, "size": size, "pitch": pitch}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--systems", default="standard/L,standard/M,dense/A,dense/B,dense/C,turbo/0.25,turbo/0.35,turbo/0.45,turbo/0.55,turbo/0.65,turbo/0.75,turbo/0.85")
    parser.add_argument("--widths", default="40,48,56,64,72,80,88")
    parser.add_argument("--trials", type=int, default=16)
    parser.add_argument("--payload", type=int, default=128)
    parser.add_argument("--blur", type=float, default=0.7)
    parser.add_argument("--seed", type=int, default=10000)
    parser.add_argument("--rounds", type=int, default=16)
    parser.add_argument("--equalizer", choices=["average", "cg"], default="average")
    parser.add_argument("--calibration", choices=["oracle", "nominal", "estimated"], default="estimated")
    parser.add_argument("--out", type=Path, default=Path("research/density/discovery.jsonl"))
    args = parser.parse_args()
    source = b"".join(Path(__file__).with_name(name).read_bytes()
                      for name in ["turbo.py", "gray.py", "benchmark_density.py"])
    source_hash = hashlib.sha256(source).hexdigest()
    existing = [json.loads(line) for line in args.out.read_text().splitlines()] if args.out.exists() else []
    widths = list(map(float, args.widths.split(",")))
    systems = args.systems.split(",")
    jobs = [(system, width) for system in systems for width in widths]
    done = 0
    start = time.perf_counter()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("a") as log:
        for system, width in jobs:
            config = {"system": system, "width": width, "trials": args.trials,
                      "payload": args.payload, "blur": args.blur, "seed": args.seed,
                      "rounds": args.rounds, "calibration": args.calibration,
                      "equalizer": args.equalizer, "source": source_hash}
            if any(row["config"] == config for row in existing):
                continue
            frames = []
            for i in range(args.trials):
                frames.append(trial(system, width, args.payload, args.blur,
                                    args.seed + i, args.rounds, args.calibration, args.equalizer))
                done += 1
                if (i + 1) % 8 == 0 or i + 1 == args.trials:
                    elapsed = time.perf_counter() - start
                    total = len(jobs) * args.trials
                    eta = elapsed * (total - done) / max(done, 1)
                    print(f"[{done}/{total}] {system} W={width} {i + 1}/{args.trials} "
                          f"elapsed={elapsed:.1f}s ETA<={eta:.1f}s", flush=True)
            successes = sum(row["success"] for row in frames)
            lower = float(beta.ppf(0.05, successes, args.trials - successes + 1)) if successes else 0.0
            result = {"config": config, "successes": successes,
                      "wrong": sum(row["wrong"] for row in frames),
                      "one_sided_95_lower": lower,
                      "payload_bits_per_area": 8 * args.payload / width ** 2,
                      "seconds": sum(row["seconds"] for row in frames), "frames": frames}
            log.write(json.dumps(result) + "\n")
            log.flush()
            print(f"RESULT {system} W={width} {successes}/{args.trials} "
                  f"density={result['payload_bits_per_area']:.4f}", flush=True)


if __name__ == "__main__":
    main()
