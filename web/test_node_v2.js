// node web/test_node_v2.js  -- v2 JS port vs the Python reference
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const V2 = require("./pascal_mds_v2.js");
const vectors = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "tests", "vectors_v2.json"), "utf8"));
let n = 0;
for (const v of vectors) {
  const sym = V2.encode(v.text, v.level);
  assert.strictEqual(sym.size, v.S, `size for ${JSON.stringify(v.text)}`);
  assert.deepStrictEqual(sym.modules.map((r) => Array.from(r).join("")), v.modules, `matrix for ${JSON.stringify(v.text)}`);
  n++;
}
// LDPC round trip with noisy LLRs
const { makeIra, ldpcEncode, ldpcDecode } = V2._ldpc;
let s = 7; const rnd = () => { s = (Math.imul(s, 1103515245) + 12345) >>> 0; return (s >>> 8) / 16777216; };
const gauss = () => Math.sqrt(-2 * Math.log(rnd() + 1e-12)) * Math.cos(2 * Math.PI * rnd());
for (const [k, m] of [[400, 600], [1500, 500]]) {
  const code = makeIra(k, m, 99), u = Uint8Array.from({ length: k }, () => (rnd() < 0.5 ? 1 : 0)), cw = ldpcEncode(code, u);
  const sigma = k < m ? 0.8 : 0.5;
  const llr = Float64Array.from(cw, (b) => (2 * ((b ? -1 : 1) + sigma * gauss())) / (sigma * sigma));
  const out = ldpcDecode(code, llr);
  assert(out && out.every((b, i) => b === cw[i]), `LDPC ${k}/${m}`);
  n++;
}
console.log(`ok ${n} checks`);
