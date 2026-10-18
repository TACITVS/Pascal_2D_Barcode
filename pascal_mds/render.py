"""Render symbols as SVG (no dependencies) or as images (Pillow/numpy)."""

from __future__ import annotations

from .codec import Symbol

QUIET_ZONE = 2  # modules of light margin required on every side


def to_svg(symbol: Symbol, module_px: int = 10, quiet: int = QUIET_ZONE,
           dark: str = "#000", light: str = "#fff") -> str:
    n = symbol.size
    total = (n + 2 * quiet) * module_px
    path = []
    for r, row in enumerate(symbol.modules):
        c = 0
        while c < n:
            if row[c]:
                start = c
                while c < n and row[c]:
                    c += 1
                x = (start + quiet) * module_px
                y = (r + quiet) * module_px
                path.append(f"M{x} {y}h{(c - start) * module_px}v{module_px}h-{(c - start) * module_px}z")
            else:
                c += 1
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total}" height="{total}" '
        f'viewBox="0 0 {total} {total}" shape-rendering="crispEdges">'
        f'<rect width="100%" height="100%" fill="{light}"/>'
        f'<path fill="{dark}" d="{"".join(path)}"/></svg>'
    )


def to_array(symbol: Symbol, module_px: int = 10, quiet: int = QUIET_ZONE):
    """uint8 grayscale image (0 = dark, 255 = light)."""
    import numpy as np

    grid = np.array(symbol.modules, dtype=np.uint8)
    grid = np.pad(grid, quiet)
    img = np.where(grid == 1, 0, 255).astype(np.uint8)
    return np.kron(img, np.ones((module_px, module_px), dtype=np.uint8))


def to_image(symbol: Symbol, module_px: int = 10, quiet: int = QUIET_ZONE):
    from PIL import Image

    return Image.fromarray(to_array(symbol, module_px, quiet), mode="L")
