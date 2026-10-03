"""Model access. Owner: C. Extraction only; code decides scores and routes.

    chat_json(system: str, user: str, *, mock: dict, max_tokens: int = 4000) -> dict

- POST {LLM_BASE_URL}/chat/completions with model=LLM_MODEL, temperature=0,
  chat_template_kwargs.enable_thinking=False (Qwen3 skips <think>).
- Reads only choices[0].message.content; the separate "reasoning" field is ignored.
  Content is stripped (it starts with blank lines), then <think>...</think> and
  ``` fences are removed and the outermost {...} is parsed.
- Thinking tokens count against max_tokens, so keep the default 4000 for extraction.
  finish_reason "length" is a failed call (content may be empty): returns an error.
- On parse failure, retries once with the bad output and a "Return only the JSON object" turn.
- Never raises for model trouble (unreachable, HTTP error, truncated, bad JSON):
  returns {"error": "..."} instead.
- MOCK_LLM=1: returns a deep copy of `mock`. Each caller passes a canned dict of
  the shape it expects, so smoke tests run without the box.

Caller rule: check `"error" in out` first and pass it through unchanged, then
validate the keys you need and return {"error": "model output missing <key>"}.

Self-check: `python tools/_llm.py` runs one small skills extraction and prints
{"ok", "seconds", "base_url", "model", "result"}.
"""
import copy
import json
import re
import time
import urllib.error
import urllib.request

import _config

TIMEOUT = 180
RETRY_PROMPT = "Your last reply was not valid JSON. Return only the JSON object."


class _BadResponse(Exception):
    """Server answered, but not in the chat/completions shape."""


def _post(messages, max_tokens):
    body = {
        "model": _config.LLM_MODEL,
        "messages": messages,
        "temperature": 0,
        "max_tokens": max_tokens,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    req = urllib.request.Request(
        _config.LLM_BASE_URL + "/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        raw = resp.read().decode("utf-8")
    # External boundary: vLLM response
    try:
        choice = json.loads(raw)["choices"][0]
        content, finish = choice["message"]["content"], choice["finish_reason"]
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise _BadResponse(f"{type(e).__name__}: {e}; body {raw[:200]!r}") from None
    return content, finish


def _extract(text):
    text = text.strip().rsplit("</think>", 1)[-1]
    text = re.sub(r"```(?:json)?", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError(f"no JSON object in model output: {text[:200]!r}")
    obj = json.loads(text[start:end + 1])
    if not isinstance(obj, dict):
        raise ValueError("model output is not a JSON object")  # noqa: TRY004, retried as a parse failure
    return obj


def chat_json(system, user, *, mock, max_tokens=4000):
    if _config.MOCK:
        return copy.deepcopy(mock)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    for _ in range(2):
        try:
            content, finish = _post(messages, max_tokens)
        except (urllib.error.URLError, OSError) as e:
            return {"error": f"model unreachable at {_config.LLM_BASE_URL}: {e}"}
        except _BadResponse as e:
            return {"error": f"bad model response from {_config.LLM_BASE_URL}: {e}"}
        if finish == "length":
            return {"error": f"model output truncated at max_tokens={max_tokens}"}
        if not isinstance(content, str):
            return {"error": f"bad model response: message.content is {type(content).__name__}, expected str"}
        try:
            return _extract(content)
        except ValueError:
            messages = messages + [
                {"role": "assistant", "content": content},
                {"role": "user", "content": RETRY_PROMPT},
            ]
    return {"error": f"invalid JSON after retry: {content[:200]}"}


def _selfcheck():
    import _taxonomy

    lines = (_config.REPO / "tests" / "fixtures" / "resume.txt").read_text(encoding="utf-8").splitlines()
    skills_line = lines[lines.index("SKILLS") + 1]
    system = (
        "Extract skills from the text. Use only these skill ids:\n"
        + _taxonomy.prompt_block()
        + '\nReturn only JSON: {"skills": [{"skill_id": "<id>", "level": 1}]} with level 1 to 3.'
    )
    t0 = time.monotonic()
    out = chat_json(system, skills_line, mock={"skills": []})
    seconds = round(time.monotonic() - t0, 2)
    # Model boundary: skills may be missing
    ok = "error" not in out and isinstance(out.get("skills"), list)
    return {"ok": ok, "seconds": seconds, "base_url": _config.LLM_BASE_URL,
            "model": _config.LLM_MODEL, "result": out}


if __name__ == "__main__":
    import _cli

    _cli.run(_selfcheck)
