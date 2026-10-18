import httpx
import pytest

from paperscout import europepmc


def test_normalize_real_fixture(raw):
    papers = [europepmc.normalize(r) for r in raw]
    assert len(papers) == 25
    assert len({p["key"] for p in papers}) == 25
    with_abs = [p for p in papers if p["abstract"]]
    assert len(with_abs) == 22
    for p in papers:
        assert "<" not in p["title"] and p["url"].startswith("https://europepmc.org/article/")
        assert p["year"] is None or 1900 < p["year"] < 2100


@pytest.mark.parametrize("raw,expected", [
    ("<h4>Background</h4>SGLT2&amp;HF  <i>x</i>", "Background SGLT2&HF x"),
    ("&lt;i&gt;In vivo&lt;/i&gt; base editing", "In vivo base editing"),
    ("Base editing of β<sup>0</sup>-thalassemia", "Base editing of β0-thalassemia"),
    ("β&lt;sup&gt;0&lt;/sup&gt;-thalassemia", "β0-thalassemia"),
    ("HR 0.7 (p < 0.05 and x > 3)", "HR 0.7 (p < 0.05 and x > 3)"),
    ("p &lt; 0.001 vs &gt;65 years", "p < 0.001 vs >65 years"),
    ("<p>One.</p><p>Two.</p>", "One. Two."),
    ('<span class="x">CO<sub>2</sub></span>', "CO2"),
    ("&amp;lt;b&amp;gt;double&amp;lt;/b&amp;gt;", "double"),
    (None, ""),
])
def test_clean_strips_tags_and_entities(raw, expected):
    assert europepmc.clean(raw) == expected


def _client(responses):
    it = iter(responses)
    return httpx.Client(transport=httpx.MockTransport(lambda req: next(it)))


def test_search_retries_503_then_succeeds():
    ok = httpx.Response(200, json={"resultList": {"result": [{"id": "1"}]}})
    busy = httpx.Response(503, json={"errMsg": "temporarily unavailable"})
    assert europepmc.search("x", client=_client([busy, ok]), backoff=0) == [{"id": "1"}]


def test_search_gives_up_after_retries_and_reports_body():
    busy = [httpx.Response(503, text="Search service is temporarily unavailable")] * 3
    with pytest.raises(europepmc.SearchError, match="503.*temporarily"):
        europepmc.search("x", client=_client(busy), retries=2, backoff=0)


def test_search_does_not_retry_400():
    with pytest.raises(europepmc.SearchError, match="400.*bad query"):
        europepmc.search("x", client=_client([httpx.Response(400, text="bad query")]), backoff=0)


def test_search_rejects_error_body_with_200():
    with pytest.raises(europepmc.SearchError, match="unexpected body"):
        europepmc.search("x", client=_client([httpx.Response(200, json={"errCode": 1})]), backoff=0)
