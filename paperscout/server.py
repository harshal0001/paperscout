"""FastAPI app: static UI, Server-Sent Events search stream, BibTeX/CSV export of a saved run."""
import csv
import io
import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response, StreamingResponse

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

from . import pipeline  # noqa: E402  (after .env so model overrides apply)
from .llm import LLM  # noqa: E402

RUNS_DIR = Path(os.environ.get("RUNS_DIR", ROOT / "runs"))
STATIC = Path(__file__).parent / "static"
RUN_ID = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{6}-[a-z0-9-]+$")

app = FastAPI(title="PaperScout")
app.state.llm_factory = LLM
app.state.search_fn = None


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/search")
def search(q: str = Query(min_length=8, max_length=500)):
    def stream():
        try:
            llm = app.state.llm_factory()
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            return
        for event in pipeline.run(q.strip(), llm, app.state.search_fn, RUNS_DIR):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


def _load_ranked(run_id):
    path = RUNS_DIR / run_id / "ranked.json"
    if not RUN_ID.match(run_id) or not path.is_file():
        raise HTTPException(404, "run not found")
    return json.loads(path.read_text())


def to_bibtex(papers):
    out = []
    for p in papers:
        first = (p["authors"].split(",")[0].split() or ["anon"])[0]
        key = re.sub(r"[^A-Za-z0-9]", "", f"{first}{p['year'] or ''}{p['id']}")
        fields = {"title": p["title"], "author": p["authors"].replace(", ", " and "), "journal": p["journal"],
                  "year": p["year"], "doi": p["doi"], "pmid": p["pmid"], "url": p["url"]}
        body = ",\n".join(f"  {k} = {{{str(v).replace('{', '').replace('}', '')}}}" for k, v in fields.items() if v)
        out.append(f"@article{{{key},\n{body}\n}}")
    return "\n\n".join(out) + "\n"


def to_csv(papers):
    buf = io.StringIO()
    cols = ["score", "study_type", "title", "authors", "journal", "year", "cited_by", "open_access", "preprint",
            "doi", "pmid", "url", "reason"]
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    w.writerows(papers)
    return buf.getvalue()


@app.get("/api/runs/{run_id}/export")
def export(run_id: str, fmt: str = Query("bib", pattern="^(bib|csv)$"), min_score: int = 0):
    papers = [p for p in _load_ranked(run_id) if (p.get("score") or 0) >= min_score]
    if fmt == "bib":
        return Response(to_bibtex(papers), media_type="application/x-bibtex",
                        headers={"Content-Disposition": f'attachment; filename="{run_id}.bib"'})
    return Response(to_csv(papers), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{run_id}.csv"'})
