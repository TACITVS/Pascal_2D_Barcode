// node web/read_pgm.js file.pgm ...  -> one JSON line per file with decoded texts
const fs = require("fs");
const PM = require("./pascal_mds.js");
for (const f of process.argv.slice(2)) {
  const buf = fs.readFileSync(f);
  const head = buf.toString("latin1", 0, 64).split(/\s+/);
  const [w, h] = [parseInt(head[1]), parseInt(head[2])];
  const off = buf.length - w * h;
  const t = Date.now();
  const res = PM.readGray(buf.subarray(off), w, h, { maxSide: +(process.env.MAX_SIDE || 1200) });
  console.log(JSON.stringify({ file: f, texts: res.map((r) => r.text), ms: Date.now() - t }));
}
