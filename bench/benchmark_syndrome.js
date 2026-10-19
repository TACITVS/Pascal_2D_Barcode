// PM257-SYN-JS-BENCH-2026-10-19: Node algebra timings, not browser timings.
function main() {
  const PM = require("../web/pascal_mds.js");
  const fs = require("fs"), assert = require("assert");
  let state = 20261019;
  function random(n) { state ^= state << 13; state ^= state >>> 17; state ^= state << 5; return (state >>> 0) % n; }
  function gaoWord(n, k, received) {
    const xs = [], ys = [];
    received.forEach((y, i) => { if (y !== null) { xs.push(i); ys.push(y); } });
    const f = PM.gaoDecode(xs, ys, k); if (!f) return null;
    const word = Array.from({ length: n }, (_, i) => PM.polyEval(f, i));
    return 2 * xs.filter((i) => word[i] !== received[i]).length <= xs.length - k ? word : null;
  }
  function time(call) {
    const times = []; call();
    for (let batch = 0; batch < 5; batch++) {
      const start = performance.now();
      for (let i = 0; i < 20; i++) call();
      times.push((performance.now() - start) / 20);
    }
    return times.sort((a, b) => a - b)[2];
  }
  const algebra = [];
  for (const [n, k] of [[55, 37], [136, 94], [253, 177], [250, 246]]) {
    const message = Array.from({ length: k }, () => random(256));
    const word = message.concat(PM.pascalExtend(message, n - k));
    for (const kind of ["clean", "errors", "mixed", "random"]) {
      let received = word.slice();
      const e = kind === "mixed" ? Math.floor((n - k) / 2) : 0;
      const t = ["errors", "mixed"].includes(kind) ? Math.floor((n - k - e) / 2) : 0;
      const positions = Array.from({ length: n }, (_, i) => i);
      for (let i = n - 1; i > 0; i--) { const j = random(i + 1); [positions[i], positions[j]] = [positions[j], positions[i]]; }
      for (const i of positions.slice(0, e)) received[i] = null;
      for (const i of positions.slice(e, e + t)) received[i] = (word[i] + 1 + random(256)) % 257;
      if (kind === "random") received = Array.from({ length: n }, () => random(256));
      assert.deepStrictEqual(PM.decodeWord(n, k, received), gaoWord(n, k, received));
      const old = time(() => gaoWord(n, k, received)), fast = time(() => PM.decodeWord(n, k, received));
      algebra.push({ n, k, case: kind, gao_ms: old, syndrome_ms: fast, speedup: old / fast });
    }
  }
  const result = { id: "PM257-SYN-JS-BENCH-2026-10-19", node: process.version, algebra };
  fs.writeFileSync("bench/syndrome_js_results_2026-10-19.json", JSON.stringify(result, null, 2) + "\n");
  console.log(JSON.stringify(result));
}
main();
