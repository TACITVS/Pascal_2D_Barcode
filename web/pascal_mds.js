/* PASCAL-MDS 2D barcode: encoder, decoder and photo reader.
 * JavaScript port of the Python reference (pascal_mds/), same format (SPEC.md).
 * Works in browsers and Node.  No dependencies. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.PascalMDS = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";
  const P = 257;
  const INV = new Int32Array(P);
  for (let a = 1; a < P; a++) { let r = 1, b = a, e = P - 2; while (e) { if (e & 1) r = (r * b) % P; b = (b * b) % P; e >>= 1; } INV[a] = r; }
  const mod = (a) => ((a % P) + P) % P;

  // ------------------------------------------------------------ GF(257), Pascal basis
  function differenceDiagonal(values) {
    let row = values.map(mod); const diag = [];
    while (row.length) {
      diag.push(row[row.length - 1]);
      const next = new Array(row.length - 1);
      for (let j = 0; j < next.length; j++) next[j] = mod(row[j + 1] - row[j]);
      row = next;
    }
    return diag;
  }
  // f(K..K+count-1) for deg f < K with f(x) = values[x]: additions only (Pascal's rule).
  function pascalExtend(values, count) {
    const b = differenceDiagonal(values), out = [];
    for (let s = 0; s < count; s++) {
      for (let k = b.length - 2; k >= 0; k--) { const t = b[k] + b[k + 1]; b[k] = t >= P ? t - P : t; }
      out.push(b[0]);
    }
    return out;
  }
  const trim = (a) => { while (a.length && a[a.length - 1] === 0) a.pop(); return a; };
  function polyEval(a, x) { let acc = 0; for (let i = a.length - 1; i >= 0; i--) acc = (acc * x + a[i]) % P; return acc; }
  function polyMul(a, b) {
    if (!a.length || !b.length) return [];
    const out = new Array(a.length + b.length - 1).fill(0);
    for (let i = 0; i < a.length; i++) if (a[i]) for (let j = 0; j < b.length; j++) out[i + j] = (out[i + j] + a[i] * b[j]) % P;
    return trim(out);
  }
  function polySub(a, b) {
    const n = Math.max(a.length, b.length), out = new Array(n);
    for (let i = 0; i < n; i++) out[i] = mod((a[i] || 0) - (b[i] || 0));
    return trim(out);
  }
  function polyDivmod(a, b) {
    const rem = a.slice();
    if (rem.length < b.length) return [[], trim(rem)];
    const inv = INV[b[b.length - 1]], quot = new Array(rem.length - b.length + 1).fill(0);
    for (let s = rem.length - b.length; s >= 0; s--) {
      const c = (rem[s + b.length - 1] * inv) % P; quot[s] = c;
      if (c) for (let j = 0; j < b.length; j++) rem[s + j] = mod(rem[s + j] - c * b[j]);
    }
    return [trim(quot), trim(rem.slice(0, b.length - 1))];
  }
  function interpolate(xs, ys) {
    const n = xs.length, c = ys.map(mod);
    for (let lv = 1; lv < n; lv++) for (let i = n - 1; i >= lv; i--) c[i] = mod((c[i] - c[i - 1]) * INV[mod(xs[i] - xs[i - lv])]);
    let poly = n ? [c[n - 1]] : [];
    for (let i = n - 2; i >= 0; i--) {
      const sh = [0].concat(poly);
      for (let j = 0; j < poly.length; j++) sh[j] = mod(sh[j] - xs[i] * poly[j]);
      sh[0] = (sh[0] + c[i]) % P; poly = sh;
    }
    return trim(poly);
  }
  // Gao's Reed-Solomon decoder; returns monomial coefficients or null.
  function gaoDecode(xs, ys, k) {
    const n = xs.length; if (n < k) return null;
    let g0 = [1]; for (const x of xs) g0 = polyMul(g0, [mod(-x), 1]);
    let r0 = g0, r1 = interpolate(xs, ys), v0 = [], v1 = [1];
    while (r1.length - 1 >= (n + k) / 2) {
      const [q, rem] = polyDivmod(r0, r1);
      r0 = r1; r1 = rem;
      const nv = polySub(v0, polyMul(q, v1)); v0 = v1; v1 = nv;
    }
    if (!v1.length) return null;
    const [f, rem] = polyDivmod(r1, v1);
    if (rem.length || f.length > k) return null;
    return f;
  }

  // ------------------------------------------------------------ layout
  const SIZES = []; for (let n = 11; n <= 47; n += 2) SIZES.push(n);
  const LEVELS = "LMQH";
  const FRACTION = { L: 0.07, M: 0.15, Q: 0.25, H: 0.30 };
  const TARGET = 10n ** 10n; // miscorrection target 10^-10, exact
  const combCache = new Map();
  function comb(n, k) {
    const key = n * 1000 + k; if (combCache.has(key)) return combCache.get(key);
    let r = 1n; for (let i = 0; i < k; i++) r = (r * BigInt(n - i)) / BigInt(i + 1);
    combCache.set(key, r); return r;
  }
  function safe(kept, errors, redundancy) {
    if (redundancy <= 0) return false;
    let vol = 0n; for (let i = 0; i <= errors; i++) vol += comb(kept, i) * 256n ** BigInt(i);
    return vol * TARGET <= 257n ** BigInt(redundancy);
  }
  const versions = new Map();
  function version(n, level) {
    const key = n + level; if (versions.has(key)) return versions.get(key);
    if (!SIZES.includes(n) || !LEVELS.includes(level)) throw new Error("bad version");
    const m = n - 2, N = (m * m - 1) / 8, t = Math.max(1, Math.ceil(FRACTION[level] * N));
    let guard = 0; while (!safe(N, t, 2 * t + guard)) guard++;
    const r = 2 * t + guard, K = N - r, room = K - 1;
    const v = { n, level, N, K, r, t, guard, capacity: Math.max(0, room - (room - 1 <= 31 ? 1 : 2)) };
    versions.set(key, v); return v;
  }
  function acceptable(v, errors, erasures) { return 2 * errors + erasures <= v.r - v.guard && safe(v.N - erasures, errors, v.r - erasures); }
  function maxErasures(v) { let e = v.r - v.guard; while (e > 0 && !acceptable(v, 0, e)) e--; return e; }
  const placements = new Map();
  function placement(n) {
    if (placements.has(n)) return placements.get(n);
    const m = n - 2, out = []; let right = m - 1, up = true;
    while (right >= 0) {
      const cols = right >= 1 ? [right, right - 1] : [right];
      for (let s = 0; s < m; s++) { const i = up ? m - 1 - s : s; for (const j of cols) out.push([i + 1, j + 1]); }
      right -= 2; up = !up;
    }
    placements.set(n, out); return out;
  }
  function scrambler(level, count) {
    let st = Math.imul(0x2545f491, LEVELS.indexOf(level) + 1) >>> 0; const out = new Array(count);
    for (let i = 0; i < count; i++) { st ^= st << 13; st >>>= 0; st ^= st >>> 17; st ^= st << 5; st >>>= 0; out[i] = st >>> 24; }
    return out;
  }
  function frameValue(r, c, n) {
    if (c === 0 || r === n - 1) return 1;
    if (r === 0) return c % 2 === 0 ? 1 : 0;
    return r % 2 === 0 ? 1 : 0; // c === n - 1
  }

  // ------------------------------------------------------------ text mode
  const enc = new TextEncoder(), dec = new TextDecoder("utf-8");
  const TOKENS = [];
  for (const ch of "abcdefghijklmnopqrstuvwxyz0123456789 ./:-_?=&%#@+~!*,;'()\n") TOKENS.push([ch.charCodeAt(0)]);
  for (const s of ["https://", "www.", ".com"]) TOKENS.push(Array.from(enc.encode(s)));
  const CAPS = 61, SHIFT = 62, ESC = 63;
  const LONG = TOKENS.map((t, i) => [t, i]).filter(([t]) => t.length > 1).sort((a, b) => b[0].length - a[0].length);
  const SINGLE = new Map(); TOKENS.forEach((t, i) => { if (t.length === 1) SINGLE.set(t[0], i); });
  const isLetter = (b) => (b >= 65 && b <= 90) || (b >= 97 && b <= 122);
  function packText(data) {
    const bits = []; const put = (v, w) => { for (let i = w - 1; i >= 0; i--) bits.push((v >> i) & 1); };
    let caps = false, i = 0;
    outer: while (i < data.length) {
      for (const [tok, idx] of LONG) {
        let ok = i + tok.length <= data.length;
        for (let j = 0; ok && j < tok.length; j++) if (data[i + j] !== tok[j]) ok = false;
        if (ok) { put(idx, 6); i += tok.length; continue outer; }
      }
      const b = data[i];
      if (isLetter(b)) {
        const upper = b <= 90;
        if (upper !== caps) {
          let run = 0; while (i + run < data.length && isLetter(data[i + run]) && (data[i + run] <= 90) === upper) run++;
          if (run >= 2) { put(CAPS, 6); caps = upper; } else put(SHIFT, 6);
        }
        put(SINGLE.get(b | 0x20), 6);
      } else if (SINGLE.has(b)) put(SINGLE.get(b), 6);
      else { put(ESC, 6); put(b, 8); }
      i++;
    }
    while (bits.length % 8) bits.push(1);
    const out = new Uint8Array(bits.length / 8);
    for (let j = 0; j < out.length; j++) { let v = 0; for (let k = 0; k < 8; k++) v = (v << 1) | bits[8 * j + k]; out[j] = v; }
    return out;
  }
  function unpackText(packed) {
    const bits = []; for (const b of packed) for (let i = 7; i >= 0; i--) bits.push((b >> i) & 1);
    const out = []; let pos = 0, caps = false, shift = false;
    const take = (w) => { let v = 0; for (let i = 0; i < w; i++) v = (v << 1) | bits[pos++]; return v; };
    while (bits.length - pos >= 6) {
      const code = take(6);
      if (code === ESC) { if (bits.length - pos < 8) break; out.push(take(8)); }
      else if (code === CAPS) caps = !caps;
      else if (code === SHIFT) { shift = true; continue; }
      else { let tok = TOKENS[code]; if (code < 26 && caps !== shift) tok = [tok[0] - 32]; out.push(...tok); }
      shift = false;
    }
    return new Uint8Array(out);
  }

  // ------------------------------------------------------------ encoder
  function header(mode, len) {
    if (len <= 31) return [(mode << 6) | len];
    if (len >= 8192) throw new Error("payload too long");
    return [(mode << 6) | 0x20 | (len >> 8), len & 0xff];
  }
  function bestPayload(data, mode) {
    if (mode === "bytes") return [0, data];
    const packed = packText(data);
    if (mode === "text") return [1, packed];
    return packed.length < data.length ? [1, packed] : [0, data];
  }
  function encode(input, level = "M", size = null, mode = "auto") {
    const data = typeof input === "string" ? enc.encode(input) : Uint8Array.from(input);
    const [modeId, payload] = bestPayload(data, mode);
    const sizes = size ? [size] : SIZES; let v = null;
    for (const n of sizes) { const c = version(n, level); if (payload.length <= c.capacity) { v = c; break; } }
    if (!v) throw new Error(`payload needs ${payload.length} bytes; level ${level} holds at most ${version(sizes[sizes.length - 1], level).capacity}`);
    const msg = header(modeId, payload.length).concat(Array.from(payload));
    while (msg.length < v.K) msg.push(0);
    // Theorem 1: parity is affine in the pad s with slope C(x, K-1) != 0, so some s <= r works.
    let parity = pascalExtend(msg, v.r);
    const unit = pascalExtend(new Array(v.K - 1).fill(0).concat([1]), v.r);
    let pad = 0;
    while (parity.some((c) => c === 256)) { parity = parity.map((c, i) => { const s = c + unit[i]; return s >= P ? s - P : s; }); pad++; }
    msg[v.K - 1] = pad;
    const word = msg.concat(parity), n = v.n;
    const grid = []; for (let r = 0; r < n; r++) { const row = new Uint8Array(n); for (let c = 0; c < n; c++) if (r === 0 || c === 0 || r === n - 1 || c === n - 1) row[c] = frameValue(r, c, n); grid.push(row); }
    const mask = scrambler(level, v.N), cells = placement(n);
    for (let i = 0; i < v.N; i++) { const byte = word[i] ^ mask[i]; for (let b = 0; b < 8; b++) { const [r, c] = cells[8 * i + b]; grid[r][c] = (byte >> (7 - b)) & 1; } }
    return { version: v, modules: grid, pad };
  }

  // ------------------------------------------------------------ decoder
  function readBytes(modules, mirrored) {
    const n = modules.length, cells = placement(n), out = [];
    for (let i = 0; i < (cells.length - 1) / 8; i++) {
      let byte = 0;
      for (let b = 0; b < 8; b++) { let [r, c] = cells[8 * i + b]; if (mirrored) [r, c] = [n - 1 - c, n - 1 - r]; byte = (byte << 1) | (modules[r][c] ? 1 : 0); }
      out.push(byte);
    }
    return out;
  }
  function symbolConfidence(conf, mirrored) {
    const n = conf.length, cells = placement(n), out = [];
    for (let i = 0; i < (cells.length - 1) / 8; i++) {
      let w = 1e9;
      for (let b = 0; b < 8; b++) { let [r, c] = cells[8 * i + b]; if (mirrored) [r, c] = [n - 1 - c, n - 1 - r]; w = Math.min(w, conf[r][c]); }
      out.push(w);
    }
    return out;
  }
  function decodeCodeword(v, received) {
    const xs = [], ys = [];
    received.forEach((y, i) => { if (y !== null) { xs.push(i); ys.push(y); } });
    const erasures = v.N - xs.length;
    if (!acceptable(v, 0, erasures)) return null;
    const f = gaoDecode(xs, ys, v.K); if (!f) return null;
    const word = []; for (let x = 0; x < v.N; x++) word.push(polyEval(f, x));
    let errors = 0; for (const x of xs) if (word[x] !== received[x]) errors++;
    if (!acceptable(v, errors, erasures) || word.some((c) => c > 255)) return null;
    return { word, errors, erasures };
  }
  function parseMessage(v, m) {
    const mode = m[0] >> 6; let len, h;
    if (m[0] & 0x20) { len = ((m[0] & 0x1f) << 8) | m[1]; h = 2; } else { len = m[0] & 0x1f; h = 1; }
    const end = h + len;
    if (mode > 1 || end > v.K - 1) return null;
    for (let i = end; i < v.K - 1; i++) if (m[i]) return null;
    const payload = Uint8Array.from(m.slice(h, end));
    return mode === 1 ? unpackText(payload) : payload;
  }
  function decodeBytes(n, reads, rounds = 6) {
    for (let round = 0; round <= rounds; round++) {
      for (const { raw, conf, mirrored } of reads) {
        if (round && !conf) continue;
        for (const level of LEVELS) {
          const v = version(n, level); if (v.capacity <= 0) continue;
          const count = Math.round((v.r - v.guard) * round / rounds);
          if (round && (count === 0 || !acceptable(v, 0, count))) continue;
          const mask = scrambler(level, v.N);
          const rec = raw.map((b, i) => b ^ mask[i]);
          if (count) { const order = [...rec.keys()].sort((a, b) => conf[a] - conf[b] || a - b); for (let i = 0; i < count; i++) rec[order[i]] = null; }
          const res = decodeCodeword(v, rec); if (!res) continue;
          const data = parseMessage(v, res.word.slice(0, v.K));
          if (data) return { data, text: dec.decode(data), version: v, errors: res.errors, erasures: res.erasures, mirrored };
        }
      }
    }
    return null;
  }
  function decodeModules(modules, confidence = null) {
    const n = modules.length;
    if (!SIZES.includes(n)) throw new Error("not a PASCAL-MDS matrix");
    const reads = [false, true].map((m) => ({ raw: readBytes(modules, m), conf: confidence ? symbolConfidence(confidence, m) : null, mirrored: m }));
    return decodeBytes(n, reads);
  }

  // ------------------------------------------------------------ photo reader
  // gray: Float32Array (w*h, 0..255).  Mirrors pascal_mds/reader.py.
  function boxMean(g, w, h, rad) {
    const W = w + 1, ii = new Float64Array(W * (h + 1));
    for (let y = 0; y < h; y++) { let s = 0; for (let x = 0; x < w; x++) { s += g[y * w + x]; ii[(y + 1) * W + x + 1] = ii[y * W + x + 1] + s; } }
    const out = new Float32Array(w * h);
    for (let y = 0; y < h; y++) {
      const y0 = Math.max(0, y - rad), y1 = Math.min(h, y + rad + 1);
      for (let x = 0; x < w; x++) {
        const x0 = Math.max(0, x - rad), x1 = Math.min(w, x + rad + 1);
        out[y * w + x] = (ii[y1 * W + x1] - ii[y0 * W + x1] - ii[y1 * W + x0] + ii[y0 * W + x0]) / ((y1 - y0) * (x1 - x0));
      }
    }
    return out;
  }
  function binAdaptive(g, w, h) {
    const mean = boxMean(g, w, h, Math.max(7, Math.floor(Math.min(w, h) / 16)));
    const m = new Uint8Array(w * h); for (let i = 0; i < m.length; i++) m[i] = g[i] < mean[i] - 6 ? 1 : 0; return m;
  }
  function binOtsu(g, w, h) {
    const hist = new Float64Array(256); for (let i = 0; i < g.length; i++) hist[Math.max(0, Math.min(255, g[i] | 0))]++;
    let total = g.length, sum = 0; for (let i = 0; i < 256; i++) sum += i * hist[i];
    let c = 0, cm = 0, best = -1, t = -1;
    for (let i = 0; i < 255; i++) {
      c += hist[i]; cm += i * hist[i]; if (!c || c === total) continue;
      const m0 = cm / c, m1 = (sum - cm) / (total - c), b = (c / total) * (1 - c / total) * (m0 - m1) ** 2;
      if (b > best) { best = b; t = i; }
    }
    const m = new Uint8Array(w * h); if (t < 0) return m;
    for (let i = 0; i < m.length; i++) m[i] = g[i] <= t ? 1 : 0; return m;
  }
  function components(mask, w, h, minSide = 18) {
    const rr = [], ss = [], ee = [], rowStart = new Int32Array(h + 1);
    for (let y = 0; y < h; y++) {
      rowStart[y] = rr.length; let x = 0;
      while (x < w) { if (mask[y * w + x]) { const s = x; while (x < w && mask[y * w + x]) x++; rr.push(y); ss.push(s); ee.push(x); } else x++; }
    }
    rowStart[h] = rr.length;
    const parent = new Int32Array(rr.length); for (let i = 0; i < parent.length; i++) parent[i] = i;
    const find = (a) => { let r = a; while (parent[r] !== r) r = parent[r]; while (parent[a] !== r) { const nx = parent[a]; parent[a] = r; a = nx; } return r; };
    for (let y = 1; y < h; y++) {
      let a = rowStart[y - 1], b = rowStart[y]; const ae = rowStart[y], be = rowStart[y + 1];
      while (a < ae && b < be) {
        if (ss[a] <= ee[b] && ss[b] <= ee[a]) { const ra = find(a), rb = find(b); if (ra !== rb) parent[Math.max(ra, rb)] = Math.min(ra, rb); }
        if (ee[a] < ee[b]) a++; else b++;
      }
    }
    const groups = new Map();
    for (let i = 0; i < rr.length; i++) { const r = find(i); let g = groups.get(r); if (!g) { g = { y0: rr[i], y1: rr[i], x0: ss[i], x1: ee[i], pixels: 0, left: new Map(), right: new Map() }; groups.set(r, g); }
      g.y0 = Math.min(g.y0, rr[i]); g.y1 = Math.max(g.y1, rr[i]); g.x0 = Math.min(g.x0, ss[i]); g.x1 = Math.max(g.x1, ee[i]); g.pixels += ee[i] - ss[i];
      const l = g.left.get(rr[i]); if (l === undefined || ss[i] < l) g.left.set(rr[i], ss[i]);
      const rt = g.right.get(rr[i]); if (rt === undefined || ee[i] > rt) g.right.set(rr[i], ee[i]); }
    return [...groups.values()].filter((g) => g.y1 - g.y0 + 1 >= minSide && g.x1 - g.x0 >= minSide);
  }
  function convexHull(pts) {
    pts = pts.slice().sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
    const lower = [], upper = [];
    for (const p of pts) { while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0) lower.pop(); lower.push(p); }
    for (let i = pts.length - 1; i >= 0; i--) { const p = pts[i]; while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0) upper.pop(); upper.push(p); }
    return lower.slice(0, -1).concat(upper.slice(0, -1));
  }
  function compHull(g) {
    const pts = [];
    for (const [y, l] of g.left) { const r = g.right.get(y); pts.push([l, y], [l, y + 1], [r, y], [r, y + 1]); }
    return convexHull(pts);
  }
  function area(p) { let s = 0; for (let i = 0; i < p.length; i++) { const a = p[i], b = p[(i + 1) % p.length]; s += a[0] * b[1] - a[1] * b[0]; } return s / 2; }
  function hullQuad(hull) {
    if (hull.length < 4) return null;
    let cx = 0, cy = 0; for (const p of hull) { cx += p[0]; cy += p[1]; } cx /= hull.length; cy /= hull.length;
    const far = (f) => hull.reduce((best, p) => (f(p) > f(best) ? p : best), hull[0]);
    const a = far((p) => (p[0] - cx) ** 2 + (p[1] - cy) ** 2), c = far((p) => (p[0] - a[0]) ** 2 + (p[1] - a[1]) ** 2);
    const dx = c[0] - a[0], dy = c[1] - a[1], side = (p) => (p[0] - a[0]) * dy - (p[1] - a[1]) * dx;
    const b = far(side), e = far((p) => -side(p));
    if (side(b) <= 0 || side(e) >= 0) return null;
    let q = [a, b, c, e]; if (area(q) < 0) q = q.reverse(); return q;
  }
  function solve(A, bvec) { // least squares via normal equations + Gaussian elimination
    const n = A[0].length, M = []; for (let i = 0; i < n; i++) { M.push(new Float64Array(n + 1)); }
    for (let r = 0; r < A.length; r++) for (let i = 0; i < n; i++) { for (let j = 0; j < n; j++) M[i][j] += A[r][i] * A[r][j]; M[i][n] += A[r][i] * bvec[r]; }
    for (let c = 0; c < n; c++) {
      let piv = c; for (let r = c + 1; r < n; r++) if (Math.abs(M[r][c]) > Math.abs(M[piv][c])) piv = r;
      [M[c], M[piv]] = [M[piv], M[c]]; if (Math.abs(M[c][c]) < 1e-12) return null;
      for (let r = 0; r < n; r++) if (r !== c) { const f = M[r][c] / M[c][c]; for (let j = c; j <= n; j++) M[r][j] -= f * M[c][j]; }
    }
    return M.map((row, i) => row[n] / row[i]);
  }
  function homography(src, dst) {
    const A = [], b = [];
    for (let i = 0; i < src.length; i++) { const [x, y] = src[i], [u, v] = dst[i];
      A.push([x, y, 1, 0, 0, 0, -u * x, -u * y]); b.push(u); A.push([0, 0, 0, x, y, 1, -v * x, -v * y]); b.push(v); }
    const s = solve(A, b); return s ? s.concat([1]) : null;
  }
  function applyH(H, x, y) { const w = H[6] * x + H[7] * y + H[8]; return [(H[0] * x + H[1] * y + H[2]) / w, (H[3] * x + H[4] * y + H[5]) / w]; }
  function cornersH(c, n) { return homography([[0, 0], [n, 0], [n, n], [0, n]], c); }
  function makeSampler(g, w, h) {
    return (x, y) => {
      let xf = Math.min(Math.max(x - 0.5, 0), w - 1.001), yf = Math.min(Math.max(y - 0.5, 0), h - 1.001);
      const x0 = xf | 0, y0 = yf | 0, fx = xf - x0, fy = yf - y0, i = y0 * w + x0;
      return g[i] * (1 - fx) * (1 - fy) + g[i + 1] * fx * (1 - fy) + g[i + w] * (1 - fx) * fy + g[i + w + 1] * fx * fy;
    };
  }
  const sampleAt = (S, H, x, y) => { const [u, v] = applyH(H, x, y); return S(u, v); };
  function pearson(vals, exp) {
    const n = vals.length; let mv = 0, me = 0; for (let i = 0; i < n; i++) { mv += vals[i]; me += exp[i]; } mv /= n; me /= n;
    let sge = 0, sgg = 0, see = 0; for (let i = 0; i < n; i++) { const g = -(vals[i] - mv), e = exp[i] - me; sge += g * e; sgg += g * g; see += e * e; }
    const d = Math.sqrt(sgg * see); return d > 0 ? sge / d : 0;
  }
  const templates = new Map();
  function frameTemplate(n) {
    if (templates.has(n)) return templates.get(n);
    const xs = [], ys = [], ex = [];
    for (let i = 0; i < n; i++) {
      xs.push(0.5, i + 0.5); ys.push(i + 0.5, n - 0.5); ex.push(1, 1);
      if (i > 0 && i < n - 1) { const t = i % 2 === 0 ? 1 : -1; xs.push(i + 0.5, n - 0.5); ys.push(0.5, i + 0.5); ex.push(t, t); }
      xs.push(-0.5, i + 0.5, i + 0.5, n + 0.5); ys.push(i + 0.5, -0.5, n + 0.5, i + 0.5); ex.push(-1, -1, -1, -1);
    }
    const t = { xs, ys, ex }; templates.set(n, t); return t;
  }
  function frameScore(S, H, n) { const t = frameTemplate(n); return pearson(t.xs.map((x, i) => sampleAt(S, H, x, t.ys[i])), t.ex); }
  const U24 = Array.from({ length: 24 }, (_, i) => 0.04 + (0.92 * i) / 23);
  const SOLID = (() => { const xs = [], ys = [], ex = [], IN = 0.008, OUT = -0.03;
    for (const u of U24) { xs.push(IN); ys.push(u); ex.push(1); } for (const u of U24) { xs.push(u); ys.push(1 - IN); ex.push(1); }
    for (const u of U24) { xs.push(OUT); ys.push(u); ex.push(-1); } for (const u of U24) { xs.push(u); ys.push(1 - OUT); ex.push(-1); }
    for (const u of U24) { xs.push(u); ys.push(OUT); ex.push(-1); } for (const u of U24) { xs.push(1 - OUT); ys.push(u); ex.push(-1); }
    return { xs, ys, ex }; })();
  function solidScore(S, c) { const H = cornersH(c, 1); if (!H) return 0; return pearson(SOLID.xs.map((x, i) => sampleAt(S, H, x, SOLID.ys[i])), SOLID.ex); }
  function timingScore(S, c, n) {
    const H = cornersH(c, n); if (!H) return 0; const vals = [], ex = [];
    for (let i = 1; i < n - 1; i++) { const e = i % 2 === 0 ? 1 : -1; vals.push(sampleAt(S, H, i + 0.5, 0.5)); ex.push(e); }
    for (let i = 1; i < n - 1; i++) { const e = i % 2 === 0 ? 1 : -1; vals.push(sampleAt(S, H, n - 0.5, i + 0.5)); ex.push(e); }
    return pearson(vals, ex);
  }
  function intersect(l1, l2) {
    const [p, d] = l1, [q, e] = l2, det = d[0] * -e[1] - -e[0] * d[1];
    if (Math.abs(det) < 1e-9) return null;
    const rx = q[0] - p[0], ry = q[1] - p[1], s = (rx * -e[1] - -e[0] * ry) / det;
    return [p[0] + s * d[0], p[1] + s * d[1]];
  }
  function outerEnvelope(us, ds, tol) {
    let keep = us.map(() => true), coef = null;
    for (let it = 0; it < 6; it++) {
      const A = [], b = []; us.forEach((u, i) => { if (keep[i]) { A.push([1, u]); b.push(ds[i]); } });
      if (A.length < 3) return null;
      coef = solve(A, b); if (!coef) return null;
      const nk = us.map((u, i) => { const r = ds[i] - (coef[0] + coef[1] * u); return r <= tol && r >= -4 * tol; });
      if (nk.every((k, i) => k === keep[i])) break; keep = nk;
    }
    return coef;
  }
  function percentile(arr, p) { const a = Float64Array.from(arr).sort(); const pos = (a.length - 1) * p / 100, lo = Math.floor(pos); return a[lo] + (a[Math.min(lo + 1, a.length - 1)] - a[lo]) * (pos - lo); }
  function fitSides(S, H, sides, depths, tol) {
    if (!H) return null; const lines = {};
    for (const name of ["left", "bottom", "top", "right"]) {
      const { u, pts, normal } = sides[name];
      const prof = pts.map(([px, py]) => depths.map((d) => sampleAt(S, H, px - d * normal[0], py - d * normal[1])));
      const outer = []; prof.forEach((p) => outer.push(p[0], p[1], p[2]));
      const light = percentile(outer, 50), dark = percentile(prof.flat(), 5);
      if (light - dark < 12) return null;
      const thr = (light + dark) / 2, us = [], ds = [];
      prof.forEach((p, i) => {
        const j = p.findIndex((v) => v < thr); if (j <= 0) return;
        const v0 = p[j - 1], v1 = p[j], f = v0 !== v1 ? (v0 - thr) / (v0 - v1) : 0.5;
        us.push(u[i]); ds.push(depths[j - 1] + f * (depths[j] - depths[j - 1]));
      });
      if (us.length < 3) return null;
      const coef = outerEnvelope(us, ds, tol); if (!coef) return null;
      const umin = Math.min(...u), umax = Math.max(...u), ends = [];
      for (const t of [umin, umax]) {
        const fr = (t - u[0]) / (u[u.length - 1] - u[0]);
        const bx = pts[0][0] + (pts[pts.length - 1][0] - pts[0][0]) * fr, by = pts[0][1] + (pts[pts.length - 1][1] - pts[0][1]) * fr;
        const d = coef[0] + coef[1] * t; ends.push(applyH(H, bx - d * normal[0], by - d * normal[1]));
      }
      lines[name] = [ends[0], [ends[1][0] - ends[0][0], ends[1][1] - ends[0][1]]];
    }
    const c = [intersect(lines.left, lines.top), intersect(lines.top, lines.right), intersect(lines.right, lines.bottom), intersect(lines.bottom, lines.left)];
    return c.some((x) => !x) ? null : c;
  }
  const linspace = (a, b, n) => Array.from({ length: n }, (_, i) => a + ((b - a) * i) / (n - 1));
  const FREE_U = linspace(0.02, 0.98, 97), FREE_D = linspace(-0.04, 0.035, 41);
  const FREE_SIDES = {
    left: { u: FREE_U, pts: FREE_U.map((u) => [0, u]), normal: [-1, 0] }, bottom: { u: FREE_U, pts: FREE_U.map((u) => [u, 1]), normal: [0, 1] },
    top: { u: FREE_U, pts: FREE_U.map((u) => [u, 0]), normal: [0, -1] }, right: { u: FREE_U, pts: FREE_U.map((u) => [1, u]), normal: [1, 0] },
  };
  function refineFree(S, c) { return fitSides(S, cornersH(c, 1), FREE_SIDES, FREE_D, 0.004); }
  const N_D = linspace(-1.2, 0.6, 37);
  function refineCorners(S, c, n) {
    const idx = Array.from({ length: n }, (_, i) => i + 0.5), tim = idx.filter((_, i) => i % 2 === 0);
    const sides = { left: { u: idx, pts: idx.map((v) => [0, v]), normal: [-1, 0] }, bottom: { u: idx, pts: idx.map((v) => [v, n]), normal: [0, 1] },
      top: { u: tim, pts: tim.map((v) => [v, 0]), normal: [0, -1] }, right: { u: tim, pts: tim.map((v) => [n, v]), normal: [1, 0] } };
    return fitSides(S, cornersH(c, n), sides, N_D, 0.25);
  }
  function locate(S, quad) {
    const hyps = [];
    for (let k = 0; k < 4; k++) {
      const [bl, tl, tr, br] = [0, 1, 2, 3].map((i) => quad[(k + i) % 4]);
      hyps.push([tl, tr, br, bl], [tl, [tl[0] + br[0] - bl[0], tl[1] + br[1] - bl[1]], br, bl]);
    }
    const scored = hyps.map((c) => [solidScore(S, c), c]).sort((a, b) => b[0] - a[0]);
    let best = null;
    for (const [s0, c0] of scored.slice(0, 2)) {
      if (s0 < 0.5) continue; let c = c0, sc = s0;
      for (let it = 0; it < 4; it++) { const r = refineFree(S, c); if (!r) break; const rs = solidScore(S, r); if (rs < sc - 0.02) break; c = r; sc = rs; }
      let tBest = -1, n = 0; for (const m of SIZES) { const t = timingScore(S, c, m); if (t > tBest) { tBest = t; n = m; } }
      if (tBest < 0.4) continue;
      for (let it = 0; it < 3; it++) {
        const r = refineCorners(S, c, n); if (!r) break;
        if (timingScore(S, r, n) + 0.02 < timingScore(S, c, n)) break;
        const moved = Math.max(...r.map((p, i) => Math.max(Math.abs(p[0] - c[i][0]), Math.abs(p[1] - c[i][1])))); c = r; if (moved < 0.05) break;
      }
      const H = cornersH(c, n); if (!H) continue;
      const total = frameScore(S, H, n); if (!best || total > best.score) best = { corners: c, n, score: total };
    }
    return best && best.score >= 0.55 ? best : null;
  }
  function quadFit(xs, ys, vals) { return solve(xs.map((x, i) => [1, x, ys[i], x * x, x * ys[i], ys[i] * ys[i]]), vals); }
  const quadEval = (c, x, y) => c[0] + c[1] * x + c[2] * y + c[3] * x * x + c[4] * x * y + c[5] * y * y;
  function sampleModules(S, H, n) {
    const t = frameTemplate(n), vals = t.xs.map((x, i) => sampleAt(S, H, x, t.ys[i]));
    const dx = [], dy = [], dv = [], lx = [], ly = [], lv = [];
    t.ex.forEach((e, i) => { const X = t.xs[i] / n - 0.5, Y = t.ys[i] / n - 0.5; if (e > 0) { dx.push(X); dy.push(Y); dv.push(vals[i]); } else { lx.push(X); ly.push(Y); lv.push(vals[i]); } });
    const dc = quadFit(dx, dy, dv), lc = quadFit(lx, ly, lv); if (!dc || !lc) return null;
    const offs = [-0.18, 0, 0.18], bits = [], conf = [];
    for (let r = 0; r < n; r++) {
      const br = new Uint8Array(n), cr = new Float64Array(n);
      for (let c = 0; c < n; c++) {
        let acc = 0; for (const oy of offs) for (const ox of offs) acc += sampleAt(S, H, c + 0.5 + ox, r + 0.5 + oy); acc /= 9;
        const X = (c + 0.5) / n - 0.5, Y = (r + 0.5) / n - 0.5, d = quadEval(dc, X, Y), l = quadEval(lc, X, Y), thr = (d + l) / 2, half = Math.max((l - d) / 2, 1e-3);
        br[c] = acc < thr ? 1 : 0; cr[c] = Math.min(1, Math.abs(acc - thr) / half);
      }
      bits.push(br); conf.push(cr);
    }
    return { bits, conf };
  }
  function candidateQuads(mask, w, h, limit = 40) {
    const out = [];
    for (const g of components(mask, w, h)) {
      const bw = g.x1 - g.x0, bh = g.y1 - g.y0 + 1;
      if (Math.max(bw, bh) > 6 * Math.min(bw, bh) || g.pixels < 0.12 * bw * bh) continue;
      const hull = compHull(g), quad = hullQuad(hull); if (!quad) continue;
      const ha = area(hull); if (ha <= 0 || area(quad) < 0.75 * ha) continue;
      out.push([g.pixels, quad]);
    }
    return out.sort((a, b) => b[0] - a[0]).slice(0, limit).map((x) => x[1]);
  }
  function inside(p, poly) {
    let sign = null;
    for (let i = 0; i < 4; i++) { const a = poly[i], b = poly[(i + 1) % 4], s = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]) > 0; if (sign === null) sign = s; else if (s !== sign) return false; }
    return true;
  }
  /** Decode every symbol in a grey image (Float32Array or Uint8Array, row-major). */
  function readGray(gray, w, h, opts = {}) {
    const maxSide = opts.maxSide || 1200;
    let g = gray, W = w, Hh = h, scale = 1;
    if (Math.max(w, h) > maxSide) { // box downscale
      scale = Math.max(w, h) / maxSide; W = Math.round(w / scale); Hh = Math.round(h / scale); g = new Float32Array(W * Hh);
      for (let y = 0; y < Hh; y++) for (let x = 0; x < W; x++) {
        const x0 = Math.floor(x * scale), x1 = Math.max(x0 + 1, Math.floor((x + 1) * scale)), y0 = Math.floor(y * scale), y1 = Math.max(y0 + 1, Math.floor((y + 1) * scale));
        let s = 0, c = 0; for (let yy = y0; yy < Math.min(y1, h); yy++) for (let xx = x0; xx < Math.min(x1, w); xx++) { s += gray[yy * w + xx]; c++; }
        g[y * W + x] = s / c;
      }
    } else if (!(g instanceof Float32Array)) g = Float32Array.from(g);
    const S = makeSampler(g, W, Hh), found = [];
    for (const bin of [binAdaptive, binOtsu]) {
      for (const quad of candidateQuads(bin(g, W, Hh), W, Hh)) {
        const cx = quad.reduce((s, p) => s + p[0], 0) / 4, cy = quad.reduce((s, p) => s + p[1], 0) / 4;
        if (found.some((f) => inside([cx, cy], f.corners))) continue;
        const loc = locate(S, quad); if (!loc) continue;
        const H = cornersH(loc.corners, loc.n), sm = H && sampleModules(S, H, loc.n); if (!sm) continue;
        const reads = [false, true].map((m) => ({ raw: readBytes(sm.bits, m), conf: symbolConfidence(sm.conf, m), mirrored: m }));
        const d = decodeBytes(loc.n, reads);
        if (d) found.push({ ...d, corners: loc.corners });
        if (opts.first && found.length) break;
      }
      if (found.length) break;
    }
    return found.map((f) => ({ ...f, corners: f.corners.map(([x, y]) => [x * scale, y * scale]) }));
  }
  /** Decode from RGBA ImageData-like {data, width, height}. */
  function readImageData(img, opts) {
    const { data, width, height } = img, g = new Float32Array(width * height);
    for (let i = 0; i < g.length; i++) g[i] = 0.299 * data[4 * i] + 0.587 * data[4 * i + 1] + 0.114 * data[4 * i + 2];
    return readGray(g, width, height, opts);
  }

  // ------------------------------------------------------------ rendering
  function toSVG(sym, modulePx = 10, quiet = 2, dark = "#000", light = "#fff") {
    const n = sym.modules.length, total = (n + 2 * quiet) * modulePx; let d = "";
    sym.modules.forEach((row, r) => { let c = 0; while (c < n) { if (row[c]) { const s = c; while (c < n && row[c]) c++; d += `M${(s + quiet) * modulePx} ${(r + quiet) * modulePx}h${(c - s) * modulePx}v${modulePx}h-${(c - s) * modulePx}z`; } else c++; } });
    return `<svg xmlns="http://www.w3.org/2000/svg" width="${total}" height="${total}" viewBox="0 0 ${total} ${total}" shape-rendering="crispEdges"><rect width="100%" height="100%" fill="${light}"/><path fill="${dark}" d="${d}"/></svg>`;
  }

  return { encode, decodeModules, readGray, readImageData, toSVG, packText, unpackText, version, maxErasures, SIZES, LEVELS, pascalExtend, gaoDecode, polyEval };
});
