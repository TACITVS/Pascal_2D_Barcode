"""PM257-CAPACITY-VALIDATION-2026-10-19: frozen, resumable held-out validation.

The plan is saved before testing. Every frame is checkpointed. Two
preselected configurations, 640 fresh images each; simultaneous 95% exact
binomial intervals use a Bonferroni correction over both tails and all points.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from scipy.stats import beta

from benchmark_density import trial


def main() -> None:
    root = Path(__file__).resolve().parent
    selections = [(800, "turbo/0.85", 160), (582, "dense/A", 160)]
    digest = hashlib.sha256(b"".join((root / name).read_bytes() for name in
                                   ["turbo.py", "gray.py", "benchmark_density.py", "validate_capacity.py"])).hexdigest()
    plan = {"id": "PM257-CAPACITY-VALIDATION-2026-10-19", "trials_per_point": 640,
            "seed": 1000000, "blur": 0.7, "jitter": 0.25, "noise": 6,
            "jpeg": 75, "calibration": "estimated", "geometry": "supplied",
            "rounds": 16, "equalizer": "average", "familywise_confidence": 0.95,
            "source_sha256": digest, "selections": [list(row) for row in selections]}
    plan_path = root / "capacity_validation_plan.json"
    if plan_path.exists() and json.loads(plan_path.read_text()) != plan:
        raise RuntimeError("validation source/plan changed; do not mix results")
    plan_path.write_text(json.dumps(plan, indent=2) + "\n")
    path = root / "capacity_validation_frames.jsonl"
    previous = [json.loads(row) for row in path.read_text().splitlines()] if path.exists() else []
    done = {(row["point"], row["trial"]) for row in previous}
    start = time.perf_counter()
    total = len(selections) * plan["trials_per_point"]
    completed = 0
    records = list(previous)
    with path.open("a") as log:
        for point, (payload, system, width) in enumerate(selections):
            for index in range(plan["trials_per_point"]):
                if (point, index) in done:
                    continue
                result = trial(system, width, payload, 0.7, plan["seed"] + index,
                               16, "estimated", "average")
                row = {"point": point, "trial": index, **result}
                records.append(row)
                log.write(json.dumps(row) + "\n")
                log.flush()
                completed += 1
                if completed % 16 == 0:
                    elapsed = time.perf_counter() - start
                    remaining = total - len(previous) - completed
                    eta = elapsed * remaining / completed
                    print(f"[{len(previous) + completed}/{total}] {system} "
                          f"{payload}B W={width} elapsed={elapsed:.1f}s ETA={eta:.1f}s", flush=True)
            frames = [row for row in records if row["point"] == point]
            print(f"POINT {point} {system} {payload}B W={width}: "
                  f"{sum(row['success'] for row in frames)}/{len(frames)}", flush=True)
    alpha = 0.05 / (2 * len(selections))
    summary = []
    for point, (payload, system, width) in enumerate(selections):
        frames = [row for row in records if row["point"] == point]
        successes = sum(row["success"] for row in frames)
        n = len(frames)
        lower = float(beta.ppf(alpha, successes, n - successes + 1)) if successes else 0.0
        upper = float(beta.ppf(1 - alpha, successes + 1, n - successes)) if successes < n else 1.0
        summary.append({"point": point, "system": system, "payload_bytes": payload,
                        "width_with_quiet": width, "trials": n, "successes": successes,
                        "wrong": sum(row["wrong"] for row in frames),
                        "simultaneous_95_interval": [lower, upper],
                        "meets_99_percent_lower_bound": lower >= 0.99,
                        "payload_bits_per_area": 8 * payload / width ** 2,
                        "failed_trials": [row["trial"] for row in frames if not row["success"]],
                        "seconds": sum(row["seconds"] for row in frames)})
    (root / "capacity_validation_summary.json").write_text(json.dumps({"plan": plan, "results": summary}, indent=2) + "\n")


if __name__ == "__main__":
    main()
