import json
import re
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "europepmc_sglt2.json"


def fixture_results():
    return json.loads(FIXTURE.read_text())["resultList"]["result"]


class FakeLLM:
    """Canned replies per role; `fail` maps role -> exception to raise, `ranker_drop` omits paper numbers."""

    def __init__(self, fail=None, plan=None, ranker_drop=(), summary=None):
        self.fail, self.ranker_drop, self.calls = fail or {}, set(ranker_drop), []
        self.plan = plan or {"pico": {"population": "adults with heart failure", "intervention": "SGLT2 inhibitors",
                                      "comparison": "placebo", "outcome": "hospitalisation"},
                             "queries": ["SGLT2 AND \"heart failure\"", "(dapagliflozin OR empagliflozin) AND HFpEF",
                                         "SGLT2 AND (randomized OR \"meta-analysis\")"], "rationale": "test"}
        self.summary = summary or {"summary": "SGLT2 inhibitors reduce HF hospitalisation [1][2].",
                                   "evidence_gaps": "Few data in elderly.", "confidence": "moderate"}
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0}

    def complete_json(self, role, system, user, max_tokens=1500):
        self.calls.append(role)
        if role in self.fail:
            raise self.fail[role]
        if role == "planner":
            return self.plan
        if role == "ranker":
            nums = [int(n) for n in re.findall(r"^\[(\d+)\]", user, flags=re.M)]
            return {"scores": [{"i": i, "score": (i * 7) % 11, "study_type": "RCT", "reason": f"reason {i}"}
                               for i in nums if i not in self.ranker_drop]}
        return self.summary


@pytest.fixture
def raw():
    return fixture_results()
