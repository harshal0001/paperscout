"""OpenAI-compatible client for Nebius Token Factory, JSON-only completions keyed by role."""
import json
import os
import re

from openai import OpenAI

BASE_URL = os.environ.get("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1/")
MODELS = {
    "planner": os.environ.get("PLANNER_MODEL", "nvidia/nemotron-3-super-120b-a12b"),
    "ranker": os.environ.get("RANKER_MODEL", "nvidia/Nemotron-3_5-Lightning"),
    "writer": os.environ.get("WRITER_MODEL", "nvidia/nemotron-3-super-120b-a12b"),
}


class LLMError(RuntimeError):
    pass


def parse_json(text):
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise LLMError(f"no JSON object in reply: {text[:200]!r}")
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        raise LLMError(f"invalid JSON ({e}): {text[:200]!r}") from e


class LLM:
    def __init__(self, api_key=None):
        key = api_key or os.environ.get("NEBIUS")
        if not key:
            raise LLMError("env var NEBIUS (Token Factory API key) is not set")
        self.client = OpenAI(base_url=BASE_URL, api_key=key, timeout=90, max_retries=2)
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0}

    def complete_json(self, role, system, user, max_tokens=1500, schema=None):
        """Schema-constrained decoding when a schema is given (free-form JSON broke deterministically in testing);
        one retry on unparseable output; thinking disabled (it ate the whole token budget in testing)."""
        extra = {"response_format": {"type": "json_schema", "json_schema": {"name": role, "schema": schema, "strict": True}}} \
            if schema else {}
        last = None
        for _ in range(2):
            r = self.client.chat.completions.create(
                model=MODELS[role], temperature=0, max_tokens=max_tokens,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                extra_body={"chat_template_kwargs": {"enable_thinking": False}}, **extra,
            )
            if r.usage:
                self.usage["prompt_tokens"] += r.usage.prompt_tokens
                self.usage["completion_tokens"] += r.usage.completion_tokens
            try:
                return parse_json(r.choices[0].message.content)
            except LLMError as e:
                last = e
        raise last
