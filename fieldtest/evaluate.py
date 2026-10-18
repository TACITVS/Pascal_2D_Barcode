"""Decode every QR and PASCAL-MDS code in test-sheet photos.

python fieldtest/evaluate.py photo1.jpg [photo2.jpg ...]

Prints, per photo, which size tags each symbology decoded.  QR is read by
zxing-cpp (all its effort options on); PASCAL-MDS by pascal_mds.reader.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research"))
sys.path.insert(0, str(ROOT / "research" / "v2"))
from pascal_mds.reader import read  # noqa: E402

TAGS = [f"{s}{i}" for s, n in (("a", 6), ("b", 5), ("c", 5)) for i in range(1, n + 1)]


def tags_in(texts) -> set[str]:
    found = set()
    for t in texts:
        m = re.search(r"(?:ref=|NOTE:|Tag )([abc]\d)", t)
        if m:
            found.add(m.group(1))
    return found


def evaluate(path: str) -> dict:
    img = ImageOps.exif_transpose(Image.open(path)).convert("L")
    import zxingcpp

    qr = zxingcpp.read_barcodes(img, formats=zxingcpp.BarcodeFormat.QRCode)
    qr_tags = tags_in(r.text for r in qr)
    arr = np.asarray(img, dtype=np.float32)
    pm_tags = tags_in(d.decoded.text for d in read(arr, max_side=max(arr.shape)))
    import reader2

    v2_tags = tags_in(r.data.decode("utf-8", "replace") for r in reader2.read(arr, max_side=max(arr.shape)))
    return {"photo": Path(path).name, "size": img.size, "qr": qr_tags, "pascal": pm_tags, "dense": v2_tags}


def main() -> None:
    for p in sys.argv[1:]:
        r = evaluate(p)
        print(f"\n{r['photo']}  ({r['size'][0]}x{r['size'][1]})")
        print("  tag   QR   Standard  Dense")
        for t in TAGS:
            if any(t in r[k] for k in ("qr", "pascal", "dense")):
                print(f"  {t}    {'yes' if t in r['qr'] else ' - '}   {'yes' if t in r['pascal'] else ' - ':8s}  {'yes' if t in r['dense'] else ' - '}")


if __name__ == "__main__":
    main()
