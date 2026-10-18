// Headless check of the UI concept's JavaScript: runs every renderer against the embedded real run with a stub DOM,
// then fails on runtime errors or on NaN / undefined / Infinity in the generated markup. No browser needed.
// Usage: node scripts/check_ui_sample.mjs mockups/<file>-ui-concept.html
import fs from "node:fs";
import vm from "node:vm";

const file = process.argv[2];
const html = fs.readFileSync(file, "utf8");
const js = html.match(/<script>([\s\S]*)<\/script>/)[1];
// theme variables from :root, served through a getComputedStyle stub so a mistyped variable name shows up as ""
const rootCss = html.match(/:root\{([\s\S]*?)\}/)[1];
const vars = Object.fromEntries([...rootCss.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)].map(m => [m[1], m[2].trim()]));
const missing = new Set();
const getComputedStyle = () => ({ getPropertyValue: n => { if (!(n in vars)) missing.add(n); return vars[n] ?? ""; } });
const outsideRoot = html.slice(html.indexOf("}", html.indexOf(":root{")));
const strayHex = outsideRoot.match(/#[0-9a-fA-F]{3,8}\b/g) || [];
const els = {};
const mk = () => {
  const e = { innerHTML: "", textContent: "", value: "", checked: false, disabled: false, style: {}, dataset: {}, children: [],
    offsetTop: 0, parentNode: null,
    classList: { _s: new Set(), add(c) { this._s.add(c); }, remove(c) { this._s.delete(c); }, toggle(c, on) { on ?? !this._s.has(c) ? this._s.add(c) : this._s.delete(c); }, contains(c) { return this._s.has(c); } },
    setAttribute(k, v) { this[k] = v; }, appendChild(c) { this.children.push(c); c.parentNode = this; return c; }, insertBefore(c) { return this.appendChild(c); },
    insertAdjacentHTML(_, h) { this.innerHTML += h; }, querySelectorAll() { return []; }, querySelector() { return mk(); },
    scrollIntoView() {}, remove() {}, addEventListener() {}, click() {} };
  return e;
};
const document = { getElementById: id => (els[id] ??= mk()), createElement: () => mk(), createTextNode: t => ({ t }), addEventListener() {},
  querySelectorAll: () => [], querySelector: () => mk(), body: mk(), activeElement: null };
const ctx = { document, getComputedStyle, window: {}, innerWidth: 1400, performance, console, setTimeout: () => 0, setInterval: () => 0, clearInterval() {},
  requestAnimationFrame: () => 0, CSS: { escape: s => s }, navigator: {}, URL, Blob, Math, JSON, Set, Object, Array, String, Number, RegExp, Promise };
vm.createContext(ctx);
vm.runInContext(js + `
;globalThis.__out = {};
state.scored = new Set(papers.map(p => p.key));
drawMap(); __out.map = document.getElementById("map").innerHTML;
drawPyramid(); __out.pyr = document.getElementById("pyr").innerHTML;
render(true); __out.list = document.getElementById("list").innerHTML;
for (const t of ["funnel", "forest", "gap"]) { tab = t; drawCanvas(); __out[t] = { svg: document.getElementById("viz").innerHTML, sub: document.getElementById("cvSub").innerHTML, foot: document.getElementById("cvFoot").textContent, chips: document.getElementById("ocChips").innerHTML }; }
for (const o of ["Hospitalisation", "Mortality / survival"]) { ocFilter = o; tab = "forest"; drawCanvas(); __out["forest:" + o] = { svg: document.getElementById("viz").innerHTML, sub: document.getElementById("cvSub").innerHTML }; }
applyKeys("test", [papers[0].key]); __out.filtered = visible().length;
`, ctx);
const out = ctx.__out;
let bad = 0;
for (const [k, v] of Object.entries(out)) {
  const s = typeof v === "string" ? v : JSON.stringify(v);
  const m = s.match(/NaN|undefined|Infinity|fill=\\?"\\?"|stroke=\\?"\\?"|stop-color=\\?"\\?"|background:\s*[;"\\]/g);
  if (m) { bad++; console.log(`FAIL ${k}: contains ${[...new Set(m)].join(", ")}`); }
}
if (missing.size) { bad++; console.log(`FAIL theme variables used but not defined in :root: ${[...missing].join(", ")}`); }
if (strayHex.length) { bad++; console.log(`FAIL hard-coded colours outside :root: ${[...new Set(strayHex)].join(", ")}`); }
console.log(`theme: ${Object.keys(vars).length} variables in :root, ${missing.size} missing, ${strayHex.length} stray hex colours`);
const strip = h => h.replace(/<[^>]+>/g, "");
console.log("funnel :", strip(out.funnel.sub));
console.log("forest :", strip(out.forest.sub));
console.log("  chips:", strip(out.forest.chips).replace(/\s+/g, " "));
console.log("  rows :", (out.forest.svg.match(/class="fr"/g) || []).length, "| hosp rows:", (out["forest:Hospitalisation"].svg.match(/class="fr"/g) || []).length);
console.log("gap    :", strip(out.gap.sub));
console.log("  cells:", (out.gap.svg.match(/class="cell/g) || []).length, "filled,", (out.gap.svg.match(/stroke-dasharray="2 2"/g) || []).length, "empty");
console.log("funnel nodes:", (out.funnel.svg.match(/class="nd/g) || []).length, "links:", (out.funnel.svg.match(/class="lk"/g) || []).length);
console.log("cards:", (out.list.match(/<article/g) || []).length, "| map dots:", (out.map.match(/class="dot/g) || []).length, "| keys filter ->", out.filtered);
console.log(bad ? `\n${bad} renderer(s) produced bad values` : "\nall renderers ran; no NaN/undefined/Infinity");
process.exit(bad ? 1 : 0);
