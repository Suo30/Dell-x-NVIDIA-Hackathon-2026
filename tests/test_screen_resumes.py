import json

import pytest

# recruit_assistant deps are optional for tools/ laptops: pip install -r requirements-recruit.txt
for _dep in ("fastapi", "pydantic", "docx"):
    pytest.importorskip(_dep, reason="recruit_assistant deps missing: pip install -r requirements-recruit.txt")

import _db
import screen_resumes

PUBLIC = {
    "title": "Ops App Engineer (Co-op)",
    "description": "Build an internal app for the ops team.",
    "location": "Boston, MA (hybrid)",
    "sponsorship": True,
    "clearance": "none",
    "pay": None,
}
PRIVATE = {
    "requirements": [
        {"skill_id": "python", "level": 2, "importance": "must", "why": "backend"},
        {"skill_id": "mysql", "level": 2, "importance": "must", "why": "data layer"},
        {"skill_id": "react", "level": 1, "importance": "nice", "why": "simple UI"},
    ],
    "seniority": "co-op",
    "team_context": "2 engineers",
    "timeline": "Jan 2027",
}


def _insert_role(status):
    conn = _db.connect()
    conn.execute(
        "INSERT INTO roles (id, company, paid, status, public_json, private_json, created) VALUES (?, ?, 0, ?, ?, ?, ?)",
        ("r001", "Acme", status, json.dumps(PUBLIC), json.dumps(PRIVATE), _db.now()),
    )
    conn.commit()
    conn.close()


def _fit(evidence):
    return {
        "summary": "Evidence reviewed.",
        "strengths": [evidence],
        "unknowns": [],
        "criteria": [
            {"criterion_id": r["skill_id"], "criterion": r["skill_id"], "required": r["importance"] == "must",
             "assessment": "demonstrated", "evidence": [evidence], "confidence": 0.9}
            for r in PRIVATE["requirements"]
        ],
        "source_assessments": [
            {"source": "resume", "assessment": "strong", "rationale": "Direct.", "evidence": [evidence]}
        ],
    }


@pytest.fixture
def resumes(tmp_path, monkeypatch):
    monkeypatch.setattr("recruit_assistant.storage.JOBS_DIR", tmp_path / "jobs")
    d = tmp_path / "applicants"
    d.mkdir()
    (d / "ana.txt").write_text(
        "Ana Doe\nBuilt Python services on MySQL at Acme 2022-2024\nhttps://github.com/octocat", encoding="utf-8"
    )
    (d / "ben.txt").write_text("Ben Roe\nReact course project", encoding="utf-8")
    (d / "notes.md").write_text("not a resume", encoding="utf-8")
    return d


def test_rubric_weights_follow_must_and_nice():
    criteria = screen_resumes.rubric_criteria(PRIVATE["requirements"])
    assert [c["criterion_id"] for c in criteria] == ["python", "mysql", "react"]
    assert [c["required"] for c in criteria] == [True, True, False]
    assert [c["weight"] for c in criteria] == pytest.approx([40, 40, 20])
    assert criteria[0]["title"] == "Python"
    assert criteria[0]["description"].startswith("Level 2: ")


def test_rubric_rejects_role_without_requirements():
    with pytest.raises(ValueError, match="no requirements"):
        screen_resumes.rubric_criteria([])


def test_missing_and_unapproved_roles_are_rejected(tmp_db):
    with pytest.raises(ValueError, match="not found"):
        screen_resumes.load_role("r001")
    _insert_role("draft")
    with pytest.raises(ValueError, match="approve it"):
        screen_resumes.load_role("r001")


def test_role_screen_uses_role_rubric_and_no_web_without_consent(tmp_db, resumes, monkeypatch):
    _insert_role("approved")
    prompts = []

    def fake_complete_json(system_prompt, user_prompt):
        prompts.append(user_prompt)
        return _fit("Built Python services on MySQL")

    monkeypatch.setattr("recruit_assistant.local_llm.complete_json", fake_complete_json)
    out = screen_resumes.screen("r001", None, None, [str(resumes)], consent=False, discover=False)

    assert out["rubric_source"] == "role"
    assert {r["file"] for r in out["results"]} == {"ana.txt", "ben.txt"}
    assert all(r["sources"] == [] for r in out["results"])
    assert all(r["rank"] is not None for r in out["results"])
    assert out["shortlist_count"] >= 1
    assert len(prompts) == 2
    assert '"criterion_id":"python"' in prompts[0]
    assert "Ops App Engineer (Co-op) at Acme" in prompts[0]


def test_discover_requires_consent(tmp_db, resumes):
    with pytest.raises(ValueError, match="--discover needs --consent-confirmed"):
        screen_resumes.screen(None, "Backend", "Python required", [str(resumes)], consent=False, discover=True)


def test_title_mode_routes_to_human_review_when_model_unavailable(resumes, mock_llm):
    out = screen_resumes.screen(None, "Backend", "Python required", [str(resumes)], consent=False, discover=False)
    assert out["rubric_source"] == "unavailable"
    assert out["shortlist_count"] == 0
    assert {r["route"] for r in out["results"]} == {"human_review_required"}
    assert "Fit review: Backend" in out["slack"]
    assert out["notice"] in out["slack"]


def test_slack_report_lists_scores_and_gaps():
    text = screen_resumes.slack_report(
        "Senior Applied AI Scientist",
        [
            {
                "file": "sneha.pdf",
                "rank": 1,
                "top_30_percent": True,
                "evidence_score": 95.0,
                "coverage": 70.0,
                "fit_label": "strong_role_alignment",
                "required_met": "4/4",
                "hard_gaps": [],
                "summary": "ok",
                "strengths": ["RAG"],
                "unknowns": [],
            }
        ],
        "Decision support only.",
    )
    assert "*Fit review: Senior Applied AI Scientist*" in text
    assert "95.0/100" in text
    assert "Strong demonstrated alignment" in text
    assert "Decision support only." in text
