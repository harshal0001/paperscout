import json

import pytest
from conftest import FakeLLM, fixture_results
from fastapi.testclient import TestClient

from paperscout import server


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(server.app.state, "llm_factory", FakeLLM)
    monkeypatch.setattr(server.app.state, "search_fn", lambda q: fixture_results())
    return TestClient(server.app)


def sse(text):
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


def test_index(client):
    r = client.get("/")
    assert r.status_code == 200 and "PaperScout" in r.text


def test_search_stream_then_export(client):
    events = sse(client.get("/api/search", params={"q": "SGLT2 inhibitors in heart failure"}).text)
    assert events[-1]["type"] == "done"
    run_id = events[0]["run_id"]
    bib = client.get(f"/api/runs/{run_id}/export", params={"fmt": "bib"})
    assert bib.status_code == 200 and bib.text.count("@article{") == 22
    csv = client.get(f"/api/runs/{run_id}/export", params={"fmt": "csv", "min_score": 7})
    rows = csv.text.strip().splitlines()
    assert rows[0].startswith("score,") and all(int(r.split(",")[0]) >= 7 for r in rows[1:])


def test_missing_key_surfaces_as_error_event(client, monkeypatch):
    def broken():
        raise RuntimeError("env var NEBIUS (Token Factory API key) is not set")
    monkeypatch.setattr(server.app.state, "llm_factory", broken)
    events = sse(client.get("/api/search", params={"q": "SGLT2 inhibitors in heart failure"}).text)
    assert events == [{"type": "error", "message": "env var NEBIUS (Token Factory API key) is not set"}]


@pytest.mark.parametrize("rid", ["..%2F..%2Fetc", "nope", "2026-10-18_170509-missing"])
def test_export_rejects_unknown_or_unsafe_ids(client, rid):
    assert client.get(f"/api/runs/{rid}/export").status_code == 404


def test_short_query_rejected(client):
    assert client.get("/api/search", params={"q": "hi"}).status_code == 422
