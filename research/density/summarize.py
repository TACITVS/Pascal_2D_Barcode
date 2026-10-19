"""Aggregate both frozen validation families with one 95% familywise budget.

The primary and secondary selections were frozen separately before their
respective fresh tests. This summary uses the more conservative 13-point
Bonferroni adjustment throughout, including both tails of every interval.
"""

from __future__ import annotations

import json
from pathlib import Path

from scipy.stats import beta


def main() -> None:
    root = Path(__file__).resolve().parent
    sources = [json.loads((root / name).read_text()) for name in
               ("validation_summary.json", "capacity_validation_summary.json")]
    points = sum(len(source["results"]) for source in sources)
    alpha = 0.05 / (2 * points)
    rows = []
    for source in sources:
        for result in source["results"]:
            row = dict(result)
            n, k = row["trials"], row["successes"]
            lower = float(beta.ppf(alpha, k, n - k + 1)) if k else 0.0
            upper = float(beta.ppf(1 - alpha, k + 1, n - k)) if k < n else 1.0
            row.update({"experiment": source["plan"]["id"],
                        "simultaneous_95_interval": [lower, upper],
                        "meets_99_percent_lower_bound": lower >= 0.99})
            rows.append(row)
    report = {"familywise_confidence": 0.95, "points": points,
              "per_tail_alpha": alpha, "plans": [s["plan"] for s in sources],
              "results": rows}
    (root / "combined_validation.json").write_text(json.dumps(report, indent=2) + "\n")
    for row in rows:
        lower, upper = row["simultaneous_95_interval"]
        print(f"{row['payload_bytes']:3}B {row['system']:11} W={row['width_with_quiet']:3} "
              f"{row['successes']}/{row['trials']} CI=[{lower:.6f},{upper:.6f}] "
              f"qualifies={row['meets_99_percent_lower_bound']}")


if __name__ == "__main__":
    main()
