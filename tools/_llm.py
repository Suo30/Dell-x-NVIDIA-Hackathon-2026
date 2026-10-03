"""Model access. Owner: C. Extraction only; code decides scores and routes.

Proposed signature (C may change it; tell B and D in chat if you do):

    chat_json(system: str, user: str, *, mock: dict, max_tokens: int = 2048) -> dict

- POST {LLM_BASE_URL}/chat/completions with model=LLM_MODEL, temperature=0.
- Tip: vLLM accepts "chat_template_kwargs": {"enable_thinking": False} for Qwen3,
  which skips <think> and saves model time. Still strip <think>...</think> in case.
- Strip ``` fences, take the outermost {...}, json.loads it.
- On parse failure, retry once with the bad output and "Return only valid JSON."
- Still bad: return {"error": "..."}; never raise for model trouble.
- MOCK_LLM=1: return `mock` unchanged. Each caller passes a canned dict of the
  shape it expects, so smoke tests run without the box.
- urllib.request only (stdlib). Timeout ~120 s.
"""
import _config


def chat_json(system, user, *, mock, max_tokens=2048):
    if _config.MOCK:
        return mock
    raise NotImplementedError("_llm.chat_json (owner: C)")
