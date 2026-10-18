"""Build the standalone UI concept page from a saved run, so the sample shows real model output, never retyped data.

Usage: .venv/bin/python scripts/build_ui_sample.py [runs/<run_id>]   (default: newest successful run)
Writes mockups/<YYYY-MM-DD_HHMM>-ui-concept.html. Self-contained: open the file directly, no server needed.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIELDS = ("key", "id", "title", "authors", "journal", "year", "cited_by", "open_access", "preprint", "doi", "pmid",
          "url", "score", "reason", "study_type", "matched_queries", "abstract")


def newest_ok_run():
    for d in sorted((ROOT / "runs").iterdir(), reverse=True):
        meta = d / "run.json"
        if meta.is_file() and json.loads(meta.read_text()).get("status") == "ok" and (d / "summary.json").is_file():
            return d
    sys.exit("no successful run under runs/")


def main():
    run_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else newest_ok_run()
    meta = json.loads((run_dir / "run.json").read_text())
    data = {
        "run_id": meta["run_id"], "question": meta["question"], "counts": meta["counts"], "usage": meta.get("usage"),
        "warnings": meta["warnings"], "plan": json.loads((run_dir / "plan.json").read_text()),
        "summary": json.loads((run_dir / "summary.json").read_text()),
        "papers": [{k: p.get(k) for k in FIELDS} for p in json.loads((run_dir / "ranked.json").read_text())],
    }
    template = (ROOT / "mockups" / "ui-concept.template.html").read_text()
    if template.count('"__RUN_DATA__"') != 1:
        sys.exit("template must contain the placeholder exactly once")
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")  # never close the <script> early
    out = ROOT / "mockups" / f"{datetime.now():%Y-%m-%d_%H%M}-ui-concept.html"
    out.write_text(template.replace('"__RUN_DATA__"', payload))
    print(f"{out.relative_to(ROOT)}  ({len(data['papers'])} papers from {meta['run_id']}, {out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
