"""Draw exact encoded patterns and the held-out density comparison.

Requires matplotlib in addition to the development dependencies.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from benchmark_density import make_symbol


def main() -> None:
    root = Path(__file__).resolve().parent
    data = json.loads((root / "combined_validation.json").read_text())
    fig = plt.figure(figsize=(10, 9), layout="constrained", facecolor="#f7f8fa")
    layout = fig.add_gridspec(3, 2, height_ratios=[1.4, 1, 0.22])
    for column, (system, count, label) in enumerate([
            ("dense/A", 582, "Existing Dense-A · 582 bytes"),
            ("turbo/0.85", 800, "New global optical code · 800 bytes")]):
        ax = fig.add_subplot(layout[0, column])
        payload = np.random.default_rng(20261019).bytes(count)
        _, grid, quiet = make_symbol(system, payload)
        assert grid.shape == (94, 94)
        ax.imshow(1 - np.pad(grid, quiet), cmap="gray", vmin=0, vmax=1,
                  interpolation="nearest")
        ax.set_title(label, fontsize=13, pad=10)
        ax.set_xlabel("94×94 modules + the same quiet zone\nProfile: 640/640 fresh simulated reads", fontsize=10)
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)
    ax = fig.add_subplot(layout[1, :])
    configurations = [("dense/A", 80, "Dense-A · width 80"),
                      ("standard/L", 76, "Original · width 76"),
                      ("turbo/0.55", 66, "New · width 66")]
    rows = [next(r for r in data["results"] if r["payload_bytes"] == 128
                 and r["system"] == system and r["width_with_quiet"] == width)
            for system, width, _ in configurations]
    assert all(r["meets_99_percent_lower_bound"] for r in rows)
    values = [r["payload_bits_per_area"] for r in rows]
    bars = ax.barh([c[2] for c in configurations], values,
                   color=["#9aa6b5", "#63758a", "#137c73"], height=0.55)
    ax.bar_label(bars, labels=[f"{v:.3f}" for v in values], padding=8, fontsize=11)
    ax.set_xlim(0, max(values) * 1.2)
    ax.invert_yaxis()
    ax.set_xlabel("Payload bits per captured pixel² · area includes quiet zones")
    ax.set_title("The same 128-byte payload in less area", loc="left", fontsize=13, pad=14)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.grid(axis="x", alpha=0.2)
    ax.set_axisbelow(True)
    fig.suptitle("Higher payload density, with measured read reliability", fontsize=17)
    caption = fig.add_subplot(layout[2, :])
    caption.axis("off")
    caption.text(0.5, 0.5, "Controlled simulation: fresh random payloads; supplied geometry; estimated blur; noise + JPEG.\n"
                 "Selected points pass a 99% read-rate lower bound at simultaneous 95% confidence.\n"
                 "Real print/phone validation remains open.", ha="center", va="center", fontsize=9, color="#485568")
    fig.savefig(root / "density_results.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main()
