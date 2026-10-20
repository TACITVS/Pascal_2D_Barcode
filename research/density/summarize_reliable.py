"""PB-RELIABLE-SUMMARY-2026-10-20-v1: audit saved trials and plot results."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
matplotlib.rcParams["svg.hashsalt"] = "PB-RELIABLE-01"
import matplotlib.pyplot as plt
import numpy as np

try:
    from . import reliable_density, validate_reliable
except ImportError:
    import reliable_density
    import validate_reliable


def combine(root: Path) -> dict[str, Any]:
    plan = json.loads((root / "reliable_validation_annex.json").read_text())
    groups, rows = [], []
    hashes = None
    rendered = 0
    for group in plan["groups"]:
        path = root / f"reliable_confirm_{group['id']}.json"
        document = json.loads(path.read_text())
        config = document["config"]
        assert document["source_commit"] == plan["source_commit"]
        assert config["profiles"] == [group["profile"]]
        assert config["payload_bytes"] == group["payload_bytes"]
        assert config["widths"] == group["widths"]
        expected_seed = (plan["seed"] if group["id"].startswith("annex-")
                         else 3000000)
        assert config["seed"] == expected_seed
        assert config["trials"] == plan["trials"]
        assert config["source_sha256"] == (hashes or config["source_sha256"])
        hashes = config["source_sha256"]
        receivers = (["legacy", "gmd"] if
                     group["profile"].startswith("turbo/")
                     else ["gmd"] if group["profile"].startswith("shaped/")
                     else ["assisted"])
        assert len(document["results"]) == len(group["widths"]) * len(receivers)
        for result in document["results"]:
            outcomes = result["outcomes_in_trial_order"]
            assert len(outcomes) == result["trials"] == plan["trials"]
            assert set(outcomes).issubset({"0", "1", "X"})
            assert outcomes.count("1") == result["successes"]
            assert outcomes.count("X") == result["accepted_wrong"]
            assert result["receiver"] in receivers
            lower, upper = validate_reliable.interval(
                result["successes"], result["trials"],
                plan["alpha"], plan["family_size"])
            rows.append({
                **result, "group": group["id"],
                "payload_bytes": group["payload_bytes"],
                "simultaneous_lower": lower, "simultaneous_upper": upper,
                "qualifies": lower >= plan["minimum_read_rate"],
            })
        rendered += len(group["widths"]) * plan["trials"]
        groups.append({
            "id": group["id"], "file": path.name,
            "provenance": document["provenance"],
        })
    assert hashes == reliable_density.source_hashes()
    assert len(rows) == plan["family_size"] == 56
    assert len({(r["group"], r["allocated_width"], r["receiver"])
                for r in rows}) == 56
    return {
        "experiment": "PB-RELIABLE-COMBINED-2026-10-20-v1",
        "source_commit": plan["source_commit"],
        "family_size": 56, "alpha": plan["alpha"],
        "per_tail_alpha": plan["alpha"] / 112,
        "minimum_read_rate": plan["minimum_read_rate"],
        "rendered_validation_images": rendered,
        "receiver_observations": sum(r["trials"] for r in rows),
        "accepted_wrong": sum(r["accepted_wrong"] for r in rows),
        "source_sha256": hashes, "groups": groups, "results": rows,
    }


def plot(document: dict[str, Any], out: Path) -> None:
    profiles = [
        ("turbo", "Binary Turbo", "#1261a0", "o"),
        ("shaped", "Four-level .85/.55", "#138a36", "s"),
        ("qr/L", "QR-L + assistance", "#cb3b2b", "^"),
        ("qr/M", "QR-M + assistance", "#d4850b", "v"),
        ("datamatrix", "Data Matrix + assistance", "#784e9b", "D"),
    ]
    fig, axes = plt.subplots(1, 2, figsize=(10, 4), constrained_layout=True)
    for ax, payload in zip(axes, (128, 800)):
        for prefix, label, color, marker in profiles:
            rows = sorted([
                r for r in document["results"]
                if r["payload_bytes"] == payload
                and r["profile"].startswith(prefix)
                and r["receiver"] != "legacy"
            ], key=lambda r: r["allocated_width"])
            x = np.asarray([r["allocated_width"] for r in rows])
            y = np.asarray([r["successes"] / r["trials"] for r in rows])
            lo = np.asarray([r["simultaneous_lower"] for r in rows])
            hi = np.asarray([r["simultaneous_upper"] for r in rows])
            ax.errorbar(
                x, y, yerr=np.vstack([y - lo, hi - y]),
                color=color, marker=marker, markersize=4,
                linewidth=1.2, capsize=2, label=label)
        ax.axhline(0.99, color="#444444", linestyle=":", linewidth=1)
        ax.set(title=f"{payload} arbitrary bytes",
               xlabel="Allocated exterior width (camera pixels)",
               ylabel="Exact payload recovery", ylim=(-0.02, 1.035))
        ax.grid(alpha=0.2)
    axes[0].legend(fontsize=7, loc="lower right")
    fig.suptitle(
        "Registered linear Gaussian optics + JPEG; supplied geometry/blur",
        fontsize=11)
    fig.savefig(out, format="svg", metadata={"Date": None})
    plt.close(fig)


def patterns(out: Path) -> None:
    data = np.random.default_rng(20261020).bytes(800)
    settings = [
        ("shaped/0.85+0.55+0.25", "Four-level prototype"),
        ("qr/L", "QR-L"),
        ("datamatrix/ECC200", "Data Matrix ECC200"),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(9, 3.3),
                             constrained_layout=True)
    for ax, (profile, label) in zip(axes, settings):
        symbol = reliable_density.encode(profile, data)
        modules = np.pad(symbol.grid, symbol.quiet)
        ax.imshow(
            225 - 200 * modules, cmap="gray", vmin=0, vmax=255,
            interpolation="nearest", extent=(0, 128, 128, 0))
        ax.set_title(
            f"{label}\n{symbol.grid.shape[1]} cells + quiet zone", fontsize=10)
        ax.axis("off")
    fig.suptitle(
        "Same 800 source bytes; exact encodings at equal allocated area",
        fontsize=11)
    fig.savefig(out, format="svg", metadata={"Date": None})
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).parent)
    parser.add_argument("--emit-svg", action="store_true")
    args = parser.parse_args()
    document = combine(args.root)
    (args.root / "reliable_combined_results.json").write_text(
        json.dumps(document, indent=2) + "\n")
    paths = [args.root / "reliable_density_results.svg",
             args.root / "reliable_800_patterns.svg"]
    plot(document, paths[0])
    patterns(paths[1])
    print("RELIABILITY_COMBINED_JSON "
          + json.dumps(document, separators=(",", ":")), flush=True)
    if args.emit_svg:
        for path in paths:
            print("RELIABILITY_FIGURE_JSON " + json.dumps({
                "name": path.name, "svg": path.read_text()}), flush=True)


if __name__ == "__main__":
    main()
