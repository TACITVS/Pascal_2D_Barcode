"""Build the screen/print test sheet: QR and PASCAL-MDS pairs at equal sizes.

Every code encodes the same kind of text with a different size tag
(a1..a6, b1..b5), so one photo shows the smallest size each symbology
survives.  python fieldtest/make_sheet.py  ->  fieldtest/sheet.html
"""

from __future__ import annotations

import sys
from pathlib import Path

import segno

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pascal_mds import encode  # noqa: E402

LINK = "https://www.example.com/products/item?id=12345&ref={tag}"
CONTACT = ("BEGIN:VCARD\nVERSION:3.0\nN:Doe;Jane\nTEL:+1-555-0100\n"
           "EMAIL:jane.doe@example.com\nNOTE:{tag}\nEND:VCARD")
SETS = [
    ("a", "Link, 53 characters", LINK, [220, 150, 105, 75, 55, 40]),
    ("b", "Contact card, 104 characters", CONTACT, [260, 180, 125, 90, 65]),
]


def svg(modules, quiet: int, width_px: float, label: str) -> str:
    n_rows, n_cols = len(modules), len(modules[0])
    path = []
    for r, row in enumerate(modules):
        c = 0
        while c < n_cols:
            if row[c]:
                s = c
                while c < n_cols and row[c]:
                    c += 1
                path.append(f"M{s + quiet} {r + quiet}h{c - s}v1h-{c - s}z")
            else:
                c += 1
    vw, vh = n_cols + 2 * quiet, n_rows + 2 * quiet
    total = width_px * vw / n_cols
    return (f'<svg role="img" aria-label="{label}" width="{total:.1f}" height="{total * vh / vw:.1f}" '
            f'viewBox="0 0 {vw} {vh}" shape-rendering="crispEdges"><rect width="{vw}" height="{vh}" fill="#fff"/>'
            f'<path fill="#000" d="{"".join(path)}"/></svg>')


def main() -> None:
    sections = []
    for key, title, template, widths in SETS:
        rows = []
        for i, w in enumerate(widths, 1):
            tag = f"{key}{i}"
            text = template.format(tag=tag)
            qr = segno.make_qr(text, error="m", boost_error=False)
            qm = [list(r) for r in qr.matrix]
            pm = encode(text, "M")
            rows.append(
                f'<div class="pair"><div class="tag"><b>{tag}</b><span>{w} px wide</span></div>'
                f'<figure><div class="plate">{svg(qm, 4, w, f"QR Code {tag}")}</div>'
                f'<figcaption>QR {len(qm)}×{len(qm)}</figcaption></figure>'
                f'<figure><div class="plate">{svg(pm.modules, 2, w, f"PASCAL-MDS {tag}")}</div>'
                f'<figcaption>PASCAL {pm.size}×{pm.size}</figcaption></figure></div>')
        sections.append(f'<section><h2>{title}</h2><div class="grid">{"".join(rows)}</div></section>')
    html = TEMPLATE.replace("{{SECTIONS}}", "".join(sections))
    out = Path(__file__).parent / "sheet.html"
    out.write_text(html)
    print("wrote", out)


TEMPLATE = """<title>Barcode Distance Test</title>
<meta name="claude:viewport-fit-sides" content="cover">
<style>
/* Layout: one column of size rows; each row pairs QR and PASCAL-MDS at the same symbol width. */
:root { --bg: #eef0f3; --ink: #15171c; --muted: #5a6170; --line: #d5d9e0; --accent: #2f44cf;
  --font: "Atkinson Hyperlegible", system-ui, -apple-system, "Segoe UI", sans-serif; --mono: ui-monospace, Menlo, monospace; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg: #101318; --ink: #e8ebf1; --muted: #9aa3b4; --line: #2b313d; --accent: #8e9cff; color-scheme: dark; } }
:root[data-theme="dark"] { --bg: #101318; --ink: #e8ebf1; --muted: #9aa3b4; --line: #2b313d; --accent: #8e9cff; color-scheme: dark; }
* { box-sizing: border-box; }
body { background: var(--bg); color: var(--ink); font: 15px/1.5 var(--font); margin: 0;
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); padding-block: 20px 40px; }
main { max-width: 980px; margin: 0 auto; display: grid; gap: 24px; }
h1 { font-size: 26px; margin: 0; letter-spacing: -0.01em; }
h2 { font-size: 17px; margin: 0 0 12px; }
ol { margin: 0; padding-left: 20px; max-width: 70ch; }
li + li { margin-top: 4px; }
.note { color: var(--muted); margin: 0; max-width: 70ch; }
.grid { display: grid; gap: 22px; }
.pair { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 18px 28px; padding-bottom: 18px; border-bottom: 1px solid var(--line); }
.tag { width: 92px; display: grid; }
.tag b { font: 700 22px var(--mono); color: var(--accent); }
.tag span { color: var(--muted); font-size: 12px; }
figure { margin: 0; display: grid; gap: 6px; justify-items: start; }
figcaption { font: 12px var(--mono); color: var(--muted); }
.plate { background: #fff; line-height: 0; }
svg { display: block; max-width: 100%; height: auto; }
</style>
<main>
  <header style="display:grid;gap:10px">
    <h1>Barcode Distance Test</h1>
    <p class="note">Each row shows a QR Code and a PASCAL-MDS code of the same text at the same printed width. The tag in the text (a1, a2, …) tells which size was read.</p>
    <ol>
      <li>Show this page on a computer screen at 100% zoom, brightness high.</li>
      <li>Photograph it with your phone's normal camera from several distances (for example 30 cm, 60 cm, 1 m, 1.5 m), straight on, then a few at an angle.</li>
      <li>Upload the photos in the chat. Both codes in every photo get decoded and compared.</li>
    </ol>
  </header>
  {{SECTIONS}}
</main>
"""

if __name__ == "__main__":
    main()
