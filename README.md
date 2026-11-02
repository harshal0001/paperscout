# PaperScout

Research paper discovery for healthcare and life sciences. You ask a research question, and an agent:

1. **Plans** the search: it extracts PICO (Population, Intervention, Comparison, Outcome) and writes 3–4 Boolean queries, each from a different angle (NVIDIA Nemotron 3 Super).
2. **Retrieves** candidates from [Europe PMC](https://europepmc.org) (PubMed + preprints), running the queries in parallel and removing duplicates by PubMed ID or DOI.
3. **Screens and ranks** every abstract 0–10 for relevance, with a one-line reason and a study-design label (Nemotron 3.5 Lightning, in batches of 10).
4. **Synthesizes** a short evidence summary over the top papers. Every claim is cited `[n]`, each citation links to its paper card, and citations that point to papers it was never given are flagged.

The UI streams the agent's work live:
- **Agent trace:** each step, its model and log lines, with a timer and token and cost counters.
- **Evidence brief:** the summary with clickable citations.
- **Insight canvas** with three diagrams:
  - an evidence funnel, from searches to the papers that grounded the brief;
  - a forest plot of effect sizes (HR/OR/RR with 95% CI) extracted word for word from abstracts;
  - an evidence gap map of outcomes × study designs.
- **Evidence map and pyramid** by study design.
- **Ranked paper cards**, each with a reason.

You can filter by score, open access, preprints, study design or any diagram selection, and export to BibTeX or CSV. Open `/?q=<question>` to start a search straight from a link.

Built for the Nebius Build Week hackathon (Healthcare / Life Sciences track).

## Requirements

- **Python 3.11 or newer.** Check with `python3 --version`.
- **A Nebius Token Factory API key.** Sign in at [tokenfactory.nebius.com](https://tokenfactory.nebius.com), create a key, and make sure the account has credit. Europe PMC needs no key.
- **Node.js** (optional), only for the UI check in step 7.

## Getting started

**1. Clone the repo**

```bash
git clone https://github.com/harshal0001/paperscout.git
cd paperscout
```

**2. Create a virtual environment**

```bash
python3 -m venv .venv
```

If `python3` is older than 3.11, name a newer one, for example `python3.12 -m venv .venv`. With [uv](https://docs.astral.sh/uv/), `uv venv` works too.

**3. Install the dependencies**

```bash
.venv/bin/pip install -r requirements.txt
```

**4. Add your API key**

```bash
echo 'NEBIUS=<your Nebius Token Factory API key>' > .env
```

`.env` is gitignored, so the key is never committed. It starts with a dot, so Finder hides it; open it with `open -e .env` or press Cmd+Shift+. in Finder.

**5. Start the server**

```bash
.venv/bin/uvicorn paperscout.server:app --port 8000
```

**6. Open the app**

Go to [http://localhost:8000](http://localhost:8000), type a research question or click an example, and press Search. A search typically takes 10–30 seconds and costs well under $0.01. Each run is saved to `runs/<timestamp>-<slug>/`.

To stop the server, press Ctrl+C in its terminal.

**7. Run the checks (optional)**

```bash
.venv/bin/python -m pytest -q                 # offline: mock LLM + recorded Europe PMC response, no key needed
node scripts/check_ui_live.mjs                # UI: replays a captured real event stream through the page's JS (no browser)
.venv/bin/python scripts/smoke_examples.py    # live: sends every home-page example question to the running server (real tokens, <$0.05)
```

### Configuration

Optional environment variables, set in `.env` or the shell:

| Variable | Default |
|---|---|
| `PLANNER_MODEL` | `nvidia/nemotron-3-super-120b-a12b` |
| `RANKER_MODEL` | `nvidia/Nemotron-3_5-Lightning` |
| `WRITER_MODEL` | `nvidia/nemotron-3-super-120b-a12b` |
| `NEBIUS_BASE_URL` | `https://api.tokenfactory.nebius.com/v1/` |
| `RUNS_DIR` | `runs/` |

### Troubleshooting

- **The search fails with "NEBIUS … is not set":** `.env` is missing or isn't in the project folder. Repeat step 4, then restart the server.
- **`Address already in use`:** a server is already running on port 8000. Stop it, or use another port with `--port 8001`.
- **Europe PMC returns 503:** this is a temporary outage on their side; it is retried automatically. Try again in a minute if it persists.

## Cost

One question costs roughly 4 planner/writer calls and about 10 ranker calls. Prices per 1M tokens (input / output), checked 2026-10-18: Nemotron 3 Super $0.30 / $0.90, Nemotron 3.5 Lightning $0.06 / $0.24. In the measured run that is well under $0.01 per question; see `doc/engineering-log.md`.

## Layout

- `paperscout/europepmc.py`: search plus record normalisation
- `paperscout/llm.py`: Token Factory client (OpenAI-compatible), JSON-only replies
- `paperscout/pipeline.py`: the four agent stages as an event generator; each run is saved to `runs/<timestamp>-<slug>/`
- `paperscout/insights.py`: deterministic effect-size and outcome extraction from abstracts (feeds the forest plot and gap map)
- `paperscout/server.py`: FastAPI app with a Server-Sent Events stream and export
- `paperscout/static/index.html`: the single-page UI (all colours live in its `:root` theme block)
- `mockups/`: the approved design concept, frozen. The live page above is now the source of truth.
- `scripts/`: the live smoke test, the UI replay check, and the concept build/check
- `doc/`: project brief, engineering log, backlog
