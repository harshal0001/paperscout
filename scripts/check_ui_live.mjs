// Replays a captured server event stream through the live page's JavaScript (stub DOM + stub EventSource), so the
// UI's event handling, renderers and theme are exercised without a browser. Three scenarios: a real run, a run that
// fails with an error, and a run that emits a warning.
// Usage: node scripts/check_ui_live.mjs [paperscout/static/index.html] [tests/fixtures/sse_live_sglt2.txt]
import fs from "node:fs";
import vm from "node:vm";

const page = process.argv[2] || "paperscout/static/index.html";
const fixture = process.argv[3] || "tests/fixtures/sse_live_sglt2.txt";
const html = fs.readFileSync(page, "utf8");
const js = html.match(/<script>([\s\S]*)<\/script>/)[1];
const vars = Object.fromEntries([...html.match(/:root\{([\s\S]*?)\}/)[1].matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)].map(m => [m[1], m[2].trim()]));
const events = fs.readFileSync(fixture, "utf8").split("\n").filter(l => l.startsWith("data: ")).map(l => l.slice(6));
const sleep = ms => new Promise(r => setTimeout(r, ms));

function makeWorld() {
  const missing = new Set(), els = {}, sel = {};
  const mk = (tag = "div") => {
    const e = { tag, _html: "", textContent: "", value: "", checked: false, disabled: false, style: {}, dataset: {}, children: [], className: "",
      offsetTop: 0, parentNode: null, title: "",
      get innerHTML() { return this._html; }, set innerHTML(v) { this._html = v; this.children = []; },
      classList: { _s: new Set(), add(c) { this._s.add(c); }, remove(c) { this._s.delete(c); }, toggle(c, on) { (on ?? !this._s.has(c)) ? this._s.add(c) : this._s.delete(c); }, contains(c) { return this._s.has(c); } },
      setAttribute(k, v) { this[k] = v; }, appendChild(c) { if (c.parentNode) c.parentNode.children = c.parentNode.children.filter(x => x !== c); this.children.push(c); c.parentNode = this; return c; },
      insertBefore(c, ref) { this.appendChild(c); if (ref) { this.children = this.children.filter(x => x !== c); this.children.splice(this.children.indexOf(ref), 0, c); } return c; },
      remove() { if (this.parentNode) this.parentNode.children = this.parentNode.children.filter(x => x !== this); this.parentNode = null; },
      insertAdjacentHTML(_, h) { this._html += h; }, querySelectorAll() { return []; }, querySelector() { return null; },
      scrollIntoView() {}, addEventListener() {}, click() {}, focus() {}, select() {} };
    return e;
  };
  const stages = ["plan", "retrieve", "rank", "synth"].map(s => { const li = mk("li"); li.className = "st"; li.s = s; sel[`.st[data-s="${s}"]`] = li; li.log = mk(); return li; });
  stages.forEach(li => { li.querySelector = q => (q === ".log" ? li.log : null); sel[`.st[data-s="${li.s}"] .log`] = li.log; });
  const document = {
    getElementById: id => (els[id] ??= mk()), createElement: t => mk(t), createTextNode: t => ({ t, parentNode: null }), addEventListener() {},
    querySelector: q => sel[q] ?? null,
    querySelectorAll: q => q === ".st" ? stages : q === ".st.active" ? stages.filter(li => li.className.includes("active")) : [],
    body: mk(), activeElement: null, documentElement: {} };
  ["sPapers", "sRel", "sTok", "sCost"].forEach(id => document.getElementById(id).dataset.v = 0);
  let es = null;
  class EventSource { constructor(url) { this.url = url; es = this; } close() { this.closed = true; } }
  const ctx = { document, EventSource, getComputedStyle: () => ({ getPropertyValue: n => { if (!(n in vars)) missing.add(n); return vars[n] ?? ""; } }),
    window: { scrollTo() {} }, history: { replaceState() {} }, location: { search: "" }, innerWidth: 1600, performance, console,
    setTimeout, setInterval: () => 1, clearInterval() {}, requestAnimationFrame: () => 0, CSS: { escape: s => s }, navigator: {}, URL, Blob,
    Math, JSON, Set, Object, Array, String, Number, RegExp, Promise, URLSearchParams };
  vm.createContext(ctx);
  vm.runInContext(js, ctx);
  const byId = new Proxy({}, { get: (_, id) => document.getElementById(id) });  // same lazily-created elements the page uses
  return { ctx, els: byId, stages, missing, get es() { return es; }, run: c => vm.runInContext(c, ctx) };
}

let failures = 0;
const check = (ok, msg) => { console.log(`${ok ? "PASS" : "FAIL"}  ${msg}`); if (!ok) failures++; };
const bad = s => (s.match(/NaN|undefined|Infinity|fill=\\?"\\?"|stroke=\\?"\\?"|stop-color=\\?"\\?"/g) || []);

async function scenario(name, stream) {
  console.log(`\n== ${name}`);
  const w = makeWorld();
  w.els.q.value = JSON.parse(stream[0]).question || "Do SGLT2 inhibitors reduce hospitalisation in heart failure?";
  w.run("start()");
  check(w.es && w.es.url.startsWith("/api/search?q="), `opens the event stream (${w.es?.url.slice(0, 60)}…)`);
  for (const d of stream) { w.es.onmessage({ data: d }); await sleep(5); }
  await sleep(4000);  // let the brief finish typing
  return w;
}

// 1) real captured run
{
  const w = await scenario("real captured run", events);
  const evs = events.map(e => JSON.parse(e)), sum = evs.find(e => e.type === "summary"), res = evs.find(e => e.type === "results");
  check(w.els.mPlan.textContent === evs[0].models.planner && w.els.mRank.textContent.startsWith(evs[0].models.ranker), "trace shows the real model names");
  check(w.stages.every(li => li.className === "st done"), `all 4 stages done (${w.stages.map(l => l.className).join(" | ")})`);
  check(!w.els.go.disabled, "Discover button re-enabled");
  check(w.els.alerts.innerHTML === "", "no alerts for a clean run");
  const pills = w.els.sum.children.filter(c => c.className === "cite");
  const expected = (sum.summary.match(/\[\d+\]/g) || []).length;
  check(pills.length === expected && expected > 0, `brief has ${pills.length} clickable citations (expected ${expected})`);
  check(!pills.some(p => p.classList.contains("bad")), "every citation resolves to a grounding paper");
  check(w.els.briefState.textContent === "grounded in screened abstracts", `brief state: "${w.els.briefState.textContent}"`);
  check(w.els.canvas.classList.contains("on"), "insight canvas shown");
  const visible = w.run("visible().length"), cards = (w.els.list.innerHTML.match(/<article/g) || []).length;
  check(cards === visible && cards > 0, `${cards} paper cards rendered (= visible after default filter)`);
  check(w.els.count.textContent === `${visible} / ${res.papers.length} papers`, `count label "${w.els.count.textContent}"`);
  for (const t of ["funnel", "forest", "gap"]) {
    w.run(`tab = "${t}"; drawCanvas();`);
    const b = bad(w.els.viz.innerHTML + w.els.cvSub.innerHTML);
    check(!b.length && w.els.viz.innerHTML.length > 500, `${t} renders (${w.els.viz.innerHTML.length} chars) ${b.length ? b.join(",") : ""}`);
    console.log(`      ${w.els.cvSub.innerHTML.replace(/<[^>]+>/g, "")}`);
  }
  check(w.els.cvSub.innerHTML.length && !bad(w.els.map.innerHTML + w.els.pyr.innerHTML + w.els.list.innerHTML).length, "map, pyramid and cards have no bad values");
  check(w.missing.size === 0, `all theme variables resolve (${[...w.missing].join(",") || "none missing"})`);
  check(w.els.sTok.dataset.v > 0, `tokens stat set (${w.els.sTok.dataset.v})`);
  // evidence-map bubbles must stay small whatever the citation counts (a 46,706-citation paper once drew r=37 px)
  for (const extreme of [0, 8, 46706, 5e6]) {
    w.run(`papers[0].cited_by = ${extreme}; drawMap();`);
    const rs = [...w.els.map.innerHTML.matchAll(/ r="([\d.]+)"/g)].map(m => +m[1]);
    check(rs.length && Math.max(...rs) <= 10 && Math.min(...rs) >= 3, `map bubbles within 3–10 px with max citations ${extreme} (got ${Math.min(...rs).toFixed(1)}–${Math.max(...rs).toFixed(1)})`);
  }
}

// 2) failure path: planner ok, then a server error
{
  const stream = [{ type: "run", run_id: "x", question: "Does anything happen at all here?" }, { type: "step", stage: "plan", status: "start" },
    { type: "error", message: "All searches failed: Europe PMC HTTP 503" }].map(e => JSON.stringify(e));
  const w = await scenario("server error mid-run", stream);
  check(w.els.alerts.innerHTML.includes('class="alert bad"') && w.els.alerts.innerHTML.includes("Europe PMC HTTP 503"), "error shown as a red alert with the server's message");
  check(!w.els.go.disabled, "button re-enabled after the error");
  check(w.els.list.innerHTML.includes("No papers to show"), "list explains there are no papers instead of spinning skeletons");
  check(!w.stages.some(li => li.className.includes("active")), "no stage left spinning");
  check(w.es.closed, "event stream closed");
}

// 3) warning path: same real run with one warning injected after the plan
{
  const stream = [...events]; stream.splice(3, 0, JSON.stringify({ type: "warning", message: "Search failed for query 'x': HTTP 500" }));
  const w = await scenario("real run with an injected warning", stream);
  check(w.els.alerts.innerHTML.includes('class="alert warn"') && w.els.alerts.innerHTML.includes("HTTP 500"), "warning shown as an amber alert");
  check(w.els.citedTxt.textContent.includes("1 warning"), `brief footer counts it ("${w.els.citedTxt.textContent}")`);
}

console.log(failures ? `\n${failures} check(s) FAILED` : "\nall checks passed");
process.exit(failures ? 1 : 0);
