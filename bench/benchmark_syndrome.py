"""PM257-SYN-BENCH-2026-10-19: exact decoder comparison, progress + ETA.

Run from the repository: python bench/benchmark_syndrome.py --photos 4
Outputs measured timings, exact result comparisons, and runtime metadata.
The optional photo test needs the existing bench dependencies. No training.
"""

from __future__ import annotations

import argparse
import json
import platform
import random
import statistics
import sys
import time
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pascal_mds import gf257  # noqa: E402
from pascal_mds.syndrome import _checks, decode_word  # noqa: E402


def gao_word(length: int, k: int, received: list[int | None]) -> list[int] | None:
    kept = [i for i, y in enumerate(received) if y is not None]
    poly = gf257.gao_decode(kept, [received[i] for i in kept], k)
    if poly is None:
        return None
    word = [gf257.poly_eval(poly, i) for i in range(length)]
    errors = sum(word[i] != received[i] for i in kept)
    return word if 2 * errors <= len(kept) - k else None


def milliseconds(call: Callable[[], object], repeats: int = 5) -> float:
    times = []
    for _ in range(repeats):
        start = time.perf_counter()
        for _ in range(5):
            call()
        times.append((time.perf_counter() - start) * 200)
    return statistics.median(times)


def progress(done: int, total: int, start: float) -> None:
    elapsed = time.perf_counter() - start
    eta = elapsed * (total - done) / max(1, done)
    width = round(20 * done / total)
    print(f"[{'#' * width}{'.' * (20 - width)}] {done}/{total} "
          f"elapsed={elapsed:.1f}s ETA={eta:.1f}s", flush=True)


def algebra() -> list[dict[str, object]]:
    results = []
    start = time.perf_counter()
    dimensions = [(55, 37), (136, 94), (253, 177), (250, 246)]
    for length, k in dimensions:
        rng = random.Random(length * 1000 + k)
        message = [rng.randrange(256) for _ in range(k)]
        word = message + gf257.pascal_extend(message, length - k)
        for kind in ("clean", "errors", "mixed", "random"):
            received: list[int | None] = list(word)
            erasures = (length - k) // 2 if kind == "mixed" else 0
            errors = (length - k - erasures) // 2 if kind in ("errors", "mixed") else 0
            positions = rng.sample(range(length), erasures + errors)
            for i in positions[:erasures]:
                received[i] = None
            for i in positions[erasures:]:
                received[i] = (word[i] + rng.randrange(1, 257)) % 257
            if kind == "random":
                received = [rng.randrange(256) for _ in range(length)]
            old = gao_word(length, k, received)
            assert old == decode_word(length, k, received)
            old_ms = milliseconds(lambda: gao_word(length, k, received))
            new_ms = milliseconds(lambda: decode_word(length, k, received))
            _checks.cache_clear()
            tick = time.perf_counter()
            assert decode_word(length, k, received) == old
            cold_ms = (time.perf_counter() - tick) * 1000
            results.append({"n": length, "k": k, "case": kind,
                            "gao_ms": old_ms, "syndrome_ms": new_ms,
                            "cold_syndrome_ms": cold_ms, "speedup": old_ms / new_ms})
            progress(len(results), 16, start)
    return results


def photos(trials: int) -> dict[str, object]:
    import numpy as np

    import benchmark as camera
    from pascal_mds import codec, encode
    from pascal_mds.reader import read

    records = []
    original = codec.decode_word
    start = time.perf_counter()
    settings = [("URL (53 B)", 44), ("URL (53 B)", 52),
                ("contact (118 B)", 75), ("contact (118 B)", 90)]
    try:
        for name, width in settings:
            payload = camera.PAYLOADS[name]
            grid = np.asarray(encode(payload, "M").modules, dtype=np.uint8)
            for seed in range(trials):
                image = camera.capture(grid, 2, camera.Condition(width=width, blur=1.2),
                                       np.random.default_rng(1000 + seed))
                observed, timings = {}, {}
                # Alternate order to reduce systematic warmup bias.
                implementations = [("gao", gao_word), ("syndrome", original)]
                if seed % 2:
                    implementations.reverse()
                for label, function in implementations:
                    codec.decode_word = function
                    tick = time.perf_counter()
                    observed[label] = [result.decoded.data.hex() for result in read(image)]
                    timings[label] = time.perf_counter() - tick
                assert observed["gao"] == observed["syndrome"]
                assert all(data == payload.encode().hex() for data in observed["syndrome"])
                records.append({"payload": name, "width": width, "seed": seed,
                                "decoded": bool(observed["syndrome"]), "seconds": timings})
                progress(len(records), len(settings) * trials, start)
    finally:
        codec.decode_word = original
    old = sum(record["seconds"]["gao"] for record in records)
    new = sum(record["seconds"]["syndrome"] for record in records)
    return {"frames": records, "gao_seconds": old, "syndrome_seconds": new,
            "speedup": old / new if new else None, "all_outputs_equal": True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--photos", type=int, default=0, help="trials per each of four conditions")
    parser.add_argument("--out", type=Path, default=Path("bench/syndrome_results_2026-10-19.json"))
    args = parser.parse_args()
    result = {"id": "PM257-SYN-BENCH-2026-10-19", "python": sys.version,
              "platform": platform.platform(), "algebra": algebra()}
    if args.photos:
        result["photos"] = photos(args.photos)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(f"Wrote {args.out}", flush=True)


if __name__ == "__main__":
    main()
