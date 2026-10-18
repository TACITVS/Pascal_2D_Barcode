"""Chart for research/README.md: information density ceiling vs QR.

python plot_capacity.py   (reads capacity_results.json, operating_points.json,
                           multistage_results.json if present)
"""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).parent
SERIES = [("hard", "hard decisions (how QR reads)", "#2a78d6"),
          ("soft", "soft, one module at a time", "#eb6834"),
          ("joint", "joint, decoded in stages", "#1baf7a")]
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"


def main():
    caps = json.loads((HERE / "capacity_results.json").read_text())
    ops = json.loads((HERE / "operating_points.json").read_text())
    ms = [json.loads(f.read_text()) for f in sorted((HERE / "multistage_results").glob("*.json"))]
    blurs = (0.7, 1.2, 2.0)
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.3), sharey=True)
    for ax, blur in zip(axes, blurs):
        rows = sorted((r for r in caps if r["channel"]["levels"] == 2 and r["channel"]["grid_error"]
                       and r["channel"]["blur"] == blur), key=lambda r: r["channel"]["pitch"])
        ps = [r["channel"]["pitch"] for r in rows]
        for key, label, colour in SERIES:
            ys = [r[key] / r["channel"]["pitch"] ** 2 for r in rows]
            ax.plot(ps, ys, color=colour, lw=2, marker="o", ms=4, label=label, zorder=3)
        for system, style, va, dy in (("QR", (0, (4, 3)), "top", -3), ("PASCAL", (0, (1, 2)), "bottom", 3)):
            d = ops.get(f"{blur}|URL (53 B)|{system}", {}).get("bits_per_px2")
            if d:
                ax.axhline(d, color=MUTED, lw=1.2, ls=style, zorder=2)
                name = "QR Code" if system == "QR" else "PASCAL-MDS v1"
                ax.annotate(f"{name} {d:.3f}", (3.38, d), xytext=(0, dy), textcoords="offset points",
                            ha="right", va=va, fontsize=8, color=MUTED)
        for m in ms:
            c = m["channel"]
            if c["blur"] == blur and c["grid_error"] and m.get("design") == "worst":
                best = max((x for x in m["results"] if x["success"] >= 0.9), key=lambda x: x["bits_per_px2"],
                           default=None)
                if best:
                    ax.plot(c["pitch"], best["bits_per_px2"], marker="D", ms=8, color=INK, zorder=4)
                    ax.annotate(f"working receiver\n{best['bits_per_px2']:.2f}", (c["pitch"], best["bits_per_px2"]),
                                xytext=(8, 8), textcoords="offset points", fontsize=8, color=INK)
        ax.set_title(f"lens blur σ = {blur} px", fontsize=10, color=INK, loc="left")
        ax.set_xlabel("module size (camera pixels per module)", fontsize=9, color=MUTED)
        ax.set_xlim(0.5, 3.4)
        ax.grid(True, color=GRID, lw=0.8)
        ax.tick_params(colors=MUTED, labelsize=8)
        for s in ax.spines.values():
            s.set_visible(False)
    axes[0].set_ylabel("user bits per camera pixel²", fontsize=9, color=MUTED)
    axes[0].set_ylim(0, 0.75)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=3, frameon=False, fontsize=9)
    fig.suptitle("")
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    fig.savefig(HERE / "capacity_chart.png", dpi=150, facecolor="#fcfcfb")
    print("wrote", HERE / "capacity_chart.png")


if __name__ == "__main__":
    main()
