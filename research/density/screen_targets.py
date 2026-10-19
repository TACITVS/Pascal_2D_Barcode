"""PM257-PHOTO-TARGETS-2026-10-19-v1: reproducible offline screen kit.

Generate matched old/new targets and their ground-truth manifest. Auxiliary
ArUco marks supply assisted registration; their area is reported separately.
The viewer displays precomputed codes and does not implement a photo reader.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

try:
    from .benchmark_density import make_symbol
except ImportError:
    from benchmark_density import make_symbol


@dataclass(frozen=True)
class BoardLayout:
    cells: int
    marker: int
    gap: int = 3

    @property
    def origin(self) -> int:
        return self.marker + 2 * self.gap

    @property
    def side(self) -> int:
        return self.cells + 2 * self.origin

    @property
    def marker_origins(self) -> tuple[tuple[int, int], ...]:
        lo, hi = self.gap, self.side - self.gap - self.marker
        return ((lo, lo), (hi, lo), (hi, hi), (lo, hi))

    def marker_corners(self) -> list[list[list[float]]]:
        return [[[float(x), float(y)], [float(x + self.marker), float(y)],
                 [float(x + self.marker), float(y + self.marker)],
                 [float(x), float(y + self.marker)]] for x, y in self.marker_origins]


@dataclass(frozen=True)
class TargetCase:
    identifier: str
    profile: str
    variant: int
    payload: bytes
    grid: np.ndarray
    quiet: int
    marker_ids: tuple[int, ...]

    @property
    def layout(self) -> BoardLayout:
        cells = self.grid.shape[0] + 2 * self.quiet
        return BoardLayout(cells, 6 * max(2, math.ceil(0.16 * cells / 6)))

    def record(self) -> dict[str, object]:
        layout = self.layout
        return {"id": self.identifier, "profile": self.profile,
                "variant": self.variant, "payload_bytes": len(self.payload),
                "payload_base64": base64.b64encode(self.payload).decode("ascii"),
                "payload_sha256": hashlib.sha256(self.payload).hexdigest(),
                "S": int(self.grid.shape[0]), "quiet": self.quiet,
                "rows": ["".join(map(str, row)) for row in self.grid.tolist()],
                "board_side_units": layout.side, "code_origin_units": layout.origin,
                "marker_side_units": layout.marker, "marker_ids": self.marker_ids,
                "marker_corners_units": layout.marker_corners(),
                "png": f"targets/{self.identifier}.png"}


def payload_bytes(variant: int, length: int) -> bytes:
    """Deterministic high-entropy bytes, unrelated to validation seed sets."""
    seed = f"PM257-PHOTO-PAYLOAD-2026-10-19-v1/{variant}/".encode("ascii")
    stream = b"".join(hashlib.sha256(seed + str(i).encode("ascii")).digest()
                      for i in range(math.ceil(length / 32)))
    return stream[:length]


def make_cases(variants: int = 3) -> list[TargetCase]:
    if not 1 <= variants <= 3:
        raise ValueError("choose one to three independent payload variants")
    cases = []
    for variant in range(1, variants + 1):
        for index, (label, system, length) in enumerate([
                ("A1", "dense/A", 128), ("A2", "turbo/0.55", 128),
                ("B1", "dense/A", 582), ("B2", "turbo/0.85", 800)]):
            payload = payload_bytes(variant, length)
            _, grid, quiet = make_symbol(system, payload)
            first = 10 + 16 * (variant - 1) + 4 * index
            cases.append(TargetCase(f"{label}-V{variant}", system, variant, payload,
                                    grid, quiet, tuple(range(first, first + 4))))
    return cases


def marker_grid(identifier: int) -> np.ndarray:
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_100)
    return (cv2.aruco.generateImageMarker(dictionary, identifier, 6) == 0).astype(np.uint8)


def board_array(case: TargetCase, cell_pixels: int = 4) -> np.ndarray:
    if cell_pixels < 1:
        raise ValueError("cell_pixels must be positive")
    layout = case.layout
    board = np.zeros((layout.side, layout.side), dtype=np.uint8)
    start = layout.origin + case.quiet
    side = case.grid.shape[0]
    board[start:start + side, start:start + side] = case.grid
    for identifier, (x, y) in zip(case.marker_ids, layout.marker_origins):
        marker = np.repeat(np.repeat(marker_grid(identifier), layout.marker // 6,
                                     axis=0), layout.marker // 6, axis=1)
        board[y:y + layout.marker, x:x + layout.marker] = marker
    return np.repeat(np.repeat(255 * (1 - board), cell_pixels, axis=0),
                     cell_pixels, axis=1).astype(np.uint8)


def build(output: Path, variants: int = 3) -> dict[str, object]:
    root = Path(__file__).resolve().parent
    output.mkdir(parents=True, exist_ok=True)
    (output / "targets").mkdir(exist_ok=True)
    cases = make_cases(variants)
    manifest = {
        "kit_id": "PM257-PHOTO-KIT-2026-10-19-v1",
        "encoder_base_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "encoder_sha256": {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                           for name in ("turbo.py", "benchmark_density.py", "screen_targets.py")},
        "marker_dictionary": "DICT_4X4_100", "registration": "assisted_external_markers",
        "default_png_cell_pixels": 4, "cases": [case.record() for case in cases],
        "markers": {str(i): marker_grid(i).tolist()
                    for case in cases for i in case.marker_ids},
        "density_accounting": "Report symbol-plus-quiet and full-board areas separately.",
    }
    encoded = json.dumps(manifest, separators=(",", ":"))
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    template = (root / "screen_viewer.html").read_text()
    (output / "START_PHOTO_TEST.html").write_text(template.replace("__TARGET_MANIFEST__", encoded))
    for case in cases:
        Image.fromarray(board_array(case)).save(output / "targets" / f"{case.identifier}.png")
    (output / "README.txt").write_text((root / "PHOTO_PROTOCOL.md").read_text())
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("/tmp/pascal-photo-kit"))
    parser.add_argument("--variants", type=int, default=3)
    args = parser.parse_args()
    manifest = build(args.out, args.variants)
    print(f"Built {len(manifest['cases'])} targets in {args.out.resolve()}")


if __name__ == "__main__":
    main()
