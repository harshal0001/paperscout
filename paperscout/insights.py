"""Deterministic analysis over screened papers: effect sizes and outcome tags extracted from abstracts.

Used by the UI concept build (scripts/build_ui_sample.py); not yet wired into the live app.
Every extracted number keeps its source sentence verbatim, so it can be found with ctrl-F in the abstract.
"""
import re

_NUM = r"(\d+(?:\.\d+)?)"
# Abbreviations are case-sensitive on purpose: a case-insensitive "OR" matches the English word "or".
EFFECT = re.compile(
    r"\b(a?HRs?|a?ORs?|a?RRs?|IRR|(?i:hazard ratios?|odds ratios?|risk ratios?|relative risks?))\b"
    r"\s*(?:\((?:a?HR|a?OR|a?RR)\))?\s*[=:,]?\s*(?:of\s+|was\s+)?" + _NUM +
    r"\s*[;,(\[]?\s*(?:95\s*%\s*(?i:CI|confidence intervals?)(?:\s*\(CI\))?\s*[:=,]?\s*)?\(?\s*" + _NUM +
    r"\s*(?:-|–|—|to|,)\s*" + _NUM)

# The keyword ending closest before the number decides the outcome (see outcome_for).
OUTCOMES = {
    "Hospitalisation": r"hospitali[sz]|admission|readmission",
    "CV death": r"cardiovascular (?:death|mortality)|cv (?:death|mortality)",
    "Mortality / survival": r"mortality|death|survival|\bOS\b",
    "Progression": r"\bPFS\b|progression|worsening|decline",
    "Composite endpoint": r"\bMACE\b|composite|primary (?:end ?point|outcome)",
    "Safety": r"adverse|safety|toxicit|hypoglyc|ketoacidosis|infection",
    "Symptoms / QoL": r"quality of life|\bQoL\b|KCCQ|symptom",
    "Kidney": r"\beGFR\b|kidney|renal",
    "Response / efficacy": r"response|remission|efficacy|\bORR\b",
}
_OUT_RE = {k: re.compile(v, re.I) for k, v in OUTCOMES.items()}


def measure(label):
    w = label.lower().split()[0].rstrip("s")
    w = w[1:] if w in ("ahr", "aor", "arr") else w
    return {"hr": "HR", "hazard": "HR", "or": "OR", "odd": "OR", "rr": "RR", "risk": "RR", "relative": "RR",
            "irr": "RR"}[w]


def _sentence_start(text, pos):
    i = text.rfind(". ", 0, pos)
    return i + 2 if i >= 0 else 0


def outcome_for(context):
    """Category whose keyword ENDS closest before the number; on a tie the longer match wins, so
    "cardiovascular death" beats its own "death". 'Other' if none."""
    best, rank = "Other", (-1, 0)
    for name, rx in _OUT_RE.items():
        for m in rx.finditer(context):
            if (m.end(), m.end() - m.start()) > rank:
                best, rank = name, (m.end(), m.end() - m.start())
    return best


def extract_effects(abstract, max_per_paper=3):
    """Ratio estimates with a CI. Drops anything where the CI does not bracket the estimate."""
    text, out = abstract or "", []
    for m in EFFECT.finditer(text):
        est, lo, hi = (float(m.group(i)) for i in (2, 3, 4))
        if not (0 < lo <= est <= hi < 100) or lo == hi:
            continue
        start = _sentence_start(text, m.start())
        end = text.find(". ", m.end())
        out.append({"measure": measure(m.group(1)), "est": est, "lo": lo, "hi": hi,
                    "outcome": outcome_for(text[start:m.start()]),
                    "snippet": text[start:end + 1 if end >= 0 else len(text)].strip()})
        if len(out) == max_per_paper:
            break
    return out


def outcome_tags(abstract):
    return [name for name, rx in _OUT_RE.items() if rx.search(abstract or "")]
