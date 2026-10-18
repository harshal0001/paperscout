import json
from pathlib import Path

import pytest

from paperscout.insights import extract_effects, outcome_for, outcome_tags


@pytest.mark.parametrize("text,expected", [
    ("a 26% reduction in heart failure hospitalization (HR = 0.74, 95% CI: 0.68-0.81).", ("HR", 0.74, 0.68, 0.81)),
    ("risk of death (RR: 0.80, 95% CI 0.69-0.93).", ("RR", 0.80, 0.69, 0.93)),
    ("OS (HR = 0.84, 95%CI 0.76-0.92, p=0.003)", ("HR", 0.84, 0.76, 0.92)),
    ("odds ratio 1.35 (95% confidence interval 1.10 to 1.66)", ("OR", 1.35, 1.10, 1.66)),
    ("aHR 0.62; 95% CI, 0.48–0.80", ("HR", 0.62, 0.48, 0.80)),
    ("Hazard ratio of 0.9 [0.8, 1.01]", ("HR", 0.9, 0.8, 1.01)),
    ("OR=0.74 (0.65-0.84)", ("OR", 0.74, 0.65, 0.84)),
])
def test_extracts_common_shapes(text, expected):
    e = extract_effects(text)
    assert len(e) == 1 and (e[0]["measure"], e[0]["est"], e[0]["lo"], e[0]["hi"]) == expected


@pytest.mark.parametrize("text", [
    "patients aged 18 or 65 (40-80) were enrolled",   # English "or" is not an odds ratio
    "HR 0.74 (95% CI 0.80-0.90)",                     # CI does not bracket the estimate
    "OR 0.74 (95% CI 0.74-0.74)",                     # degenerate CI
    "heart rate (HR) was 72 bpm",                     # no CI at all
    "",
])
def test_rejects_non_effects(text):
    assert extract_effects(text) == []


def test_snippet_is_verbatim_and_outcome_is_nearest_keyword():
    a = ("Background text. SGLT2i reduced all-cause mortality (HR = 0.86, 95% CI: 0.79-0.92; p < 0.001) and "
         "heart failure hospitalization (HR = 0.74, 95% CI: 0.68-0.81). Conclusion here.")
    e = extract_effects(a)
    assert [x["outcome"] for x in e] == ["Mortality / survival", "Hospitalisation"]
    assert all(x["snippet"] in a and x["snippet"].startswith("SGLT2i") for x in e)


@pytest.mark.parametrize("context,expected", [
    ("reduced cardiovascular death ", "CV death"),           # longer phrase must beat its own "death"
    ("lower all-cause mortality and fewer admissions ", "Hospitalisation"),
    ("progression-free survival ", "Mortality / survival"),  # nearest keyword wins
])
def test_outcome_nearest_keyword(context, expected):
    assert outcome_for(context) == expected


def test_outcome_fallback_and_tags():
    assert outcome_for("the primary measure was") == "Other"
    assert outcome_tags("Fewer adverse events and lower eGFR decline") == ["Progression", "Safety", "Kidney"]


def test_real_fixture_snippets_are_findable():
    raw = json.loads((Path(__file__).parent / "fixtures" / "europepmc_sglt2.json").read_text())["resultList"]["result"]
    from paperscout.europepmc import normalize
    effects = [(p, e) for p in map(normalize, raw) for e in extract_effects(p["abstract"])]
    assert effects, "fixture should contain at least one reported effect size"
    assert all(e["snippet"] in p["abstract"] and e["lo"] <= e["est"] <= e["hi"] for p, e in effects)
