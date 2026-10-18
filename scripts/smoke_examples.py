"""Backend smoke test: send every example question from the home page to a running server and check each run.

Usage: .venv/bin/python scripts/smoke_examples.py [base_url]   (default http://localhost:8000; costs real tokens)
"""
import json
import re
import sys
import time
from pathlib import Path

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
ROOT = Path(__file__).resolve().parent.parent
html = (ROOT / "paperscout" / "static" / "index.html").read_text()
EXAMPLES = re.findall(r'^\s*"([^"]+\?)",?$', html.split("const EXAMPLES = [", 1)[1].split("];", 1)[0], flags=re.M)


def check(q, client):
    t = time.time()
    events = []
    with client.stream("GET", f"{BASE}/api/search", params={"q": q}, timeout=240) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    secs = time.time() - t
    by = lambda typ: [e for e in events if e["type"] == typ]
    problems = [f"warning: {w['message']}" for w in by("warning")] + [f"error: {e['message']}" for e in by("error")]
    papers = by("results")[0]["papers"] if by("results") else []
    summary = by("summary")[0] if by("summary") else {}
    cites = re.findall(r"\[(\d+)\]", summary.get("summary", ""))
    run_id = events[0].get("run_id") if events else None
    steps_done = [e["stage"] for e in by("step") if e["status"] == "done"]
    if events[-1]["type"] != "done":
        problems.append(f"last event is {events[-1]['type']!r}, not 'done'")
    if steps_done != ["plan", "retrieve", "rank", "synthesize"]:
        problems.append(f"steps completed: {steps_done}")
    if not papers:
        problems.append("no papers")
    unscored = sum(p.get("score") is None for p in papers)
    if unscored:
        problems.append(f"{unscored} unscored papers")
    if not cites:
        problems.append("summary has no [n] citations")
    if any(not 1 <= int(n) <= len(summary.get("cited_keys", [])) for n in cites):
        problems.append("summary cites a paper outside cited_keys")
    if any(re.search(r"</?[a-zA-Z]+[^<>]*>", p["title"]) for p in papers):
        problems.append("HTML tags left in titles")
    if run_id:
        meta = json.loads((ROOT / "runs" / run_id / "run.json").read_text())
        if meta["status"] != "ok":
            problems.append(f"run.json status {meta['status']}")
        for fmt, marker in (("bib", "@article{"), ("csv", "score,")):
            r = client.get(f"{BASE}/api/runs/{run_id}/export", params={"fmt": fmt})
            if r.status_code != 200 or marker not in r.text:
                problems.append(f"export {fmt}: HTTP {r.status_code}")
    print(f"{'PASS' if not problems else 'FAIL'}  {secs:4.1f}s  papers={len(papers):3d}  "
          f"score>=7={sum((p.get('score') or 0) >= 7 for p in papers):2d}  cites={len(cites):2d}  "
          f"confidence={summary.get('confidence')}  | {q}")
    if papers:
        p = papers[0]
        print(f"      top: [{p.get('score')}] {p['title'][:100]}")
    for prob in problems:
        print(f"      - {prob}")
    return not problems


if __name__ == "__main__":
    if not EXAMPLES:
        sys.exit("could not read EXAMPLES from index.html")
    print(f"{len(EXAMPLES)} example questions from index.html, server {BASE}\n")
    with httpx.Client() as client:
        results = [check(q, client) for q in EXAMPLES]
    print(f"\n{sum(results)}/{len(results)} passed")
    sys.exit(0 if all(results) else 1)
