# Backlog

Statuses: DEFERRED, UNVERIFIED, BLOCKED, WONTFIX, DONE (dated).

- DEFERRED: **Second literature source** (PubMed E-utilities or Semantic Scholar) as a fallback. Europe PMC is a single point of failure and returned a 503 during setup. Where: `paperscout/` as a new module plus `search_fn` fan-out in `pipeline.retrieve`. Trigger: Europe PMC outage during the demo, or wanting broader coverage.
- DEFERRED: **Embedding pre-filter** (Qwen3-Embedding-8B on Token Factory, $0.01 per 1M tokens) to rerank more than 100 candidates before LLM screening. Where: between retrieve and rank. Trigger: wanting more than 4×25 candidates.
- DEFERRED: **Follow-up questions / query refinement loop** (the agent sees weak scores and issues new queries). Where: `pipeline.run` after rank. Trigger: low-relevance results on niche questions.
- DEFERRED: **Full-text open-access snippets** (Europe PMC fullTextXML) for evidence quotes. Trigger: judges or users asking "where in the paper?".
- UNVERIFIED: **Ranker calibration.** Scores come from a small model on abstracts only, and have not been checked against expert relevance labels. Trigger: any claim about accuracy.
- UNVERIFIED: **Summary faithfulness.** Out-of-range citation numbers are caught automatically. Whether each cited claim is actually supported by its abstract has not been checked beyond the manual look in the engineering log.
- DEFERRED: **Rate limiting / concurrency guard** on `/api/search` for a public deployment. Trigger: hosting it publicly.
