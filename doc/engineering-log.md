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

**First real end-to-end run (run `2026-10-18_164809-…`): 3 of 9 ranker batches failed, 30 of 81 papers unscored.**
Nemotron Lightning emitted malformed JSON (`}], {"i": 2, …`: it closed the array after the first item). Reproduced
on the saved candidates: 2 of the 3 batches failed deterministically at temperature 0, so the same-request retry could
not help. Tried `response_format: json_schema`: always valid JSON, but the model then *legally* closed the array after
1–2 items. Fix: `minItems = maxItems = batch size` in the schema → 9 of 9 batches complete (a keyed-object schema did
equally well; the array version kept the existing parser). On top of that, the class fix: any paper still unscored
after a batch is re-asked once in a smaller batch (a different prompt, so it can succeed where an identical retry
cannot). Planner and writer got schemas too, since the same failure class applies to every JSON call.

**Second and third real runs: reading the output, not just the status, found three more defects (all fixed):**
- The microbiome summary contained zero `[n]` citations. The check only caught out-of-range numbers, so a summary with
  no citations passed silently. Now the writer is re-asked once if there are no citations or invalid ones, and warns
  if that fails too.
- `study_type` was free text ("review", "Review", "review-article, Review, Journal Article"). Now it is an enum in the
  schema, and anything outside the enum is normalised to "other".
- A planner query mixed AND and OR without parentheses (`"HFpEF" OR "…" AND "SGLT2" OR …`), which silently changes what
  it searches for. Fixed with a prompt rule plus a `mixes_and_or` check that re-asks once, then warns. The model also
  emitted `Parkinson\'s` (a JSON-escaped apostrophe); backslashes are now removed from queries.
- Titles kept `<i>` and `<sup>` tags because `clean()` stripped tags *before* unescaping, so escaped tags survived.
  Unescaping first would also eat comparisons like `p < 0.05 … > 3`, so the tag pattern now requires a letter right
  after `<`, and strip/unescape repeats until stable. An invented double-escaped input caught a second bug in the first
  version of that fix (it ended on an unescape step).

Measured after the fixes (2 questions): 64–71 papers, 0 unscored, 0 warnings, 9–11 s, about 26k input + 3.5k output
tokens per question (almost all on Lightning), which is under $0.01.

**Live smoke test (`scripts/smoke_examples.py`, 16:59, final code):** all 4 home-page example questions (read from
`index.html` by the script, so the list cannot drift) passed: 61–94 papers, 0 unscored, 0 warnings, 2–7 citations,
both exports OK, 9–14 s each. The checker was proven by its failure path: against a server with no API key it
reported FAIL for every question and exited 1. The browser UI itself was not exercised (the user chose a
terminal-only check); the JavaScript rendering is unverified, see backlog.

**Tests:** 26 offline tests (mock LLM + a recorded Europe PMC response) covering the happy path and every failure
path: planner failure or garbage output → fallback query plus a warning; one query failing → warning, run continues;
all failing → error event and a persisted `run.json` with status `failed`; ranker batch failure or partial reply →
papers left unscored, sorted to the bottom, with a warning; an invented citation number in the summary → warning;
summary failure → results kept; client disconnect → run marked `aborted`. Now 45 tests, adding: schema on every LLM
call, ranker re-ask (recovers / still warns), summary citation re-ask (recovers / still warns), AND/OR re-ask,
`mixes_and_or` on 11 invented shapes, `clean()` on 10 invented markup shapes.
