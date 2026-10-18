"""Build the screen/print test sheet: QR and PASCAL-MDS codes at equal sizes.

Every code encodes the same kind of text with a different size tag
(a1..a6, b1..b5, c1..c5), so one photo shows the smallest size each
symbology survives.  python fieldtest/make_sheet.py  ->  fieldtest/sheet.html

The sheet is a paged viewer: codes keep their exact test widths and are
packed into pages that fill the window; arrow keys page through them.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import segno

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research"))
sys.path.insert(0, str(ROOT / "research" / "v2"))
from pascal_mds import encode  # noqa: E402
import dense  # noqa: E402

LINK = "https://www.example.com/products/item?id=12345&ref={tag}"
CONTACT = ("BEGIN:VCARD\nVERSION:3.0\nN:Doe;Jane\nTEL:+1-555-0100\n"
           "EMAIL:jane.doe@example.com\nNOTE:{tag}\nEND:VCARD")
NOTES = ("Meeting notes 18 Oct: the new barcode reads at half the printed size of a QR Code in simulation. "
         "Next: field tests with printed sheets at 0.5, 1, 1.5 and 2 m, normal room light, three phones. "
         "Contact Jane Doe (jane.doe@example.com) for the test kit; budget PX-2207. Tag {tag}.")
V2_LEVEL = "A"  # densest; best in every benchmark condition (bench/RESULTS_v2.md)
SETS = [
    ("a", "Link, 53 characters", LINK, [220, 150, 105, 75, 55, 40]),
    ("b", "Contact card, 104 characters", CONTACT, [260, 180, 125, 90, 65]),
    ("c", "Notes, 300 characters", NOTES, [320, 230, 165, 120, 90]),
]


def svg(modules, quiet: int, width_px: float, label: str) -> tuple[str, float, float]:
    """Crisp SVG with its quiet zone, scaled so the symbol itself is width_px
    wide.  Returns (markup, total width, total height)."""
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
    tw = width_px * vw / n_cols
    th = tw * vh / vw
    markup = (f'<svg role="img" aria-label="{label}" width="{tw:.2f}" height="{th:.2f}" '
              f'viewBox="0 0 {vw} {vh}" shape-rendering="crispEdges"><rect width="{vw}" height="{vh}" fill="#fff"/>'
              f'<path fill="#000" d="{"".join(path)}"/></svg>')
    return markup, tw, th


def items() -> list[dict]:
    """One entry per code: tag, kind, symbol width, SVG and its plate size."""
    out = []
    for key, title, template, widths in SETS:
        for i, w in enumerate(widths, 1):
            tag = f"{key}{i}"
            text = template.format(tag=tag)
            qr = segno.make_qr(text, error="m", boost_error=False)
            qm = [list(r) for r in qr.matrix]
            codes = [("QR", f"QR {len(qm)}×{len(qm)}", svg(qm, 4, w, f"QR Code {tag}"))]
            try:
                pm = encode(text, "M")
                codes.append(("Std", f"Standard {pm.size}×{pm.size}", svg(pm.modules, 2, w, f"PASCAL-MDS {tag}")))
            except ValueError:
                pass  # too long for Standard
            v, grid = dense.encode(text, V2_LEVEL)
            codes.append(("Dense", f"Dense {v.S}×{v.S}", svg(grid.tolist(), dense.QUIET, w, f"PASCAL-MDS Dense {tag}")))
            for kind, detail, (markup, tw, th) in codes:
                out.append({"tag": tag, "set": title, "kind": kind, "detail": detail, "w": w,
                            "pw": round(tw, 2), "ph": round(th, 2), "svg": markup})
    # largest first: every page then holds codes of similar size
    order = {"QR": 0, "Std": 1, "Dense": 2}
    out.sort(key=lambda it: (-it["ph"], it["tag"], order[it["kind"]]))
    return out


def main() -> None:
    data = json.dumps(items(), ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = TEMPLATE.replace("{{ITEMS}}", data)
    out = Path(__file__).parent / "sheet.html"
    out.write_text(html)
    print("wrote", out)


TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Barcode Distance Test</title>
<style>
/* Paged viewer: codes keep their exact test widths (never rescaled) and are
   shelf-packed into pages the size of the window; keys page through them. */
:root { --bg: #eef0f3; --ink: #15171c; --muted: #5a6170; --line: #d5d9e0; --accent: #2f44cf; --bar: #ffffffd9;
  --font: "Atkinson Hyperlegible", system-ui, -apple-system, "Segoe UI", sans-serif; --mono: ui-monospace, Menlo, Consolas, monospace; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg: #101318; --ink: #e8ebf1; --muted: #9aa3b4; --line: #2b313d; --accent: #8e9cff; --bar: #181c23d9; color-scheme: dark; } }
:root[data-theme="dark"] { --bg: #101318; --ink: #e8ebf1; --muted: #9aa3b4; --line: #2b313d; --accent: #8e9cff; --bar: #181c23d9; color-scheme: dark; }
* { box-sizing: border-box; }
html, body { height: 100%; margin: 0; overflow: hidden; }
body { background: var(--bg); color: var(--ink); font: 15px/1.5 var(--font); user-select: none; -webkit-user-select: none; }
body.idle, body.idle * { cursor: none; }
#stage { position: fixed; inset: 0 0 var(--barh, 30px) 0; display: flex; flex-direction: column; justify-content: space-evenly; padding: 8px 10px; }
.shelf { display: flex; justify-content: space-evenly; align-items: flex-end; }
.item { display: grid; justify-items: center; gap: 2px; }
.plate { background: #fff; line-height: 0; }
.plate svg { display: block; }
.cap { font: 11px/13px var(--mono); color: var(--muted); white-space: nowrap; }
.cap b { color: var(--accent); }
#bar { position: fixed; left: 0; right: 0; bottom: 0; height: var(--barh, 30px); display: flex; align-items: center; justify-content: space-between;
  gap: 12px; padding: 0 max(12px, env(safe-area-inset-right, 0px)) 0 max(12px, env(safe-area-inset-left, 0px));
  background: var(--bar); border-top: 1px solid var(--line); font: 12px var(--mono); color: var(--muted); white-space: nowrap; overflow: hidden; }
#bar b { color: var(--ink); }
#bar .keys { overflow: hidden; text-overflow: ellipsis; }
kbd { font: 11px var(--mono); border: 1px solid var(--line); border-bottom-width: 2px; border-radius: 4px; padding: 0 5px; color: var(--ink); }
.cover { margin: auto; max-width: 68ch; display: grid; gap: 14px; padding: 16px; overflow: auto; max-height: 100%; }
.cover h1 { font-size: 28px; line-height: 1.2; margin: 0; letter-spacing: -0.01em; }
.cover p, .cover ol { margin: 0; }
.cover ol { padding-left: 22px; }
.cover li + li { margin-top: 6px; }
.cover .note { color: var(--muted); }
.cover .go { font-size: 17px; }
</style>
</head>
<body>
<div id="stage"></div>
<div id="bar"><span id="where"></span><span class="keys"><kbd>→</kbd> next &nbsp;<kbd>←</kbd> back &nbsp;<kbd>F</kbd> full screen &nbsp;<kbd>Home</kbd> instructions</span></div>
<script>
const ITEMS = {{ITEMS}};
const GAP_X = 14, GAP_Y = 8, CAP_H = 15, MIN_W = 58;
const stage = document.getElementById("stage"), where = document.getElementById("where");
let pages = [], current = 0;  // page 0 is the instructions

function size(it) { return { w: Math.max(it.pw, MIN_W), h: it.ph + CAP_H }; }

// First-fit shelf packing, largest first: each code goes into the first row
// (on any page) with room to its right; otherwise it opens a row on the first
// page with height to spare; otherwise a new page.  Rows never grow taller,
// because codes come in decreasing height.  A code larger than the window
// gets a page alone.
function pack(W, H) {
  const out = [];  // pages: {shelves: [{items, w}], used}
  for (let i = 0; i < ITEMS.length; i++) {
    const s = size(ITEMS[i]);
    const shelf = out.flatMap(pg => pg.shelves).find(sh => sh.w + GAP_X + s.w <= W);
    if (shelf) { shelf.items.push(i); shelf.w += GAP_X + s.w; continue; }
    let page = out.find(pg => pg.used + GAP_Y + s.h <= H);
    if (!page) { page = { shelves: [], used: -GAP_Y }; out.push(page); }
    page.shelves.push({ items: [i], w: s.w });
    page.used += GAP_Y + s.h;
  }
  return out.map(pg => pg.shelves);
}

function cover() {
  const n = ITEMS.length, sets = [...new Set(ITEMS.map(it => it.set))].join(", ");
  return `<div class="cover">
    <h1>Barcode Distance Test</h1>
    <p>${n} codes: QR, PASCAL-MDS Standard and PASCAL-MDS Dense, each at several exact widths (${sets}).
      Every code carries a size tag (a1, b3, …) in its text, so each photo shows which sizes were read.</p>
    <ol>
      <li>Set the browser zoom to 100% and the screen brightness high. Press <kbd>F</kbd> for full screen.</li>
      <li>Press <kbd>→</kbd> or <kbd>Space</kbd> for the next batch of codes, <kbd>←</kbd> to go back. Tapping the right or left half of the screen also works.</li>
      <li>Photograph each batch with your phone's normal camera from 0.5 m, 1 m, 1.5 m and 2 m, straight on, then a few at an angle.</li>
      <li>Upload the photos in the chat; every code in every photo gets decoded and compared.</li>
    </ol>
    <p class="note">Codes are shown at their exact test widths and never rescaled; the batches repack when the window changes size.
      Screen scaling here: ${Math.round(devicePixelRatio * 100)}%.</p>
    <p class="go"><kbd>→</kbd> start</p></div>`;
}

function itemHtml(i) {
  const it = ITEMS[i];
  return `<div class="item" title="${it.set} · ${it.detail} · ${it.w} px"><div class="plate">${it.svg}</div>` +
         `<div class="cap"><b>${it.tag}</b> ${it.kind} ${it.w}</div></div>`;
}

function show(p) {
  current = Math.max(0, Math.min(p, pages.length));
  if (current === 0) {
    stage.innerHTML = cover();
    where.innerHTML = `<b>Instructions</b> · ${pages.length} pages of codes`;
  } else {
    const page = pages[current - 1];
    stage.innerHTML = page.map(sh => `<div class="shelf">${sh.items.map(itemHtml).join("")}</div>`).join("");
    const its = page.flatMap(sh => sh.items).map(i => ITEMS[i]);
    const ws = its.map(it => it.w);
    where.innerHTML = `<b>Page ${current} of ${pages.length}</b> · ${its.length} codes · ${Math.min(...ws)}–${Math.max(...ws)} px wide`;
  }
}

function layout() {
  const first = current > 0 && pages[current - 1] ? pages[current - 1][0].items[0] : null;
  const cs = getComputedStyle(stage);
  const W = stage.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
  const H = stage.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom);
  pages = pack(W, H);
  // keep the code that led the current page in view after a resize
  show(first === null ? current : 1 + pages.findIndex(pg => pg.some(sh => sh.items.includes(first))));
}

function fullscreen() {
  if (document.fullscreenElement) document.exitFullscreen();
  else document.documentElement.requestFullscreen?.().catch(() => {});
}

document.addEventListener("keydown", e => {
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  const k = e.key;
  if (["ArrowRight", "ArrowDown", "PageDown", " ", "Enter", "n", "N"].includes(k)) show(current + 1);
  else if (["ArrowLeft", "ArrowUp", "PageUp", "Backspace", "p", "P"].includes(k)) show(current - 1);
  else if (k === "Home") show(0);
  else if (k === "End") show(pages.length);
  else if (k === "f" || k === "F") fullscreen();
  else return;
  e.preventDefault();
});
stage.addEventListener("click", e => show(current + (e.clientX > innerWidth / 2 ? 1 : -1)));

// hide the pointer while photographing
let idleTimer;
addEventListener("pointermove", () => {
  document.body.classList.remove("idle");
  clearTimeout(idleTimer);
  idleTimer = setTimeout(() => document.body.classList.add("idle"), 1500);
});

let resizeTimer;
addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(layout, 120); });
layout();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
