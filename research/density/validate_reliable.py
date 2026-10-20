"""PB-RELIABLE-VALIDATE-2026-10-20-v1: frozen fresh-seed confirmation.

The plan predates the trials. Check that every decoder, encoder and renderer
source still matches the selected Git commit. A single Bonferroni family
covers every reported operating point and both paired binary receivers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from scipy.stats import beta

try:
    from . import reliable_density
except ImportError:
    import reliable_density


def family_size(groups: list[dict[str, Any]]) -> int:
    return sum(len(group["widths"])
               * (2 if group["profile"].startswith("turbo/") else 1)
               for group in groups)


def interval(
    successes: int, trials: int, alpha: float, family: int,
) -> tuple[float, float]:
    """Exact two-sided Clopper-Pearson with Bonferroni family coverage."""
    tail = alpha / (2 * family)
    lower = (0.0 if successes == 0 else
             float(beta.ppf(tail, successes, trials - successes + 1)))
    upper = (1.0 if successes == trials else
             float(beta.ppf(1 - tail, successes + 1, trials - successes)))
    return lower, upper


def validate(plan_path: Path, group_id: str, out: Path) -> dict[str, Any]:
    plan_bytes = plan_path.read_bytes()
    plan = json.loads(plan_bytes)
    if family_size(plan["groups"]) != plan["family_size"]:
        raise ValueError("plan family size is inconsistent")
    group = next(row for row in plan["groups"] if row["id"] == group_id)
    # The workflow fetches full history. A report-only commit may follow the
    # frozen source commit, but it must not change the experiment's sources.
    subprocess.run(
        ["git", "diff", "--exit-code", plan["source_commit"], "--",
         *plan["frozen_paths"]], check=True)
    raw_path = out.with_suffix(".measurements.json")
    measured = reliable_density.run(
        group["payload_bytes"], group["widths"], [group["profile"]],
        group.get("trials", plan["trials"]), plan["seed"], raw_path,
        rounds=plan["rounds"], blur=plan["channel"]["blur"],
        noise=plan["channel"]["noise"], jpeg=plan["channel"]["jpeg"],
        jitter=plan["channel"]["blur_jitter"])
    checkpoint = raw_path.with_suffix(".jsonl")
    rows = [json.loads(line) for line in checkpoint.read_text().splitlines()
            if line.strip()]
    for result in measured["results"]:
        low, high = interval(
            result["successes"], result["trials"],
            plan["alpha"], plan["family_size"])
        result.update({
            "simultaneous_lower": low, "simultaneous_upper": high,
            "qualifies": low >= plan["minimum_read_rate"],
        })
        selected = sorted(
            [row for row in rows
             if row["allocated_width"] == result["allocated_width"]],
            key=lambda row: row["trial"])
        receiver = result["receiver"]
        # Persistent per-trial outcomes; full diagnostics stay in the
        # checkpoint artifact. Seeds/config reproduce every rendered input.
        result["outcomes_in_trial_order"] = "".join(
            "X" if row["accepted_wrong"][receiver]
            else "1" if row["exact"][receiver] else "0"
            for row in selected)
        if receiver == "gmd" and group["profile"].startswith("shaped/"):
            result["outer_rescues_without_all_inner_checks"] = sum(
                any(step.get("payload_valid")
                    and not step.get("legacy_valid")
                    for step in row["diagnostics"])
                for row in selected)
    document = {
        "experiment": "PB-RELIABLE-VALIDATE-2026-10-20-v1",
        "group": group_id,
        "plan_sha256": hashlib.sha256(plan_bytes).hexdigest(),
        "source_commit": plan["source_commit"],
        "validation_driver_sha256": hashlib.sha256(
            Path(__file__).read_bytes()).hexdigest(),
        "family_size": plan["family_size"], "alpha": plan["alpha"],
        "minimum_read_rate": plan["minimum_read_rate"],
        **measured,
    }
    if (plan.get("emit_interval_table")
            and group_id == plan["annex_group_ids"][0]):
        document["interval_table"] = [
            interval(k, plan["trials"], plan["alpha"], plan["family_size"])
            for k in range(plan["trials"] + 1)]
    out.write_text(json.dumps(document, indent=2) + "\n")
    print("RELIABILITY_VALIDATION_JSON "
          + json.dumps(document, separators=(",", ":")), flush=True)
    return document


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--group", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    validate(args.plan, args.group, args.out)


if __name__ == "__main__":
    main()
