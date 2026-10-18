# PaperScout

Research paper discovery for healthcare and life sciences. You ask a research question, and an agent:

1. **Plans** the search: it extracts PICO (Population, Intervention, Comparison, Outcome) and writes 3–4 Boolean queries, each from a different angle (NVIDIA Nemotron 3 Super).
2. **Retrieves** candidates from [Europe PMC](https://europepmc.org) (PubMed + preprints), running the queries in parallel and removing duplicates by PubMed ID or DOI.
3. **Screens and ranks** every abstract 0–10 for relevance, with a one-line reason and a study-design label (Nemotron 3.5 Lightning, in batches of 10).
4. **Synthesizes** a short evidence summary over the top papers. Every claim is cited `[n]`, each citation links to its paper card, and citations that point to papers it was never given are flagged.

The UI streams each step live. You can filter by score, open access or preprint status, and export to BibTeX or CSV.

Built for the Nebius Build Week hackathon (Healthcare / Life Sciences track).

## Run

```bash
uv venv && uv pip install -r requirements.txt
echo 'NEBIUS=<your Nebius Token Factory API key>' > .env
.venv/bin/uvicorn paperscout.server:app --port 8000
# open http://localhost:8000
```

Optional env overrides: `PLANNER_MODEL`, `RANKER_MODEL`, `WRITER_MODEL`, `NEBIUS_BASE_URL`, `RUNS_DIR`.

## Test

```bash
.venv/bin/python -m pytest -q   # offline: mock LLM + recorded Europe PMC response
.venv/bin/python scripts/smoke_examples.py   # live: sends every home-page example question to a running server (real tokens, <$0.05)
```

## Cost

One question costs roughly 4 planner/writer calls and about 10 ranker calls. Prices per 1M tokens (input / output), checked 2026-10-18: Nemotron 3 Super $0.30 / $0.90, Nemotron 3.5 Lightning $0.06 / $0.24. In the measured run that is well under $0.01 per question; see `doc/engineering-log.md`.

## Layout

- `paperscout/europepmc.py`: search plus record normalisation
- `paperscout/llm.py`: Token Factory client (OpenAI-compatible), JSON-only replies
- `paperscout/pipeline.py`: the four agent stages as an event generator; each run is saved to `runs/<timestamp>-<slug>/`
- `paperscout/server.py`: FastAPI app with a Server-Sent Events stream and export
- `paperscout/static/index.html`: the single-page UI
- `doc/`: project brief, engineering log, backlog
