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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pascal_mds.reader import read  # noqa: E402

TAGS = ["a1", "a2", "a3", "a4", "a5", "a6", "b1", "b2", "b3", "b4", "b5"]


def tags_in(texts) -> set[str]:
    found = set()
    for t in texts:
        m = re.search(r"(?:ref=|NOTE:)([ab]\d)", t)
        if m:
            found.add(m.group(1))
    return found


def evaluate(path: str) -> dict:
    img = ImageOps.exif_transpose(Image.open(path)).convert("L")
    import zxingcpp

    qr = zxingcpp.read_barcodes(img, formats=zxingcpp.BarcodeFormat.QRCode)
    qr_tags = tags_in(r.text for r in qr)
    pm = read(np.asarray(img, dtype=np.float32), max_side=2400)
    pm_tags = tags_in(d.decoded.text for d in pm)
    return {"photo": Path(path).name, "size": img.size, "qr": qr_tags, "pascal": pm_tags}


def main() -> None:
    for p in sys.argv[1:]:
        r = evaluate(p)
        print(f"\n{r['photo']}  ({r['size'][0]}x{r['size'][1]})")
        print("  tag   QR   PASCAL")
        for t in TAGS:
            print(f"  {t}    {'yes' if t in r['qr'] else ' - '}   {'yes' if t in r['pascal'] else ' - '}")


if __name__ == "__main__":
    main()
