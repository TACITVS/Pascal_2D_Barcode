/* PASCAL-MDS v2 (dense): encoder and photo reader.
 * JavaScript port of research/v2/dense.py and reader2.py; same format.
 * Needs pascal_mds.js (v1) for detection and the GF(257) outer code. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory(require("./pascal_mds.js"));
  else root.PascalMDSv2 = factory(root.PascalMDS);
})(typeof self !== "undefined" ? self : this, function (V1) {
  "use strict";
  const I = V1._internals;
  const SIZES = []; for (let S = 22; S <= 94; S += 4) SIZES.push(S);
  const QUIET = 4, RS_PARITY = 4, RS_BLOCK = 250;
  const STAGES = [[0, 0], [1, 1], [0, 1], [1, 0]];
  const LEVELS = {
    A: { pitch: 1.2, blur: 0.875, rates: [0.43, 0.41, 0.82, 0.89] },
    B: { pitch: 1.5, blur: 1.5, rates: [0.26, 0.29, 0.63, 0.90] },
    C: { pitch: 2.0, blur: 2.5, rates: [0.15, 0.19, 0.41, 0.82] },
  };
  const LIGHT = 225, DARK = 25, D = LIGHT - DARK;

  // ---------------------------------------------------------- portable PRNG
  class XorShift32 {
    constructor(seed) { this.s = (seed >>> 0) || 0x9e3779b9; }
    next() { let s = this.s; s ^= s << 13; s >>>= 0; s ^= s >>> 17; s ^= s << 5; s >>>= 0; this.s = s; return s; }
    below(n) { return this.next() % n; }
    shuffle(a) { for (let i = a.length - 1; i > 0; i--) { const j = this.below(i + 1); const t = a[i]; a[i] = a[j]; a[j] = t; } }
  }
  function seed(...parts) {
    let h = 2166136261;
    for (const b of new TextEncoder().encode(parts.join("/"))) h = Math.imul(h ^ b, 16777619) >>> 0;
    return h;
  }

  // ------------------------------------------------------------------ layout
  function frameModules(S) {
    const n = S / 2, out = new Int8Array(S * S).fill(-1);
    for (let R = 0; R < n; R++) for (let C = 0; C < n; C++) {
      if (R === 0 || C === 0 || R === n - 1 || C === n - 1) {
        const v = I.frameValue(R, C, n);
        for (let dr = 0; dr < 2; dr++) for (let dc = 0; dc < 2; dc++) out[(2 * R + dr) * S + 2 * C + dc] = v;
      }
    }
    return out;
  }
  const cosetCache = new Map();
  function cosetPositions(S, k) {
    const key = S + "/" + k; if (cosetCache.has(key)) return cosetCache.get(key);
    const [r0, c0] = STAGES[k], rr = [], cc = [];
    for (let r = 2 + r0; r < S - 2; r += 2) for (let c = 2 + c0; c < S - 2; c += 2) { rr.push(r); cc.push(c); }
    const order = rr.map((_, i) => i); new XorShift32(seed("perm", S, k)).shuffle(order);
    const out = { rows: order.map((i) => rr[i]), cols: order.map((i) => cc[i]) };
    cosetCache.set(key, out); return out;
  }
  function makeIra(k, m, sd) {
    const dv = Math.max(3, Math.round((2 * m) / Math.max(k, 1)));
    const cols = []; for (let i = 0; i < k; i++) for (let j = 0; j < dv; j++) cols.push(i);
    const rng = new XorShift32(sd); let rows;
    for (let t = 0; t < 50; t++) {
      rows = []; for (let j = 0; j < k * dv; j++) rows.push(j % m);
      rng.shuffle(rows);
      const seen = new Set(rows.map((r, i) => r * k + cols[i]));
      if (seen.size === rows.length) break;
    }
    const pairs = [...new Set(rows.map((r, i) => r * k + cols[i]))].map((x) => [Math.floor(x / k), x % k]);
    pairs.sort((a, b) => a[1] - b[1] || a[0] - b[0]);
    return { k, m, n: k + m, rows: Int32Array.from(pairs.map((p) => p[0])), cols: Int32Array.from(pairs.map((p) => p[1])) };
  }
  const versions = new Map();
  function version(S, level) {
    const key = S + level; if (versions.has(key)) return versions.get(key);
    const nCoset = ((S - 4) / 2) ** 2, kStage = LEVELS[level].rates.map((r) => Math.floor(r * nCoset));
    const total = Math.floor(kStage.reduce((a, b) => a + b, 0) / 8), nb = Math.max(1, Math.ceil(total / RS_BLOCK));
    const blocks = []; for (let i = 0; i < nb; i++) blocks.push(Math.floor(total / nb) + (i < total % nb ? 1 : 0));
    const room = blocks.reduce((a, b) => a + b - RS_PARITY - 1, 0);
    const v = { S, level, nCoset, kStage, blocks, infoBits: kStage.reduce((a, b) => a + b, 0), capacity: Math.max(0, room - (room - 1 <= 31 ? 1 : 2)) };
    versions.set(key, v); return v;
  }
  const codeCache = new Map();
  function codes(S, level) {
    const key = S + level; if (codeCache.has(key)) return codeCache.get(key);
    const v = version(S, level), out = v.kStage.map((k, i) => makeIra(k, v.nCoset - k, seed("ira", S, level, i)));
    codeCache.set(key, out); return out;
  }
  function scramble(S, level, k, n) {
    const rng = new XorShift32(seed("scr", S, level, k)), out = new Uint8Array(n);
    for (let i = 0; i < n; i++) out[i] = rng.next() >>> 31;
    return out;
  }

  // ------------------------------------------------------------------- LDPC
  function ldpcEncode(code, u) {
    const s = new Uint8Array(code.m);
    for (let e = 0; e < code.rows.length; e++) s[code.rows[e]] ^= u[code.cols[e]];
    const out = new Uint8Array(code.n); out.set(u.subarray ? u.subarray(0, code.k) : u.slice(0, code.k));
    let p = 0; for (let j = 0; j < code.m; j++) { p ^= s[j]; out[code.k + j] = p; }
    return out;
  }
  const decoderCache = new WeakMap();
  function bpGraph(code) {
    if (decoderCache.has(code)) return decoderCache.get(code);
    const { k, m } = code, E = code.rows.length + 2 * m - 1, er = new Int32Array(E), ec = new Int32Array(E);
    let e = 0;
    for (let i = 0; i < code.rows.length; i++) { er[e] = code.rows[i]; ec[e] = code.cols[i]; e++; }
    for (let j = 0; j < m; j++) { er[e] = j; ec[e] = k + j; e++; }
    for (let j = 1; j < m; j++) { er[e] = j; ec[e] = k + j - 1; e++; }
    const order = Array.from({ length: E }, (_, i) => i).sort((a, b) => er[a] - er[b] || a - b);
    const r = Int32Array.from(order.map((i) => er[i])), c = Int32Array.from(order.map((i) => ec[i]));
    const start = new Int32Array(m + 1); for (let i = 0; i < E; i++) start[r[i] + 1]++;
    for (let j = 0; j < m; j++) start[j + 1] += start[j];
    const g = { r, c, start, n: code.n, m };
    decoderCache.set(code, g); return g;
  }
  /** Sum-product decoding; llr > 0 means bit 0.  Returns bits or null. */
  function ldpcDecode(code, llr, iters = 80) {
    const { r, c, start, n, m } = bpGraph(code), E = r.length;
    const v2c = new Float64Array(E), c2v = new Float64Array(E), total = Float64Array.from(llr), t = new Float64Array(E);
    for (let e = 0; e < E; e++) v2c[e] = llr[c[e]];
    const bits = new Uint8Array(n);
    for (let it = 0; it < iters; it++) {
      for (let e = 0; e < E; e++) { let x = Math.tanh(Math.max(-30, Math.min(30, v2c[e])) / 2); if (Math.abs(x) < 1e-12) x = x < 0 ? -1e-12 : 1e-12; t[e] = x; }
      for (let j = 0; j < m; j++) {
        let logs = 0, neg = 0;
        for (let e = start[j]; e < start[j + 1]; e++) { logs += Math.log(Math.abs(t[e])); if (t[e] < 0) neg++; }
        for (let e = start[j]; e < start[j + 1]; e++) {
          const ext = Math.exp(logs - Math.log(Math.abs(t[e]))) * (((neg - (t[e] < 0 ? 1 : 0)) & 1) ? -1 : 1);
          const cl = Math.max(-0.999999999, Math.min(0.999999999, ext));
          c2v[e] = 2 * Math.atanh(cl);
        }
      }
      total.set(llr);
      for (let e = 0; e < E; e++) total[c[e]] += c2v[e];
      for (let i = 0; i < n; i++) bits[i] = total[i] < 0 ? 1 : 0;
      let ok = true;
      for (let j = 0; j < m && ok; j++) { let s = 0; for (let e = start[j]; e < start[j + 1]; e++) s ^= bits[c[e]]; if (s) ok = false; }
      if (ok) return bits;
      for (let e = 0; e < E; e++) v2c[e] = total[c[e]] - c2v[e];
    }
    return null;
  }

  function unsatisfiedFraction(code, llr) {
    const s = new Uint8Array(code.m), hard = (i) => (llr[i] < 0 ? 1 : 0);
    for (let e = 0; e < code.rows.length; e++) s[code.rows[e]] ^= hard(code.cols[e]);
    let bad = 0;
    for (let j = 0; j < code.m; j++) { const v = s[j] ^ hard(code.k + j) ^ (j ? hard(code.k + j - 1) : 0); bad += v; }
    return bad / code.m;
  }

  // ------------------------------------------------------------ outer code
  function choosePad(parity0, unit) {
    let cur = parity0.slice();
    for (let s = 0; s < 256; s++) {
      if (cur.every((v) => v !== 256)) return [s, cur];
      cur = cur.map((v, i) => (v + unit[i]) % 257);
    }
    throw new Error("unreachable (Theorem 1)");
  }
  function rsBlock(message, parity) {
    const p0 = V1.pascalExtend(message, parity), unit = V1.pascalExtend(new Array(message.length - 1).fill(0).concat([1]), parity);
    const [s, par] = choosePad(p0, unit);
    return message.slice(0, -1).concat([s], par);
  }
  function encode(input, level = "B", size = null, mode = "auto") {
    const data = typeof input === "string" ? new TextEncoder().encode(input) : Uint8Array.from(input);
    const [modeId, payload] = I.bestPayload(data, mode);
    let v = null;
    for (const S of size ? [size] : SIZES) { const c = version(S, level); if (payload.length <= c.capacity) { v = c; break; } }
    if (!v) throw new Error(`payload of ${payload.length} bytes does not fit level ${level}`);
    let stream = I.header(modeId, payload.length).concat(Array.from(payload));
    const msgs = v.blocks.map((b) => {
      const k = b - RS_PARITY, chunk = stream.slice(0, k - 1); stream = stream.slice(k - 1);
      while (chunk.length < k) chunk.push(0);
      return rsBlock(chunk, RS_PARITY);
    });
    const order = [], maxB = Math.max(...v.blocks);
    for (let i = 0; i < maxB; i++) for (let j = 0; j < msgs.length; j++) if (i < v.blocks[j]) order.push(msgs[j][i]);
    const bits = new Uint8Array(v.infoBits);
    order.forEach((byte, i) => { for (let b = 0; b < 8; b++) bits[8 * i + b] = (byte >> (7 - b)) & 1; });
    const S = v.S, grid = frameModules(S);
    let pos = 0;
    codes(S, level).forEach((code, k) => {
      const cw = ldpcEncode(code, bits.subarray(pos, pos + code.k)); pos += code.k;
      const { rows, cols } = cosetPositions(S, k), sc = scramble(S, level, k, cw.length);
      for (let i = 0; i < cw.length; i++) grid[rows[i] * S + cols[i]] = cw[i] ^ sc[i];
    });
    const modules = []; for (let r = 0; r < S; r++) modules.push(Uint8Array.from(grid.subarray(r * S, (r + 1) * S)));
    return { version: v, modules, size: S };
  }
  function decodeInfoBits(v, bits) {
    const nbytes = v.blocks.reduce((a, b) => a + b, 0), stream = [];
    for (let i = 0; i < nbytes; i++) { let x = 0; for (let b = 0; b < 8; b++) x = (x << 1) | bits[8 * i + b]; stream.push(x); }
    const blocks = v.blocks.map(() => []), maxB = Math.max(...v.blocks); let i = 0;
    for (let p = 0; p < maxB; p++) for (let j = 0; j < blocks.length; j++) if (p < v.blocks[j]) blocks[j].push(stream[i++]);
    const message = [];
    for (const blk of blocks) {
      const n = blk.length, k = n - RS_PARITY, xs = blk.map((_, x) => x);
      const f = V1.gaoDecode(xs, blk, k); if (!f) return null;
      const word = xs.map((x) => V1.polyEval(f, x));
      if (word.filter((w, x) => w !== blk[x]).length > 1 || word.some((w) => w > 255)) return null;
      message.push(...word.slice(0, k - 1));
    }
    const mode = message[0] >> 6; let len, h;
    if (message[0] & 0x20) { len = ((message[0] & 0x1f) << 8) | message[1]; h = 2; } else { len = message[0] & 0x1f; h = 1; }
    const end = h + len;
    if (mode > 1 || end > message.length) return null;
    for (let x = end; x < message.length; x++) if (message[x]) return null;
    const payload = Uint8Array.from(message.slice(h, end));
    return mode === 1 ? V1.unpackText(payload) : payload;
  }

  // ------------------------------------------------------- detector model
  const RAD = 4, LAT = RAD + 2, OFFS = [-1.5, -1, -0.5, 0, 0.5, 1, 1.5];
  const NB = []; for (let dr = -RAD; dr <= RAD; dr++) for (let dc = -RAD; dc <= RAD; dc++) NB.push([dr, dc]);
  const CENTRE = NB.findIndex(([a, b]) => a === 0 && b === 0);
  function erf(x) { // Abramowitz & Stegun 7.1.26
    const s = x < 0 ? -1 : 1; x = Math.abs(x);
    const t = 1 / (1 + 0.3275911 * x);
    return s * (1 - ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x));
  }
  const PHI = (z) => 0.5 * (1 + erf(z / Math.SQRT2));
  // quadratic B-spline (pixel box * bilinear triangle) as a 31-point quadrature
  const QB = (() => { const t = [], w = []; for (let i = 0; i < 31; i++) { const x = -1.5 + (3 * (i + 0.5)) / 31; t.push(x); const a = Math.abs(x); w.push(a < 0.5 ? 0.75 - a * a : a < 1.5 ? 0.5 * (1.5 - a) ** 2 : 0); }
    const s = w.reduce((p, q) => p + q, 0); return { t, w: w.map((q) => q / s) }; })();
  /** 1-D darkening profile of one module of width p px, blur sigma px, at x px. */
  function profile(p, sigma, x) {
    const sg = Math.max(sigma, 1e-3); let r = 0;
    for (let i = 0; i < QB.t.length; i++) { const u = x - QB.t[i]; r += QB.w[i] * (PHI((u + p / 2) / sg) - PHI((u - p / 2) / sg)); }
    return r;
  }
  const fpCache = new Map();
  /** F[n][j]: darkening of window sample j caused by neighbour n (Float64Array per n). */
  function footprints(p, blur) {
    const key = p.toFixed(2) + "/" + blur.toFixed(2); if (fpCache.has(key)) return fpCache.get(key);
    const lat = new Map();
    const r1 = (d) => { const k = Math.round(d * 2); if (!lat.has(k)) lat.set(k, Math.abs(d) > LAT ? 0 : profile(p, blur, d * p)); return lat.get(k); };
    const F = NB.map(([dr, dc]) => { const row = new Float64Array(49); let j = 0;
      for (const oy of OFFS) for (const ox of OFFS) { row[j++] = r1(ox - dc) * r1(oy - dr); } return row; });
    const sum = new Float64Array(49); for (const row of F) for (let j = 0; j < 49; j++) sum[j] += row[j];
    const out = { F, far: Array.from(sum, (s) => 0.5 * (1 - s)) };
    if (fpCache.size > 400) fpCache.clear();
    fpCache.set(key, out); return out;
  }
  function choleskySolve(A, b, n) { // A: Float64Array n*n SPD
    const L = new Float64Array(n * n);
    for (let i = 0; i < n; i++) for (let j = 0; j <= i; j++) {
      let s = A[i * n + j]; for (let k = 0; k < j; k++) s -= L[i * n + k] * L[j * n + k];
      L[i * n + j] = i === j ? Math.sqrt(Math.max(s, 1e-12)) : s / L[j * n + j];
    }
    const y = new Float64Array(n); for (let i = 0; i < n; i++) { let s = b[i]; for (let k = 0; k < i; k++) s -= L[i * n + k] * y[k]; y[i] = s / L[i * n + i]; }
    const x = new Float64Array(n); for (let i = n - 1; i >= 0; i--) { let s = y[i]; for (let k = i + 1; k < n; k++) s -= L[k * n + i] * x[k]; x[i] = s / L[i * n + i]; }
    return x;
  }
  /** Linear filter for one known/unknown neighbour pattern (see research/v2_detector.py). */
  function stageFilter(fp, knownMask, noise) {
    const { F } = fp, C = new Float64Array(49 * 49);
    for (let j = 0; j < 49; j++) C[j * 49 + j] = noise * noise;
    const unk = [], kn = [];
    NB.forEach((_, i) => { if (i === CENTRE) return; (knownMask[i] ? kn : unk).push(i); });
    const q = (D * D) / 4;
    for (const i of unk) { const f = F[i]; for (let a = 0; a < 49; a++) { if (!f[a]) continue; const fa = q * f[a]; for (let b = 0; b < 49; b++) C[a * 49 + b] += fa * f[b]; } }
    const a = Float64Array.from(F[CENTRE], (x) => D * x), w = choleskySolve(C, a, 49);
    let bias = 0; for (let j = 0; j < 49; j++) bias += 0.5 * a[j] * w[j];
    const base = new Float64Array(49); // terms independent of the known values
    for (let j = 0; j < 49; j++) { let s = -LIGHT + D * fp.far[j]; for (const i of unk) s += (D / 2) * F[i][j]; base[j] = s; }
    return { w, bias, kn, base };
  }

  // ------------------------------------------------------------------ reader
  function quadFit(xs, ys, vals) { return I.solve(xs.map((x, i) => [1, x, ys[i], x * x, x * ys[i], ys[i] * ys[i]]), vals); }
  const quadEval = (c, x, y) => c[0] + c[1] * x + c[2] * y + c[3] * x * x + c[4] * x * y + c[5] * y * y;
  function moduleH(corners, S, mirrored) {
    let src = [[0, 0], [S, 0], [S, S], [0, S]];
    if (mirrored) src = src.map(([x, y]) => [S - y, S - x]);
    return I.homography(src, corners);
  }
  class Photo {
    constructor(sampler, corners, S, mirrored) {
      this.Smp = sampler; this.S = S; this.H = moduleH(corners, S, mirrored); this.kappa = 1;
      const xs = [], ys = [], vs = [];
      for (let r = -QUIET; r < S + QUIET; r++) for (let c = -QUIET; c < S + QUIET; c++) {
        if (Math.min(r, c, S - 1 - r, S - 1 - c) > -2) continue;
        const [u, v] = I.applyH(this.H, c + 0.5, r + 0.5); xs.push((c + 0.5) / S - 0.5); ys.push((r + 0.5) / S - 0.5); vs.push(sampler(u, v));
      }
      this.light = quadFit(xs, ys, vs);
      const c = S / 2, p0 = I.applyH(this.H, c - 1, c), p1 = I.applyH(this.H, c + 1, c), q0 = I.applyH(this.H, c, c - 1), q1 = I.applyH(this.H, c, c + 1);
      this.pitch = Math.sqrt(Math.hypot(p1[0] - p0[0], p1[1] - p0[1]) * Math.hypot(q1[0] - q0[0], q1[1] - q0[1])) / 2;
      this.known = new Int8Array((S + 2 * QUIET) ** 2); const fm = frameModules(S), W = S + 2 * QUIET;
      for (let r = 0; r < S; r++) for (let c2 = 0; c2 < S; c2++) this.known[(r + QUIET) * W + c2 + QUIET] = fm[r * S + c2];
    }
    darkening(r, c) {
      const lt = Math.max(1, quadEval(this.light, (c + 0.5) / this.S - 0.5, (r + 0.5) / this.S - 0.5)), out = new Float64Array(49); let j = 0;
      for (const oy of OFFS) for (const ox of OFFS) { const [u, v] = I.applyH(this.H, c + 0.5 + ox, r + 0.5 + oy); out[j++] = (lt - this.Smp(u, v)) / lt; }
      return out;
    }
    knownAt(r, c) { const W = this.S + 2 * QUIET, rr = r + QUIET, cc = c + QUIET; if (rr < 0 || cc < 0 || rr >= W || cc >= W) return 0; return this.known[rr * W + cc]; }
  }
  function estimate(ph) {
    const S = ph.S, rows = [];
    for (let r = 0; r < S; r++) for (let c = 0; c < S; c++) if (ph.knownAt(r, c) >= 0) rows.push([r, c, ph.darkening(r, c), NB.map(([dr, dc]) => { const v = ph.knownAt(r + dr, c + dc); return v < 0 ? 0.5 : v; })]);
    let best = null;
    for (let b = 0.3; b <= 3.5001; b += 0.05) {
      const fp = footprints(ph.pitch, b); let dm = 0, mm = 0; const ms = [];
      for (const [, , d, x] of rows) { const m = new Float64Array(49);
        for (let i = 0; i < NB.length; i++) if (x[i]) { const f = fp.F[i], xi = x[i]; for (let j = 0; j < 49; j++) m[j] += xi * f[j]; }
        for (let j = 0; j < 49; j++) { m[j] += fp.far[j]; dm += d[j] * m[j]; mm += m[j] * m[j]; } ms.push(m); }
      const kappa = dm / Math.max(mm, 1e-9); let err = 0;
      rows.forEach(([, , d], i) => { const m = ms[i]; for (let j = 0; j < 49; j++) err += (d[j] - kappa * m[j]) ** 2; });
      if (!best || err < best.err) best = { err, blur: Math.round(b * 100) / 100, kappa };
    }
    ph.kappa = Math.max(best.kappa, 0.05);
    // model mismatch beyond the unknown neighbours' variance counts as noise (see reader2.py)
    let r2 = 0, uv = 0, cnt = 0;
    { const fp = footprints(ph.pitch, best.blur);
      for (const [, , d, x] of rows) for (let j = 0; j < 49; j++) {
        let m = fp.far[j], u = 0;
        for (let i = 0; i < NB.length; i++) { if (!x[i]) continue; const f = fp.F[i][j]; m += x[i] * f; if (x[i] === 0.5) u += f * f; }
        r2 += ((D / ph.kappa) * (d[j] - ph.kappa * m)) ** 2; uv += (D * D / 4) * u; cnt++;
      } }
    const mismatch2 = Math.max(0, (r2 - uv) / cnt);
    const vals = [];
    for (let r = -QUIET; r < S + QUIET; r++) for (let c = -QUIET; c < S + QUIET; c++) {
      const d = Math.min(r, c, S - 1 - r, S - 1 - c); if (d !== -3 && d !== -4) continue;
      vals.push(LIGHT - (D * ph.darkening(r, c)[24]) / ph.kappa);
    }
    const mean = vals.reduce((a, b) => a + b, 0) / vals.length, sd = Math.sqrt(vals.reduce((a, b) => a + (b - mean) ** 2, 0) / vals.length);
    return { blur: best.blur, noise: Math.max(3, Math.sqrt(sd * sd + mismatch2)) };
  }
  function decodeSymbol(sampler, corners, S, mirrored, level) {
    const ph = new Photo(sampler, corners, S, mirrored), est = estimate(ph), fp = footprints(ph.pitch, est.blur);
    const v = version(S, level), W = S + 2 * QUIET, state = Int8Array.from(ph.known); // -1 = undecided data
    const at = (r, c) => { const rr = r + QUIET, cc = c + QUIET; if (rr < 0 || cc < 0 || rr >= W || cc >= W) return 0; return state[rr * W + cc]; };
    const info = new Uint8Array(v.infoBits); let pos = 0;
    const filters = new Map();
    const cs = codes(S, level);
    for (let k = 0; k < 4; k++) {
      const code = cs[k], { rows, cols } = cosetPositions(S, k), sc = scramble(S, level, k, rows.length), llr = new Float64Array(rows.length);
      for (let i = 0; i < rows.length; i++) {
        const r = rows[i], c = cols[i], vals = NB.map(([dr, dc]) => at(r + dr, c + dc));
        const maskKey = k + ":" + vals.map((x) => (x >= 0 ? 1 : 0)).join("");
        let flt = filters.get(maskKey);
        if (!flt) { flt = stageFilter(fp, vals.map((x) => x >= 0), est.noise); filters.set(maskKey, flt); }
        const d = ph.darkening(r, c);
        let L = flt.bias;
        for (let j = 0; j < 49; j++) {
          let z = LIGHT - (D * d[j]) / ph.kappa + flt.base[j];
          for (const n of flt.kn) if (vals[n]) z += D * fp.F[n][j];
          L += z * flt.w[j];
        }
        llr[i] = sc[i] ? -L : L;
      }
      for (let i = 0; i < llr.length; i++) llr[i] = Math.max(-30, Math.min(30, llr[i]));
      // wrong level/orientation/format: raw decisions violate ~half the checks (see reader2.py)
      if (k === 0 && unsatisfiedFraction(code, llr) > 0.42) return null;
      const bits = ldpcDecode(code, llr); if (!bits) return null;
      info.set(bits.subarray(0, code.k), pos); pos += code.k;
      for (let i = 0; i < rows.length; i++) state[(rows[i] + QUIET) * W + cols[i] + QUIET] = bits[i] ^ sc[i];
    }
    const data = decodeInfoBits(v, info);
    return data ? { data, text: new TextDecoder().decode(data), S, level, mirrored, blur: est.blur, pitch: ph.pitch } : null;
  }
  function readGray(gray, w, h, opts = {}) {
    const maxSide = opts.maxSide || 2400, levels = opts.levels || "ABC";
    let g = gray, W = w, Hh = h, scale = 1;
    if (Math.max(w, h) > maxSide) { scale = Math.max(w, h) / maxSide; ({ g, W, H: Hh } = I.boxDownscale(gray, w, h, scale)); }
    else if (!(g instanceof Float32Array)) g = Float32Array.from(g);
    const Smp = I.makeSampler(g, W, Hh), found = [];
    for (const bin of [I.binAdaptive, I.binOtsu]) {
      for (const quad of I.candidateQuads(bin(g, W, Hh), W, Hh)) {
        const cx = quad.reduce((s, p) => s + p[0], 0) / 4, cy = quad.reduce((s, p) => s + p[1], 0) / 4;
        if (found.some((f) => I.inside([cx, cy], f.cornersLocal))) continue;
        // opts.skip: corners (input-image coordinates) of symbols already decoded elsewhere
        if (opts.skip && opts.skip.some((c) => I.inside([cx * scale, cy * scale], c))) continue;
        const loc = I.locate(Smp, quad); if (!loc) continue;
        const S = 2 * loc.n; if (!SIZES.includes(S)) continue;
        let res = null;
        for (const mirrored of [false, true]) { for (const lv of levels) { res = decodeSymbol(Smp, loc.corners, S, mirrored, lv); if (res) break; } if (res) break; }
        if (res) found.push({ ...res, cornersLocal: loc.corners, corners: loc.corners.map(([x, y]) => [x * scale, y * scale]) });
        if (opts.first && found.length) return found;
      }
    }
    return found;
  }
  function readImageData(img, opts) {
    const { data, width, height } = img, g = new Float32Array(width * height);
    for (let i = 0; i < g.length; i++) g[i] = 0.299 * data[4 * i] + 0.587 * data[4 * i + 1] + 0.114 * data[4 * i + 2];
    return readGray(g, width, height, opts);
  }
  return { encode, readGray, readImageData, version, SIZES, LEVELS, QUIET, footprints, profile, _ldpc: { makeIra, ldpcEncode, ldpcDecode } };
});
