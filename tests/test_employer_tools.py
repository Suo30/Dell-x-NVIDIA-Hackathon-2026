import json
import sys

import _db
import _llm
import _match
import approve_role
import draft_role
import match_jobs
import pytest
import seed_db
import show_role
from conftest import ROOT

CONVERSATION = str(ROOT / "tests" / "fixtures" / "conversation.txt")
PUBLIC = {
    "title": "Ops App Engineer (Co-op)",
    "description": "Build an internal app for the ops team.",
    "location": "Boston, MA (hybrid)",
    "sponsorship": True,
    "clearance": "none",
    "pay": None,
}


def _run(monkeypatch, module, *args):
    monkeypatch.setattr(sys, "argv", [f"{module.__name__}.py", *args])
    return module.main()


def _draft(monkeypatch, *extra):
    return _run(monkeypatch, draft_role, "--company", "Acme", "--conversation-file", CONVERSATION, *extra)


def _approve(monkeypatch, role_id="r001", edits=None, tmp_path=None):
    args = ["--role", role_id]
    if edits is not None:
        path = tmp_path / "edits.json"
        path.write_text(json.dumps(edits), encoding="utf-8")
        args += ["--edits-file", str(path)]
    return _run(monkeypatch, approve_role, *args)


def _fake_llm(monkeypatch, reply):
    calls = []

    def chat_json(system, user, *, mock, max_tokens):
        calls.append({"system": system, "user": user, "max_tokens": max_tokens})
        return reply

    monkeypatch.setattr(_llm, "chat_json", chat_json)
    return calls


def _query(sql, params=()):
    conn = _db.connect()
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def _c001():
    return json.loads((ROOT / "data" / "candidates" / "c001.json").read_text(encoding="utf-8"))


# draft_role

def test_draft_mock_creates_r001_draft(tmp_db, mock_llm, monkeypatch):
    out = _draft(monkeypatch)
    assert out["role_id"] == "r001"
    assert out["status"] == "draft"
    assert out["company"] == "Acme"
    assert out["dropped_skills"] == []
    assert out["public"]["title"] == "Mobile App Engineer (Co-op)"
    assert out["public"]["location"] == "Boston, MA (hybrid)"
    assert out["public"]["sponsorship"] is True
    assert out["public"]["pay"] == "35-45 USD/hour"
    reqs = [(r["skill_id"], r["level"], r["importance"]) for r in out["private"]["requirements"]]
    assert reqs == [("react-native", 2, "must"), ("mysql", 2, "must"), ("python", 1, "nice"), ("git", 1, "nice")]
    assert out["private"]["team_context"] == "2 engineers, no designer"

    [row] = _query("SELECT * FROM roles")
    assert (row["id"], row["company"], row["status"], row["paid"]) == ("r001", "Acme", "draft", 0)
    assert json.loads(row["public_json"]) == out["public"]
    assert json.loads(row["private_json"]) == out["private"]

    assert _draft(monkeypatch, "--paid")["role_id"] == "r002"
    assert _query("SELECT paid FROM roles WHERE id = 'r002'")[0]["paid"] == 1


def test_draft_sends_conversation_and_taxonomy(tmp_db, monkeypatch):
    calls = _fake_llm(monkeypatch, draft_role._MOCK)
    _draft(monkeypatch)
    [call] = calls
    assert call["max_tokens"] == 4000
    assert call["user"].startswith("COMPANY: Acme\n\nCONVERSATION:\nmanager: I need someone")
    assert "react-native: React Native" in call["system"]
    assert "{taxonomy}" not in call["system"]


def test_draft_drops_unknown_skill_and_reports_it(tmp_db, monkeypatch):
    reply = json.loads(json.dumps(draft_role._MOCK))
    reply["private"]["requirements"].append(
        {"skill_id": "COBOL", "level": 2, "importance": "nice", "why": "legacy reports"})
    _fake_llm(monkeypatch, reply)
    out = _draft(monkeypatch)
    assert out["dropped_skills"] == [{"skill": "COBOL", "reason": "not in taxonomy"}]
    assert [r["skill_id"] for r in out["private"]["requirements"]] == ["react-native", "mysql", "python", "git"]


def test_draft_no_skills_returns_error(tmp_db, monkeypatch):
    reply = json.loads(json.dumps(draft_role._MOCK))
    reply["private"]["requirements"] = [{"skill_id": "COBOL", "level": 2, "importance": "must", "why": "x"}]
    _fake_llm(monkeypatch, reply)
    out = _draft(monkeypatch)
    assert out == {"error": draft_role.NO_SKILLS, "dropped_skills": [{"skill": "COBOL", "reason": "not in taxonomy"}]}
    assert _query("SELECT id FROM roles") == []


@pytest.mark.parametrize("reply,expected", [
    ({"error": "model unreachable at http://x: refused"}, {"error": "model unreachable at http://x: refused"}),
    ({"private": {}}, {"error": "model output missing public"}),
    ({"public": PUBLIC}, {"error": "model output missing private"}),
    ({"public": PUBLIC, "private": {"seniority": "co-op"}}, {"error": "model output missing private.requirements"}),
])
def test_draft_model_error_passes_through(tmp_db, monkeypatch, reply, expected):
    _fake_llm(monkeypatch, reply)
    assert _draft(monkeypatch) == expected
    assert _query("SELECT id FROM roles") == []


def test_draft_empty_conversation_raises(tmp_db, mock_llm, monkeypatch, tmp_path):
    empty = tmp_path / "empty.txt"
    empty.write_text("  \n", encoding="utf-8")
    with pytest.raises(ValueError, match="conversation file is empty"):
        _run(monkeypatch, draft_role, "--company", "Acme", "--conversation-file", str(empty))


# show_role

def test_show_unknown_raises(tmp_db, monkeypatch):
    with pytest.raises(ValueError, match="role r999 not found"):
        _run(monkeypatch, show_role, "--role", "r999")


def test_show_job_id_only_when_approved(tmp_db, mock_llm, monkeypatch):
    draft = _draft(monkeypatch)
    out = _run(monkeypatch, show_role, "--role", "r001")
    assert out == {"role_id": "r001", "company": "Acme", "paid": False, "status": "draft",
                   "public": draft["public"], "private": draft["private"], "job_id": None}
    _approve(monkeypatch)
    out = _run(monkeypatch, show_role, "--role", "r001")
    assert (out["status"], out["job_id"]) == ("approved", "internal:r001")


# approve_role

def test_approve_unknown_raises(tmp_db, monkeypatch):
    with pytest.raises(ValueError, match="role r999 not found"):
        _approve(monkeypatch, "r999")


def test_approve_publishes_internal_job(tmp_db, mock_llm, monkeypatch):
    draft = _draft(monkeypatch)
    out = _approve(monkeypatch)
    assert out == {"role_id": "r001", "job_id": "internal:r001", "status": "approved",
                   "public": draft["public"], "private": draft["private"]}
    assert _query("SELECT status FROM roles WHERE id = 'r001'")[0]["status"] == "approved"

    [row] = _query("SELECT * FROM jobs")
    assert row["id"] == "internal:r001"
    assert (row["source"], row["role_id"], row["company"], row["url"]) == ("internal", "r001", "Acme", None)
    assert (row["title"], row["location"]) == ("Mobile App Engineer (Co-op)", "Boston, MA (hybrid)")
    assert (row["sponsorship"], row["clearance"], row["pay"]) == (1, "none", "35-45 USD/hour")
    assert (row["paid"], row["notified"]) == (0, 0)
    reqs = json.loads(row["requirements_json"])
    assert [r["skill_id"] for r in reqs] == ["react-native", "mysql", "python", "git"]
    assert all(r["evidence_text"] == r["why"] for r in reqs)

    result = _match.evaluate(_match.job_from_row(row), _c001())
    assert result["route"] in _match.ROUTE_ORDER
    assert len(result["detail"]["requirements"]) == 4


def test_approve_paid_and_unknown_sponsorship(tmp_db, monkeypatch):
    reply = json.loads(json.dumps(draft_role._MOCK))
    reply["public"]["sponsorship"] = None
    _fake_llm(monkeypatch, reply)
    _draft(monkeypatch, "--paid")
    _approve(monkeypatch)
    [row] = _query("SELECT sponsorship, paid FROM jobs")
    assert (row["sponsorship"], row["paid"]) == (None, 1)
    assert _match.job_from_row(_query("SELECT * FROM jobs")[0])["sponsorship"] is None


def test_approve_edits_merge_and_replace_requirements(tmp_db, mock_llm, monkeypatch, tmp_path):
    _draft(monkeypatch)
    edits = {
        "public": {"pay": "40-50 USD/hour"},
        "private": {
            "requirements": [
                {"skill_id": "React Native", "level": 3, "importance": "must", "why": "leads the app"},
                {"skill_id": "mysql", "level": "2", "importance": "Nice", "why": "reports"},
            ],
            "timeline": "start Feb 2027",
        },
    }
    out = _approve(monkeypatch, edits=edits, tmp_path=tmp_path)
    assert out["public"]["pay"] == "40-50 USD/hour"
    assert out["public"]["title"] == "Mobile App Engineer (Co-op)"
    assert out["private"]["requirements"] == [
        {"skill_id": "react-native", "level": 3, "importance": "must", "why": "leads the app"},
        {"skill_id": "mysql", "level": 2, "importance": "nice", "why": "reports"},
    ]
    assert out["private"]["timeline"] == "start Feb 2027"
    assert out["private"]["team_context"] == "2 engineers, no designer"

    stored = _run(monkeypatch, show_role, "--role", "r001")
    assert (stored["public"], stored["private"]) == (out["public"], out["private"])
    [row] = _query("SELECT pay, requirements_json FROM jobs")
    assert row["pay"] == "40-50 USD/hour"
    assert [r["skill_id"] for r in json.loads(row["requirements_json"])] == ["react-native", "mysql"]


@pytest.mark.parametrize("edits,match", [
    ({"title": "New title"}, "unknown edit keys"),
    ({"public": {"titel": "New title"}}, "unknown public keys"),
    ({"private": ["requirements"]}, "private must be an object"),
    ([{"public": {}}], "edits must be a JSON object"),
    ({"private": {"requirements": [{"skill_id": "COBOL", "level": 2, "importance": "must", "why": "x"}]}},
     r"COBOL \(not in taxonomy\)"),
    ({"public": {"clearance": "secret"}}, "role r001: public.clearance"),
    ({"private": {"requirements": []}}, "role r001: private.requirements must be a non-empty list"),
])
def test_approve_bad_edit_key_raises(tmp_db, mock_llm, monkeypatch, tmp_path, edits, match):
    _draft(monkeypatch)
    with pytest.raises(ValueError, match=match):
        _approve(monkeypatch, edits=edits, tmp_path=tmp_path)
    assert _query("SELECT status FROM roles")[0]["status"] == "draft"
    assert _query("SELECT id FROM jobs") == []


def test_reapprove_keeps_first_seen_and_clears_matches(tmp_db, mock_llm, monkeypatch, tmp_path):
    _draft(monkeypatch)
    _approve(monkeypatch)
    old = "2026-01-01T00:00:00+00:00"
    conn = _db.connect()
    try:
        conn.execute("UPDATE jobs SET first_seen = ? WHERE id = 'internal:r001'", (old,))
        conn.executemany(
            "INSERT INTO matches (job_id, candidate_id, score, route, detail_json, created)"
            " VALUES (?, 'c001', 80, 'match', '{}', ?)",
            [("internal:r001", old), ("test:acme:1", old)],
        )
        conn.commit()
    finally:
        conn.close()

    out = _approve(monkeypatch, edits={"public": {"pay": "40-50 USD/hour"}}, tmp_path=tmp_path)
    assert out["status"] == "approved"
    [row] = _query("SELECT first_seen, pay FROM jobs")
    assert (row["first_seen"], row["pay"]) == (old, "40-50 USD/hour")
    assert [r["job_id"] for r in _query("SELECT job_id FROM matches")] == ["test:acme:1"]


def test_approved_role_without_job_raises(tmp_db, mock_llm, monkeypatch):
    _draft(monkeypatch)
    _approve(monkeypatch)
    conn = _db.connect()
    try:
        conn.execute("DELETE FROM jobs")
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(RuntimeError, match="job internal:r001 is missing"):
        _approve(monkeypatch)


# connected story

def test_connected_story(tmp_db, mock_llm, monkeypatch):
    assert _run(monkeypatch, seed_db)["jobs"] == 0
    _draft(monkeypatch)
    _approve(monkeypatch)
    out = _run(monkeypatch, match_jobs, "--candidate", "c001", "--limit", "50")
    assert "internal:r001" in [m["job_id"] for m in out["matches"]]
