"""Model access. Owner: C. Extraction only; code decides scores and routes.

    chat_json(system: str, user: str, *, mock: dict, max_tokens: int = 2048) -> dict

- POST {LLM_BASE_URL}/chat/completions with model=LLM_MODEL, temperature=0.
- vLLM accepts "chat_template_kwargs": {"enable_thinking": False} for Qwen3,
  which skips <think> and saves model time. Still strip <think>...</think> in case.
- Strip ``` fences, take the outermost {...}, json.loads it.
- On parse failure, retry once with the bad output and "Return only valid JSON."
- Still bad: return {"error": "..."}; never raise for model trouble.
- MOCK_LLM=1: return `mock` unchanged. Each caller passes a canned dict of the
  shape it expects, so smoke tests run without the box.
- urllib.request only (stdlib). Timeout ~120 s.
"""
import json
import re
import urllib.error
import urllib.request

import _config

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)
_TIMEOUT = 120


def _extract_json_object(text):
    text = _THINK_RE.sub("", text).strip()
    fence = _FENCE_RE.search(text)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object found in model output")
    return json.loads(text[start:end + 1])


def _call(system, user, max_tokens):
    payload = {
        "model": _config.LLM_MODEL,
        "temperature": 0,
        "max_tokens": max_tokens,
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    req = urllib.request.Request(
        f"{_config.LLM_BASE_URL}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return body["choices"][0]["message"]["content"]


def chat_json(system, user, *, mock, max_tokens=2048):
    if _config.MOCK:
        return mock
    try:
        raw = _call(system, user, max_tokens)
    except (urllib.error.URLError, TimeoutError, KeyError, IndexError) as e:
        return {"error": f"model request failed: {e}"}

    try:
        return _extract_json_object(raw)
    except (ValueError, json.JSONDecodeError):
        pass

    try:
        retry_user = (
            f"{user}\n\nYour previous reply was not valid JSON:\n{raw}\n"
            "Return only valid JSON, no commentary, no markdown fences."
        )
        raw2 = _call(system, retry_user, max_tokens)
        return _extract_json_object(raw2)
    except (ValueError, json.JSONDecodeError, urllib.error.URLError, TimeoutError, KeyError, IndexError) as e:
        return {"error": f"model did not return valid JSON: {e}"}
