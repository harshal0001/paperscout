"""Agent pipeline: plan -> retrieve -> rank -> synthesize. A generator of UI events; every run is persisted under runs/."""
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from . import europepmc
from .llm import MODELS

MAX_QUERIES = 4
PAGE_SIZE = 25
RANK_BATCH = 10
TOP_K_SUMMARY = 8
MIN_SUMMARY_SCORE = 6

PLANNER_SYSTEM = """You are a biomedical information specialist. Turn a research question into a search plan for Europe PMC (PubMed + preprints).
Return JSON only:
{"pico": {"population": "", "intervention": "", "comparison": "", "outcome": ""}, "queries": ["..."], "rationale": "one sentence"}
Rules:
- 3 or 4 queries, each a different angle: (1) core concepts joined with AND; (2) synonyms / MeSH-style variants grouped with OR; (3) the core concepts AND (randomized OR "meta-analysis" OR "systematic review"); (4) optionally a broader query.
- Europe PMC syntax only: AND, OR, NOT, parentheses, "quoted phrases". No field tags.
- Keep each query under 200 characters. Use an empty string for PICO fields that do not apply."""

RANKER_SYSTEM = """You screen biomedical abstracts for relevance to a research question.
Score each paper 0-10: 10 = directly answers the question (same population, intervention and outcome); 7-9 = highly relevant, one element differs; 4-6 = related background; 0-3 = off-topic.
Return JSON only, one entry per paper:
{"scores": [{"i": <paper number>, "score": <integer 0-10>, "study_type": "<RCT|meta-analysis|systematic review|cohort|case-control|cross-sectional|case report|narrative review|preclinical|guideline|other>", "reason": "<max 25 words, specific to this paper>"}]}"""

WRITER_SYSTEM = """You write evidence summaries for researchers. Use ONLY the numbered papers provided; never add outside facts.
Return JSON only:
{"summary": "3-6 sentences answering the question; cite every claim like [1] or [2][5]", "evidence_gaps": "1-2 sentences on what these papers do not cover", "confidence": "high|moderate|low"}
If the papers do not answer the question, say so plainly."""


def new_run_id(question, now=None):
    slug = re.sub(r"[^a-z0-9]+", "-", question.lower()).strip("-")[:40].rstrip("-") or "query"
    return f"{(now or datetime.now()):%Y-%m-%d_%H%M%S}-{slug}"


def make_plan(question, llm):
    plan = llm.complete_json("planner", PLANNER_SYSTEM, f"Research question: {question}", max_tokens=800)
    queries = [q.strip() for q in plan.get("queries", []) if isinstance(q, str) and q.strip()][:MAX_QUERIES]
    if not queries:
        raise ValueError(f"planner returned no usable queries: {plan!r:.200}")
    pico = plan.get("pico") if isinstance(plan.get("pico"), dict) else {}
    return {"pico": {k: str(pico.get(k) or "") for k in ("population", "intervention", "comparison", "outcome")},
            "queries": queries, "rationale": str(plan.get("rationale") or "")}


def retrieve(queries, search_fn):
    """Run all queries in parallel; merge by stable key. Returns (papers, per-query counts, warnings, dropped)."""
    with ThreadPoolExecutor(max_workers=len(queries)) as pool:
        futures = [pool.submit(search_fn, q) for q in queries]
    merged, counts, warnings, dropped = {}, {}, [], set()
    for q, f in zip(queries, futures):
        try:
            raw = f.result()
        except Exception as e:  # one dead query must not sink the run, but it must be visible
            warnings.append(f"Search failed for query {q!r}: {e}")
            counts[q] = None
            continue
        counts[q] = len(raw)
        for r in raw:
            p = europepmc.normalize(r)
            if not p["abstract"] or not p["title"]:
                dropped.add(p["key"])
                continue
            merged.setdefault(p["key"], {**p, "matched_queries": []})["matched_queries"].append(q)
    if all(c is None for c in counts.values()):
        raise RuntimeError("All searches failed: " + " | ".join(warnings))
    return list(merged.values()), counts, warnings, len(dropped)


def _rank_batch(question, plan, batch, llm):
    lines = [f"[{i}] {p['title']} ({p['year'] or 'n.d.'}; {', '.join(p['pub_types'][:3])})\n{p['abstract'][:1500]}"
             for i, p in enumerate(batch, 1)]
    pico = "; ".join(f"{k}: {v}" for k, v in plan["pico"].items() if v)
    user = f"Research question: {question}\nPICO: {pico or 'n/a'}\n\nPapers:\n\n" + "\n\n".join(lines)
    out = llm.complete_json("ranker", RANKER_SYSTEM, user, max_tokens=150 * len(batch) + 200)
    scored = 0
    for s in out.get("scores", []):
        try:
            i, score = int(s["i"]), max(0, min(10, int(s["score"])))
        except (KeyError, TypeError, ValueError):
            continue
        if 1 <= i <= len(batch) and batch[i - 1].get("score") is None:
            batch[i - 1].update(score=score, reason=str(s.get("reason", ""))[:300],
                                study_type=str(s.get("study_type", "other")))
            scored += 1
    return scored


def sort_papers(papers):
    return sorted(papers, key=lambda p: (p.get("score") is None, -(p.get("score") or 0), -p["cited_by"]))


def synthesize(question, ranked, llm):
    top = [p for p in ranked if (p.get("score") or 0) >= MIN_SUMMARY_SCORE][:TOP_K_SUMMARY]
    if not top:
        return {"summary": "None of the retrieved papers scored as directly relevant. Try rephrasing the question "
                           "or broadening the population or outcome.", "evidence_gaps": "", "confidence": "low",
                "cited_keys": []}, []
    body = "\n\n".join(f"[{n}] {p['title']} ({p['journal']}, {p['year']}; {p.get('study_type', '')})\n{p['abstract'][:1200]}"
                       for n, p in enumerate(top, 1))
    out = llm.complete_json("writer", WRITER_SYSTEM, f"Research question: {question}\n\nPapers:\n\n{body}", max_tokens=900)
    summary = {"summary": str(out.get("summary", "")), "evidence_gaps": str(out.get("evidence_gaps", "")),
               "confidence": str(out.get("confidence", "low")), "cited_keys": [p["key"] for p in top]}
    warnings = []
    bad = sorted({int(n) for n in re.findall(r"\[(\d+)\]", summary["summary"]) if not 1 <= int(n) <= len(top)})
    if bad:
        warnings.append(f"Summary cited papers that were not provided: {bad}")
    if not summary["summary"]:
        warnings.append("Summary model returned an empty summary")
    return summary, warnings


def run(question, llm, search_fn=None, runs_dir="runs", run_id=None):
    """Yield event dicts for the UI. Always leaves runs/<run_id>/run.json, even on failure or client disconnect."""
    search_fn = search_fn or (lambda q: europepmc.search(q, page_size=PAGE_SIZE))
    run_id = run_id or new_run_id(question)
    run_dir = Path(runs_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    meta = {"run_id": run_id, "question": question, "started": datetime.now().isoformat(timespec="seconds"),
            "models": MODELS, "status": "running", "warnings": [], "counts": {}}

    def save(name, obj):
        (run_dir / name).write_text(json.dumps(obj, indent=2, ensure_ascii=False))

    def warn(msg):
        meta["warnings"].append(msg)
        return {"type": "warning", "message": msg}

    try:
        yield {"type": "run", "run_id": run_id}
        yield {"type": "step", "stage": "plan", "status": "start"}
        try:
            plan = make_plan(question, llm)
        except Exception as e:
            plan = {"pico": dict.fromkeys(("population", "intervention", "comparison", "outcome"), ""),
                    "queries": [question], "rationale": "Fallback: planner failed, searching the question verbatim."}
            yield warn(f"Query planner failed ({e}); searching the question as typed.")
        save("plan.json", plan)
        yield {"type": "plan", "plan": plan}
        yield {"type": "step", "stage": "plan", "status": "done"}

        yield {"type": "step", "stage": "retrieve", "status": "start"}
        papers, counts, warnings, dropped = retrieve(plan["queries"], search_fn)
        for w in warnings:
            yield warn(w)
        meta["counts"].update(per_query=counts, unique=len(papers), dropped_no_abstract=dropped)
        save("candidates.json", papers)
        yield {"type": "candidates", "count": len(papers), "per_query": counts, "dropped_no_abstract": dropped}
        yield {"type": "step", "stage": "retrieve", "status": "done"}
        if not papers:
            raise RuntimeError("No papers with abstracts found. Try a broader question.")

        yield {"type": "step", "stage": "rank", "status": "start"}
        batches = [papers[i:i + RANK_BATCH] for i in range(0, len(papers), RANK_BATCH)]
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(_rank_batch, question, plan, b, llm) for b in batches]
            for n, (b, f) in enumerate(zip(batches, futures), 1):
                try:
                    if f.result() < len(b):
                        yield warn(f"Ranker skipped {len(b) - f.result()} of {len(b)} papers in batch {n}; shown unscored.")
                except Exception as e:
                    yield warn(f"Ranking batch {n} failed ({e}); its {len(b)} papers are shown unscored.")
                yield {"type": "rank_progress", "done": n, "total": len(batches)}
        ranked = sort_papers(papers)
        meta["counts"]["unscored"] = sum(p.get("score") is None for p in ranked)
        save("ranked.json", ranked)
        yield {"type": "results", "papers": ranked}
        yield {"type": "step", "stage": "rank", "status": "done"}

        yield {"type": "step", "stage": "synthesize", "status": "start"}
        try:
            summary, warnings = synthesize(question, ranked, llm)
            for w in warnings:
                yield warn(w)
        except Exception as e:
            summary = {"summary": "", "evidence_gaps": "", "confidence": "low", "cited_keys": []}
            yield warn(f"Summary generation failed ({e}); ranked papers are still valid.")
        save("summary.json", summary)
        yield {"type": "summary", **summary}
        yield {"type": "step", "stage": "synthesize", "status": "done"}
        meta["status"] = "ok"
        yield {"type": "done", "run_id": run_id, "usage": getattr(llm, "usage", None)}
    except Exception as e:
        meta.update(status="failed", error=str(e))
        yield {"type": "error", "message": str(e)}
    finally:
        if meta["status"] == "running":
            meta["status"] = "aborted"
        meta.update(finished=datetime.now().isoformat(timespec="seconds"), usage=getattr(llm, "usage", None))
        save("run.json", meta)
