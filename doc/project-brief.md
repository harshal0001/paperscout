# Project brief

**Source:** "Hackathon Master Deck.pdf", page "Healthcare / Life Sciences: Research Paper Discovery" (challenge owner
Arseniy Solokov, Nebius). Verbatim challenge text:

> Build a research paper discovery tool for healthcare and life sciences. Help users find papers relevant to a research question.

Judging (deck): 50% technical execution, 30% creativity and wow factor, 20% how well it addresses the challenge.
Deliverables (deck): 2-minute demo video and public GitHub repo, submitted by 18:30 on 2026-10-18. Team of 2–4.
Side prizes relevant here: Best use of Nemotron, Best use of Devin.

User constraint: MVP built in about 1 hour (started 16:38).

## What we build

A web app: the user enters a research question and gets a ranked, explained, exportable list of papers, plus a cited
evidence summary. The agent's work is visible step by step.

## Constraints

- LLM: Nebius Token Factory (OpenAI-compatible), NVIDIA Nemotron models, each under $1 per 1M tokens.
- Literature source: Europe PMC REST (free, no key; covers PubMed and preprints).
- Stack: Python, FastAPI, a single static HTML page, Server-Sent Events (chosen by the user over Streamlit).
- Every run is persisted under `runs/`.

## Non-goals (MVP)

Full-text retrieval, user accounts, saved collections, embeddings/vector index, multiple literature sources. See `backlog.md`.
