// node web/test_node.js  -- JS port vs the Python known-answer vectors
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const PM = require("./pascal_mds.js");
const vectors = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "tests", "vectors.json"), "utf8"));
let n = 0;
for (const v of vectors) {
  const sym = PM.encode(v.text, v.level, v.size, v.mode);
  const rows = sym.modules.map((r) => Array.from(r).join(""));
  assert.deepStrictEqual(rows, v.modules, `matrix mismatch for ${JSON.stringify(v.text)}`);
  assert.strictEqual(sym.pad, v.pad);
  const d = PM.decodeModules(sym.modules);
  assert.strictEqual(d.text, v.text);
  n++;
}
// damaged matrices: t symbol errors at every size/level are corrected
let seed = 1; const rnd = (k) => { seed = (seed * 1103515245 + 12345) >>> 0; return (seed >>> 16) % k; };
for (const size of PM.SIZES) for (const level of PM.LEVELS) {
  const v = PM.version(size, level); if (v.capacity <= 0) continue;
  const data = Uint8Array.from({ length: v.capacity }, () => rnd(256));
  const sym = PM.encode(data, level, size, "bytes");
  const grid = sym.modules.map((r) => Uint8Array.from(r));
  const hit = new Set(); while (hit.size < v.t) hit.add(rnd(v.N));
  // flip one bit inside each chosen symbol (placement order: symbol i = bits 8i..8i+7)
  const m = size - 2, cells = []; let right = m - 1, up = true;
  while (right >= 0) { const cols = right >= 1 ? [right, right - 1] : [right]; for (let s = 0; s < m; s++) { const i = up ? m - 1 - s : s; for (const j of cols) cells.push([i + 1, j + 1]); } right -= 2; up = !up; }
  for (const i of hit) { const [r, c] = cells[8 * i + rnd(8)]; grid[r][c] ^= 1; }
  const d = PM.decodeModules(grid);
  assert(d && Buffer.from(d.data).equals(Buffer.from(data)) && d.errors === v.t, `${size}${level}`);
  n++;
}
for (const s of ["WIFI:S:Net;T:WPA;P:MixedCase;;", "aBcDeF GHIJ kl M", "unicode ✓ é 漢", "HTTPS://WWW.EXAMPLE.COM"]) {
  const b = new TextEncoder().encode(s);
  assert(Buffer.from(PM.unpackText(PM.packText(b))).equals(Buffer.from(b)), s); n++;
}
console.log(`ok ${n} checks`);
