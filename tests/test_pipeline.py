import json

from conftest import FakeLLM, fixture_results

from paperscout import europepmc, pipeline
from paperscout.llm import LLMError, parse_json


def run_all(llm, search_fn, tmp_path):
    events = list(pipeline.run("Do SGLT2 inhibitors reduce HF hospitalisation?", llm, search_fn, tmp_path))
    run_id = events[0]["run_id"]
    return events, tmp_path / run_id, json.loads((tmp_path / run_id / "run.json").read_text())


def by_type(events, t):
    return [e for e in events if e["type"] == t]


def test_happy_path_events_order_and_persistence(tmp_path):
    raw = fixture_results()
    events, run_dir, meta = run_all(FakeLLM(), lambda q: raw, tmp_path)
    assert events[-1]["type"] == "done" and not by_type(events, "warning") and not by_type(events, "error")
    stages = [(e["stage"], e["status"]) for e in by_type(events, "step")]
    assert stages == [(s, x) for s in ("plan", "retrieve", "rank", "synthesize") for x in ("start", "done")]
    papers = by_type(events, "results")[0]["papers"]
    assert len(papers) == 22  # 25 fixture records, 3 without abstracts, deduped across 3 identical queries
    assert by_type(events, "candidates")[0]["dropped_no_abstract"] == 3  # unique records, not per query
    assert all(len(p["matched_queries"]) == 3 for p in papers)
    scores = [p["score"] for p in papers]
    assert scores == sorted(scores, reverse=True)
    assert meta["status"] == "ok" and meta["counts"]["unique"] == 22
    summary = by_type(events, "summary")[0]
    top = [p["key"] for p in papers if p["score"] >= pipeline.MIN_SUMMARY_SCORE][:pipeline.TOP_K_SUMMARY]
    assert summary["cited_keys"] == top and len(top) > 1
    for f in ("plan.json", "candidates.json", "ranked.json", "effects.json", "summary.json", "run.json"):
        assert (run_dir / f).is_file()
    assert events[0]["models"].keys() == {"planner", "ranker", "writer"} and events[0]["question"]
    results = by_type(events, "results")[0]
    assert all(isinstance(p["outcomes"], list) for p in papers) and any(p["outcomes"] for p in papers)
    keys = {p["key"] for p in papers}
    assert results["effects"] and all(e["key"] in keys and e["lo"] <= e["est"] <= e["hi"] for e in results["effects"])
    by = {p["key"]: p for p in papers}
    assert all(e["snippet"] in by[e["key"]]["abstract"] for e in results["effects"])
    assert json.loads((run_dir / "effects.json").read_text()) == results["effects"]
    assert meta["counts"]["effects"] == len(results["effects"])


def test_planner_failure_falls_back_and_warns(tmp_path):
    seen = []
    events, _, meta = run_all(FakeLLM(fail={"planner": LLMError("boom")}), lambda q: seen.append(q) or fixture_results(),
                              tmp_path)
    assert seen == ["Do SGLT2 inhibitors reduce HF hospitalisation?"]
    assert any("planner failed" in w["message"] for w in by_type(events, "warning"))
    assert meta["status"] == "ok" and meta["warnings"]


def test_planner_garbage_queries_falls_back(tmp_path):
    events, _, _ = run_all(FakeLLM(plan={"queries": [None, "  "]}), lambda q: fixture_results(), tmp_path)
    assert by_type(events, "plan")[0]["plan"]["queries"] == ["Do SGLT2 inhibitors reduce HF hospitalisation?"]
    assert by_type(events, "warning")


def test_one_search_failing_is_reported_not_fatal(tmp_path):
    def search(q):
        if "dapagliflozin" in q:
            raise RuntimeError("HTTP 500")
        return fixture_results()
    events, _, meta = run_all(FakeLLM(), search, tmp_path)
    assert any("HTTP 500" in w["message"] for w in by_type(events, "warning"))
    assert events[-1]["type"] == "done" and meta["counts"]["per_query"]["(dapagliflozin OR empagliflozin) AND HFpEF"] is None


def test_all_searches_failing_is_an_error_and_still_persisted(tmp_path):
    def search(q):
        raise RuntimeError("down")
    events, run_dir, meta = run_all(FakeLLM(), search, tmp_path)
    assert events[-1]["type"] == "error" and "All searches failed" in events[-1]["message"]
    assert meta["status"] == "failed" and "down" in meta["error"]
    assert (run_dir / "plan.json").is_file()


def test_no_results_is_an_error(tmp_path):
    events, _, meta = run_all(FakeLLM(), lambda q: [], tmp_path)
    assert events[-1]["type"] == "error" and meta["status"] == "failed"


def test_ranker_batch_failure_leaves_papers_unscored_at_bottom(tmp_path):
    events, _, meta = run_all(FakeLLM(fail={"ranker": LLMError("bad json")}), lambda q: fixture_results(), tmp_path)
    assert len(by_type(events, "warning")) == 3  # 22 papers -> 3 batches
    papers = by_type(events, "results")[0]["papers"]
    assert all(p.get("score") is None for p in papers) and meta["counts"]["unscored"] == 22
    assert "None of the retrieved papers" in by_type(events, "summary")[0]["summary"]


def _first_title():
    return europepmc.normalize(fixture_results()[0])["title"][:40]


def test_ranker_persistently_missing_paper_warns_after_reask(tmp_path):
    llm = FakeLLM(ranker_drop={_first_title()})
    events, _, meta = run_all(llm, lambda q: fixture_results(), tmp_path)
    assert [w["message"] for w in by_type(events, "warning")] == [
        "Ranker skipped 1 of 10 papers in batch 1; shown unscored."]
    papers = by_type(events, "results")[0]["papers"]
    assert papers[-1].get("score") is None and meta["counts"]["unscored"] == 1
    assert llm.calls.count("ranker") == 4  # 3 batches + 1 re-ask for the missing paper


def test_ranker_reask_recovers_dropped_paper(tmp_path):
    llm = FakeLLM(ranker_drop={_first_title()}, drop_once=True)
    events, _, meta = run_all(llm, lambda q: fixture_results(), tmp_path)
    assert not by_type(events, "warning") and meta["counts"]["unscored"] == 0


def test_ranker_transient_failure_recovers_on_reask(tmp_path):
    llm = FakeLLM(fail={"ranker": LLMError("bad json")}, fail_times=1)
    events, _, meta = run_all(llm, lambda q: fixture_results(), tmp_path)
    assert not by_type(events, "warning") and meta["counts"]["unscored"] == 0


def test_every_llm_call_is_schema_constrained(tmp_path):
    llm = FakeLLM()
    run_all(llm, lambda q: fixture_results(), tmp_path)
    assert {r for r, _ in llm.schemas} == {"planner", "ranker", "writer"} and all(s for _, s in llm.schemas)
    sizes = sorted(s["properties"]["scores"]["minItems"] for r, s in llm.schemas if r == "ranker")
    assert sizes == [2, 10, 10] and all(s["properties"]["scores"]["maxItems"] == s["properties"]["scores"]["minItems"]
                                        for r, s in llm.schemas if r == "ranker")


def test_summary_with_invented_citation_warns(tmp_path):
    llm = FakeLLM(summary={"summary": "Effect shown [1][42].", "evidence_gaps": "", "confidence": "low"})
    events, _, _ = run_all(llm, lambda q: fixture_results(), tmp_path)
    assert any("[42]" in w["message"] for w in by_type(events, "warning"))
    assert llm.calls.count("writer") == 2


def _summary(text):
    return {"summary": text, "evidence_gaps": "", "confidence": "low"}


def test_summary_without_citations_is_reasked_then_warns(tmp_path):
    llm = FakeLLM(summary=_summary("SGLT2 inhibitors help."))
    events, _, _ = run_all(llm, lambda q: fixture_results(), tmp_path)
    assert llm.calls.count("writer") == 2
    assert [w["message"] for w in by_type(events, "warning")] == [
        "Summary has no [n] citations, so its claims are not traceable to papers"]


def test_summary_reask_recovers_citations(tmp_path):
    llm = FakeLLM(summary=[_summary("SGLT2 inhibitors help."), _summary("SGLT2 inhibitors help [1].")])
    events, _, _ = run_all(llm, lambda q: fixture_results(), tmp_path)
    assert not by_type(events, "warning") and by_type(events, "summary")[0]["summary"].endswith("[1].")


GOOD_PLAN = {"pico": {}, "queries": ["(HFpEF OR \"preserved ejection fraction\") AND SGLT2"], "rationale": ""}
BAD_PLAN = {"pico": {}, "queries": ["HFpEF OR \"preserved ejection fraction\" AND SGLT2"], "rationale": ""}


def test_planner_unparenthesised_query_is_reasked(tmp_path):
    llm = FakeLLM(plan=[BAD_PLAN, GOOD_PLAN])
    events, _, _ = run_all(llm, lambda q: fixture_results(), tmp_path)
    assert by_type(events, "plan")[0]["plan"]["queries"] == GOOD_PLAN["queries"]
    assert llm.calls.count("planner") == 2 and not by_type(events, "warning")


def test_planner_persistently_unparenthesised_query_warns(tmp_path):
    events, _, _ = run_all(FakeLLM(plan=BAD_PLAN), lambda q: fixture_results(), tmp_path)
    assert any("without parentheses" in w["message"] for w in by_type(events, "warning"))
    assert events[-1]["type"] == "done"


def test_mixes_and_or_on_invented_shapes():
    yes = ['"HFpEF" OR "x" AND "SGLT2"', "a AND (b OR c AND d)", "a AND b OR c"]
    no = ["(a OR b) AND (c OR d)", "a AND b AND c", '"heart AND or OR lung" AND x', "((a OR b) AND c) OR d",
          "a OR b OR c", "single", "a AND NOT b", '"crohn\'s disease" AND (infliximab OR adalimumab)']
    assert [pipeline.mixes_and_or(q) for q in yes] == [True] * len(yes)
    assert [pipeline.mixes_and_or(q) for q in no] == [False] * len(no)


def test_planner_backslashes_are_removed(tmp_path):
    plan = {"pico": {}, "queries": ["(microbiome) AND Parkinson\\'s disease", "\\\\"], "rationale": ""}
    events, _, _ = run_all(FakeLLM(plan=plan), lambda q: fixture_results(), tmp_path)
    assert by_type(events, "plan")[0]["plan"]["queries"] == ["(microbiome) AND Parkinson's disease"]


def test_unknown_study_type_is_normalised(tmp_path):
    llm = FakeLLM()
    llm.study_type = "review-article, Journal Article"
    events, _, _ = run_all(llm, lambda q: fixture_results(), tmp_path)
    assert {p["study_type"] for p in by_type(events, "results")[0]["papers"]} == {"other"}


def test_summary_failure_keeps_results(tmp_path):
    events, _, meta = run_all(FakeLLM(fail={"writer": LLMError("timeout")}), lambda q: fixture_results(), tmp_path)
    assert by_type(events, "results") and events[-1]["type"] == "done"
    assert any("Summary generation failed" in w["message"] for w in by_type(events, "warning"))


def test_client_disconnect_marks_run_aborted(tmp_path):
    gen = pipeline.run("Do SGLT2 inhibitors reduce HF hospitalisation?", FakeLLM(), lambda q: fixture_results(), tmp_path)
    run_id = next(gen)["run_id"]
    next(gen)
    gen.close()
    assert json.loads((tmp_path / run_id / "run.json").read_text())["status"] == "aborted"


def test_parse_json_handles_fences_and_think():
    assert parse_json('<think>hmm {"x":0}</think>```json\n{"a": 1}\n```') == {"a": 1}


def test_run_id_is_safe_and_timestamped():
    from datetime import datetime
    rid = pipeline.new_run_id("What about ../../etc? CAR-T", datetime(2026, 10, 18, 17, 5, 9))
    assert rid == "2026-10-18_170509-what-about-etc-car-t"
