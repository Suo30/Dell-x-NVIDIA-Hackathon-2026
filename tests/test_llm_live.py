import os

import _config
import _llm
import _taxonomy
import pytest
from conftest import ROOT

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("LLM_LIVE") != "1", reason="set LLM_LIVE=1 with the tunnel up"),
]


def test_real_model_extracts_known_skills(monkeypatch):
    monkeypatch.setattr(_config, "MOCK", False)
    resume = (ROOT / "tests" / "fixtures" / "resume.txt").read_text(encoding="utf-8")
    system = (
        "Extract the candidate's skills. Use only these skill ids:\n"
        + _taxonomy.prompt_block()
        + '\nReturn only JSON: {"skills": [{"skill_id": "<id>", "level": 1}]} with level 1 to 3.'
    )
    out = _llm.chat_json(system, resume, mock={"skills": []})
    assert "error" not in out, out
    assert isinstance(out["skills"], list) and out["skills"]
    unknown = [s["skill_id"] for s in out["skills"] if _taxonomy.resolve(s["skill_id"]) is None]
    assert unknown == []
