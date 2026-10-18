import json
import re
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "europepmc_sglt2.json"


def fixture_results():
    return json.loads(FIXTURE.read_text())["resultList"]["result"]


class FakeLLM:
    """Canned replies per role. `fail` maps role -> exception (raised `fail_times` times, default always);
    `ranker_drop` is a set of title substrings the ranker omits (only on its first call if `drop_once`)."""

    def __init__(self, fail=None, plan=None, ranker_drop=(), summary=None, drop_once=False, fail_times=10 ** 6):
        self.fail, self.ranker_drop, self.calls, self.schemas = fail or {}, set(ranker_drop), [], []
        self.drop_once, self.fail_times = drop_once, fail_times
        self.plan = plan or {"pico": {"population": "adults with heart failure", "intervention": "SGLT2 inhibitors",
                                      "comparison": "placebo", "outcome": "hospitalisation"},
                             "queries": ["SGLT2 AND \"heart failure\"", "(dapagliflozin OR empagliflozin) AND HFpEF",
                                         "SGLT2 AND (randomized OR \"meta-analysis\")"], "rationale": "test"}
        self.summary = summary or {"summary": "SGLT2 inhibitors reduce HF hospitalisation [1][2].",
                                   "evidence_gaps": "Few data in elderly.", "confidence": "moderate"}
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0}

    def complete_json(self, role, system, user, max_tokens=1500, schema=None):
        self.calls.append(role)
        self.schemas.append((role, schema))
        if role in self.fail and self.calls.count(role) <= self.fail_times:
            raise self.fail[role]
        if role == "planner":
            return self._nth(self.plan, role)
        if role == "ranker":
            drop = self.ranker_drop if not self.drop_once or self.calls.count("ranker") == 1 else set()
            papers = re.findall(r"^\[(\d+)\] (.*)$", user, flags=re.M)
            return {"scores": [{"i": int(i), "score": (len(t) * 7) % 11, "study_type": self.study_type,
                                "reason": f"reason {i}"} for i, t in papers if not any(d in t for d in drop)]}
        return self._nth(self.summary, role)

    study_type = "RCT"

    def _nth(self, value, role):
        """A list means successive replies (last one repeats)."""
        if isinstance(value, list):
            return value[min(self.calls.count(role), len(value)) - 1]
        return value


@pytest.fixture
def raw():
    return fixture_results()
