/* PM257-PHOTO-NAV-TEST-2026-10-19-v1: run the actual viewer script in a DOM stub. */
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function main() {
  class Element {
    constructor(value = "") {
      this.value = value; this.style = {}; this.disabled = false;
      this.listeners = new Map(); this.classList = { toggle() {} };
      this.clientWidth = 950; this.clientHeight = 640;
    }
    addEventListener(name, listener) { this.listeners.set(name, listener); }
    change() { this.listeners.get("change")?.(); }
    click() { if (!this.disabled) this.onclick?.(); }
    getContext() { return { fillRect() {} }; }
    getBoundingClientRect() { return { left: 0, top: 0 }; }
  }
  class Select extends Element {
    constructor(values) {
      super(); this.options = values.map(value => ({ value })); this.selectedIndex = 0;
    }
    get value() { return this.options?.[this.selectedIndex]?.value; }
    set value(value) { if (this.options) this.selectedIndex = this.options.findIndex(o => o.value === value); }
  }
  const elements = new Map();
  for (const id of ["target", "previous", "next", "navigation", "comparison", "distance", "repeat", "cells", "dimensions", "measured", "record", "log", "png", "logcount", "fullscreen", "title", "shot", "viewport", "status", "manifest"]) elements.set(id, new Element());
  elements.set("profile", new Select(["A1", "A2", "B1", "B2"]));
  elements.set("variant", new Select(["1", "2", "3"]));
  elements.get("distance").value = "0.5";
  elements.get("repeat").value = "1";
  const cases = [];
  for (let variant = 1; variant <= 3; variant++) for (const id of ["A1", "A2", "B1", "B2"]) cases.push({ id: `${id}-V${variant}`, variant, S: 1, quiet: 4, rows: ["1"], profile: "dense/A", payload_bytes: 128, board_side_units: 94, code_origin_units: 18, marker_ids: [] });
  elements.get("manifest").textContent = JSON.stringify({ kit_id: "NAV-REGRESSION", cases, markers: {} });
  const listeners = new Map();
  const document = { getElementById: id => elements.get(id), addEventListener: (name, listener) => listeners.set(name, listener) };
  const window = { devicePixelRatio: 1, addEventListener() {}, requestAnimationFrame(callback) { callback(); } };
  const html = fs.readFileSync(path.join(__dirname, "../research/density/screen_viewer.html"), "utf8");
  const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
  vm.runInNewContext(script, { document, window, localStorage: { getItem() { return null; }, setItem() {} } });
  const el = id => elements.get(id);
  const key = name => listeners.get("keydown")({ key: name, target: { tagName: "BODY" }, preventDefault() {} });

  for (const variant of ["1", "2", "3"]) {
    el("variant").value = variant; el("variant").change();
    el("profile").value = "A1"; el("profile").change();
    assert.equal(el("previous").disabled, true);
    assert.equal(el("next").disabled, false);
    assert.match(el("navigation").textContent, /Target 1 of 4/);
    el("repeat").value = "7";
    for (let i = 0; i < 12; i++) { el("previous").click(); el("previous").onclick(); key("ArrowLeft"); }
    assert.equal(el("profile").value, "A1");
    assert.equal(el("repeat").value, "7");

    for (const expected of ["A2", "B1", "B2"]) { el("next").click(); assert.equal(el("profile").value, expected); }
    assert.equal(el("next").disabled, true);
    assert.equal(el("previous").disabled, false);
    assert.match(el("navigation").textContent, /Target 4 of 4.*Last target/);
    el("repeat").value = "9";
    const width = el("target").width;
    for (let i = 0; i < 12; i++) { el("next").click(); el("next").onclick(); key("ArrowRight"); }
    assert.equal(el("profile").value, "B2");
    assert.equal(el("variant").value, variant);
    assert.equal(el("repeat").value, "9");
    assert.equal(el("target").width, width);

    key("ArrowLeft"); assert.equal(el("profile").value, "B1"); assert.equal(el("next").disabled, false);
    key("1"); assert.equal(el("profile").value, "A1"); assert.equal(el("previous").disabled, true);
    key("4"); assert.equal(el("profile").value, "B2"); assert.equal(el("next").disabled, true);
    el("profile").value = "A2"; el("profile").change();
    assert.equal(el("previous").disabled, false); assert.equal(el("next").disabled, false);
  }
  console.log("ok: buttons, keyboard arrows, disabled boundaries, counters and payload sets do not wrap");
}
main();
