import json
import os
import urllib.request

import _config
import _llm
import _taxonomy
import pytest
from conftest import ROOT

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("LLM_LIVE") != "1", reason="set LLM_LIVE=1 with the tunnel up"),
]

SKILLS_SYSTEM = (
    "Extract the candidate's skills. Use only these skill ids:\n"
    + _taxonomy.prompt_block()
    + '\nReturn only JSON: {"skills": [{"skill_id": "<id>", "level": 1}]} with level 1 to 3.'
)


@pytest.fixture(autouse=True)
def real_model(monkeypatch):
    monkeypatch.setattr(_config, "MOCK", False)


def test_model_is_served():
    with urllib.request.urlopen(_config.LLM_BASE_URL + "/models", timeout=10) as resp:
        ids = [m["id"] for m in json.loads(resp.read().decode("utf-8"))["data"]]
    assert _config.LLM_MODEL in ids


def test_raw_response_fields():
    messages = [{"role": "system", "content": 'Return only JSON: {"ok": true}'},
                {"role": "user", "content": "ping"}]
    content, finish = _llm._post(messages, 4000)
    assert finish == "stop", f"finish_reason {finish!r}; raise max_tokens if 'length'"
    assert isinstance(content, str) and content.strip()
    assert _llm._extract(content) == {"ok": True}


def test_real_model_extracts_known_skills():
    resume = (ROOT / "tests" / "fixtures" / "resume.txt").read_text(encoding="utf-8")
    out = _llm.chat_json(SKILLS_SYSTEM, resume, mock={"skills": []})
    assert "error" not in out, out
    assert isinstance(out["skills"], list) and out["skills"]
    unknown = [s["skill_id"] for s in out["skills"] if _taxonomy.resolve(s["skill_id"]) is None]
    assert unknown == []
    for s in out["skills"]:
        assert s["level"] in (1, 2, 3), s
