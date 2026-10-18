# Engineering log

## 2026-10-18: MVP build

**Decisions**
- Literature source: Europe PMC rather than raw PubMed E-utilities. One JSON call returns abstract, citation count,
  open-access flag, publication types and DOI/PubMed ID; no key needed. The query is restricted to `(SRC:MED OR SRC:PPR)`:
  unrestricted results put sparse `SRC:PMC` records at the top (no PubMed ID, no year, no abstract).
- Models: checked live against `tokenfactory.nebius.com/api/public/models_info`. Planner and writer use
  `nvidia/nemotron-3-super-120b-a12b` ($0.30 / $0.90 per 1M tokens); the ranker uses `nvidia/Nemotron-3_5-Lightning` ($0.06 / $0.24).
- LLM relevance screening (with a reason per paper) instead of embeddings: it is explainable, which matters for the
  demo and for trust, and costs fractions of a cent.
- The summary uses only papers scored at least 6, at most 8 of them. The server sends the exact keys of the cited papers
  (`cited_keys`), so the UI never re-derives the selection rule itself (that would be a second copy to keep in sync).

**What failed and why**
- Nemotron with default settings: Lightning spent all 400 tokens on a visible "thinking process" and returned no JSON.
  Super returned JSON but generated reasoning tokens. Fix: `extra_body={"chat_template_kwargs": {"enable_thinking": False}}`.
  Measured: Lightning 0.3 s / 31 tokens, Super 0.6 s / 22 tokens on a small JSON task.
- Europe PMC returned `HTTP 503 {"errMsg":"Search service is temporarily unavailable"}` on one call; the identical
  call seconds later returned 200. Hence a bounded retry on 503 only (2 retries); other statuses raise with the body.
- `python-dotenv`'s `load_dotenv()` without a path crashes when run from stdin (`find_dotenv` frame assertion). The
  server passes an explicit path.

**Tests:** 26 offline tests (mock LLM + a recorded Europe PMC response) covering the happy path and every failure
path: planner failure or garbage output → fallback query plus a warning; one query failing → warning, run continues;
all failing → error event and a persisted `run.json` with status `failed`; ranker batch failure or partial reply →
papers left unscored, sorted to the bottom, with a warning; an invented citation number in the summary → warning;
summary failure → results kept; client disconnect → run marked `aborted`.
