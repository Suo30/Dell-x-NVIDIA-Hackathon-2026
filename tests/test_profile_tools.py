import json
import sys
import zipfile

import _db
import _llm
import _profile
import _resume_text
import aux_math
import ingest_profile
import match_candidates
import pytest
import seed_db
import update_profile
from conftest import ROOT

RESUME = ROOT / "tests" / "fixtures" / "resume.txt"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _seed(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["seed_db.py", "--reset"])
    return seed_db.main()


def _run(monkeypatch, module, *args):
    monkeypatch.setattr(sys, "argv", [f"{module.__name__}.py", *args])
    return module.main()


def _reply(monkeypatch, reply):
    monkeypatch.setattr(_llm, "chat_json", lambda system, user, *, mock, max_tokens=4000: reply)


def _profile_of(candidate_id):
    conn = _db.connect()
    try:
        row = conn.execute("SELECT profile_json FROM candidates WHERE id = ?", (candidate_id,)).fetchone()
    finally:
        conn.close()
    return json.loads(row["profile_json"])


def _skill(profile, skill_id):
    return next(s for s in profile["skills"] if s["skill_id"] == skill_id)


# _resume_text

def test_txt_and_md(tmp_path):
    txt, md = tmp_path / "r.txt", tmp_path / "r.md"
    txt.write_text("﻿Jordan Rivera\nPython\n", encoding="utf-8")
    md.write_bytes("# Jos\xe9\n- MySQL".encode("cp1252"))
    assert _resume_text.read(txt) == "Jordan Rivera\nPython"
    assert _resume_text.read(md) == "# Jos\xe9\n- MySQL"
    binary = tmp_path / "b.txt"
    binary.write_bytes(b"\x81\x8d\x90")
    with pytest.raises(ValueError, match="cannot read the text"):
        _resume_text.read(binary)


def test_docx_built_in_test(tmp_path):
    path = tmp_path / "r.docx"
    xml = (f'<w:document xmlns:w="{W}"><w:body>'
           "<w:p><w:r><w:t>Jordan Rivera</w:t></w:r></w:p>"
           '<w:p><w:r><w:t xml:space="preserve">Python, </w:t></w:r><w:r><w:t>MySQL</w:t></w:r></w:p>'
           "</w:body></w:document>")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", xml)
    assert _resume_text.read(path) == "Jordan Rivera\nPython, MySQL"

    bad = tmp_path / "bad.docx"
    bad.write_text("not a zip", encoding="utf-8")
    with pytest.raises(ValueError, match="not a valid .docx"):
        _resume_text.read(bad)


def test_pdf_without_pypdf_raises(tmp_path, monkeypatch):
    path = tmp_path / "r.pdf"
    path.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setitem(sys.modules, "pypdf", None)
    with pytest.raises(ValueError, match="PDF needs pypdf"):
        _resume_text.read(path)


def test_pdf_without_text_layer_raises(tmp_path):
    pypdf = pytest.importorskip("pypdf")
    path = tmp_path / "scan.pdf"
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with open(path, "wb") as f:
        writer.write(f)
    with pytest.raises(ValueError, match="no text layer"):
        _resume_text.read(path)


def test_empty_raises(tmp_path):
    path = tmp_path / "r.txt"
    path.write_text("  \n\n", encoding="utf-8")
    with pytest.raises(ValueError, match="resume is empty"):
        _resume_text.read(path)


def test_unknown_extension_raises(tmp_path):
    path = tmp_path / "r.rtf"
    path.write_text("Jordan", encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported resume type .rtf"):
        _resume_text.read(path)


# ingest_profile

GOOD_FACTS = {
    "school": "Northeastern University", "program": "MS ME",
    "visa": {"status": "F-1", "needs_sponsorship": True, "us_person": False},
    "availability": {"start": "2027-01", "type": "co-op"},
    "location": {"preferred": ["Boston, MA"], "remote": "any"},
    "bullets": ["Built a pipeline", "", 7],
}


def _ingest(monkeypatch, *extra):
    return _run(monkeypatch, ingest_profile, "--name", "Jordan Rivera", "--text-file", str(RESUME), *extra)


def test_mock_creates_c031_after_seed(tmp_db, mock_llm, monkeypatch):
    _seed(monkeypatch)
    out = _ingest(monkeypatch, "--notes", "I also know Docker")
    assert out["candidate_id"] == "c031"
    assert out["skills_found"] == len(out["profile"]["skills"]) == 7
    assert out["missing"] == [] and out["dropped_skills"] == []
    assert _skill(out["profile"], "react-native")["level"] == 1
    conn = _db.connect()
    try:
        row = conn.execute("SELECT * FROM candidates WHERE id = 'c031'").fetchone()
    finally:
        conn.close()
    assert (row["synthetic"], row["consent_auto"], row["name"]) == (0, 1, "Jordan Rivera")
    stored = json.loads(row["profile_json"])
    _profile.validate(stored, "c031")
    assert stored == out["profile"]
    assert stored["notes"] == ["I also know Docker"]


def test_chat_source_kept(tmp_db, mock_llm, monkeypatch):
    out = _ingest(monkeypatch, "--notes", "I also know Docker")
    assert out["candidate_id"] == "c001"
    assert _skill(out["profile"], "docker")["evidence"] == [{"source": "chat", "text": "I also know Docker"}]
    assert _skill(out["profile"], "python")["evidence"][0]["source"] == "resume"


def test_duplicate_skills_merge(tmp_db, monkeypatch):
    _reply(monkeypatch, {**GOOD_FACTS, "skills": [
        {"skill_id": "python", "level": 1, "source": "resume", "evidence": "Python"},
        {"skill_id": "Python", "level": "2", "source": "resume", "evidence": "Built a Python pipeline"},
        {"skill_id": "python", "level": 1, "source": "chat", "evidence": "Python"},
        {"skill_id": "react native", "level": 1, "source": ["chat"], "evidence": "React Native app"},
    ]})
    out = _ingest(monkeypatch)
    skills = out["profile"]["skills"]
    assert [s["skill_id"] for s in skills] == ["python", "react-native"]
    assert skills[0]["level"] == 2
    assert skills[0]["evidence"] == [{"source": "resume", "text": "Python"},
                                     {"source": "resume", "text": "Built a Python pipeline"}]
    assert skills[1]["evidence"][0]["source"] == "resume"
    assert out["profile"]["bullets"] == [{"id": "b1", "text": "Built a pipeline"}]


def test_null_visa_reported_missing(tmp_db, monkeypatch):
    _reply(monkeypatch, {**GOOD_FACTS,
                         "visa": {"status": None, "needs_sponsorship": None, "us_person": None},
                         "location": {"preferred": None, "remote": ["hybrid"]},
                         "availability": None,
                         "skills": [{"skill_id": "git", "level": 1, "source": "resume", "evidence": "Git"}]})
    out = _ingest(monkeypatch)
    assert out["missing"] == ["visa", "availability", "location"]
    assert out["profile"]["visa"] == {"status": None, "needs_sponsorship": False, "us_person": False}
    assert out["profile"]["location"] == {"preferred": [], "remote": "any"}
    assert out["profile"]["availability"] == {"start": None, "type": None}


def test_unknown_skill_dropped_and_reported(tmp_db, monkeypatch):
    _reply(monkeypatch, {**GOOD_FACTS, "skills": [
        {"skill_id": "cobol", "level": 2, "source": "resume", "evidence": "COBOL batch jobs"},
        {"skill_id": "mysql", "level": 5, "source": "resume", "evidence": "MySQL"},
        {"skill_id": "git", "level": 1, "source": "resume", "evidence": "  "},
        "python",
        {"skill_id": "python", "level": 2, "source": "resume", "evidence": "Python"},
    ]})
    out = _ingest(monkeypatch)
    assert [s["skill_id"] for s in out["profile"]["skills"]] == ["python"]
    assert out["skills_found"] == 1
    assert out["dropped_skills"] == [
        {"skill": "cobol", "reason": "not in taxonomy"},
        {"skill": "mysql", "reason": "level 5 is not 1, 2 or 3"},
        {"skill": "git", "reason": "no evidence"},
        {"skill": "'python'", "reason": "malformed"},
    ]


def test_ingest_model_error_passes_through(tmp_db, monkeypatch):
    _reply(monkeypatch, {"error": "model unreachable"})
    assert _ingest(monkeypatch) == {"error": "model unreachable"}
    _reply(monkeypatch, {**GOOD_FACTS})
    assert _ingest(monkeypatch) == {"error": "model output missing skills"}


# update_profile

def _update(monkeypatch, candidate, note):
    return _run(monkeypatch, update_profile, "--candidate", candidate, "--note", note)


def test_mock_adds_acme_pref(tmp_db, mock_llm, monkeypatch):
    _seed(monkeypatch)
    out = _update(monkeypatch, "c001", "I'd only go to Acme for a really strong offer")
    assert out == {"candidate_id": "c001", "ignored": [], "changes": [
        {"type": "company_pref", "company": "Acme", "stance": "only_strong_offer", "min_pay": None,
         "action": "added"}]}
    prefs = _profile_of("c001")["company_prefs"]
    assert prefs == [{"company": "Acme", "stance": "only_strong_offer", "min_pay": None}]


def test_pref_replaced_case_insensitive(tmp_db, monkeypatch):
    _seed(monkeypatch)
    _reply(monkeypatch, {"changes": [{"type": "company_pref", "company": "acme", "stance": "never",
                                      "min_pay": None}]})
    out = _update(monkeypatch, "c002", "I never want to work at acme")
    assert out["changes"][0]["action"] == "replaced"
    assert _profile_of("c002")["company_prefs"] == [{"company": "acme", "stance": "never", "min_pay": None}]


def test_skill_level_never_lowered(tmp_db, monkeypatch):
    _seed(monkeypatch)
    _reply(monkeypatch, {"changes": [{"type": "skill", "skill_id": "mysql", "level": 1}]})
    note = "I used MySQL a bit"
    out = _update(monkeypatch, "c002", note)
    assert out["changes"] == [{"type": "skill", "skill_id": "mysql", "level": 2, "action": "evidence_added"}]
    mysql = _skill(_profile_of("c002"), "mysql")
    assert mysql["level"] == 2
    assert mysql["evidence"][-1] == {"source": "chat", "text": note}


def test_chat_evidence_appended(tmp_db, monkeypatch):
    _seed(monkeypatch)
    note = "I led the Docker setup for my lab"
    _reply(monkeypatch, {"changes": [{"type": "skill", "skill_id": "docker", "level": 3},
                                     {"type": "skill", "skill_id": "python", "level": "3"}]})
    out = _update(monkeypatch, "c002", note)
    assert out["changes"] == [{"type": "skill", "skill_id": "docker", "level": 3, "action": "added"},
                              {"type": "skill", "skill_id": "python", "level": 3, "action": "raised"}]
    profile = _profile_of("c002")
    assert _skill(profile, "docker")["evidence"] == [{"source": "chat", "text": note}]
    python = _skill(profile, "python")
    assert python["evidence"][0]["source"] == "resume"
    assert python["evidence"][-1] == {"source": "chat", "text": note}

    again = _update(monkeypatch, "c002", note)
    assert [i["change"]["skill_id"] for i in again["ignored"]] == ["docker", "python"]
    assert again["changes"] == [{"type": "note"}]
    assert len(_skill(_profile_of("c002"), "python")["evidence"]) == len(python["evidence"])


def test_invalid_stance_ignored(tmp_db, monkeypatch):
    _seed(monkeypatch)
    bad = {"type": "company_pref", "company": "Acme", "stance": "maybe", "min_pay": None}
    _reply(monkeypatch, {"changes": [bad, {"type": "salary"}, "oops", {"type": ["skill"]}]})
    note = "Acme is fine I guess"
    out = _update(monkeypatch, "c001", note)
    assert out["changes"] == [{"type": "note"}]
    assert [i["change"] for i in out["ignored"]] == [bad, {"type": "salary"}, "oops", {"type": ["skill"]}]
    assert "stance 'maybe'" in out["ignored"][0]["reason"]
    profile = _profile_of("c001")
    assert profile["company_prefs"] == []
    assert profile["notes"][-1] == note


def test_annual_min_pay_converted(tmp_db, monkeypatch):
    _seed(monkeypatch)
    _reply(monkeypatch, {"changes": [{"type": "company_pref", "company": "Palantir",
                                      "stance": "only_strong_offer", "min_pay": 104000}]})
    out = _update(monkeypatch, "c001", "Palantir only if they pay 104k a year")
    assert aux_math.eq(out["changes"][0]["min_pay"], 50)
    assert aux_math.eq(_profile_of("c001")["company_prefs"][0]["min_pay"], 50)


def test_other_changes_applied(tmp_db, monkeypatch):
    _seed(monkeypatch)
    _reply(monkeypatch, {"changes": [
        {"type": "visa", "status": "green card", "needs_sponsorship": False, "us_person": True},
        {"type": "location", "preferred": ["Austin, TX"], "remote": "hybrid"},
        {"type": "availability", "start": "2027-05", "job_type": None},
        {"type": "visa", "status": "H-1B", "needs_sponsorship": "yes", "us_person": False},
    ]})
    out = _update(monkeypatch, "c001", "I got my green card, I'm moving to Austin and can start in May")
    assert [c["type"] for c in out["changes"]] == ["visa", "location", "availability"]
    assert len(out["ignored"]) == 1
    profile = _profile_of("c001")
    assert profile["visa"] == {"status": "green card", "needs_sponsorship": False, "us_person": True}
    assert profile["location"] == {"preferred": ["Austin, TX"], "remote": "hybrid"}
    assert profile["availability"] == {"start": "2027-05", "type": "co-op"}


def test_matches_cleared(tmp_db, mock_llm, monkeypatch):
    _seed(monkeypatch)
    conn = _db.connect()
    try:
        for job in ("test:a:1", "test:b:2"):
            conn.execute("INSERT INTO matches VALUES (?, 'c001', 50, 'stretch', '{}', ?)", (job, _db.now()))
        conn.execute("INSERT INTO matches VALUES ('test:a:1', 'c002', 50, 'stretch', '{}', ?)", (_db.now(),))
        conn.commit()
    finally:
        conn.close()
    _update(monkeypatch, "c001", "Acme only for a strong offer")
    conn = _db.connect()
    try:
        left = [r["candidate_id"] for r in conn.execute("SELECT candidate_id FROM matches")]
    finally:
        conn.close()
    assert left == ["c002"]


def test_unknown_candidate_raises(tmp_db, mock_llm, monkeypatch):
    _seed(monkeypatch)
    with pytest.raises(ValueError, match="candidate c999 not found"):
        _update(monkeypatch, "c999", "hello")


# match_candidates

def _insert_role(status="approved", with_job=True):
    """Same rows as C's approve_role writes for the fixture Acme job."""
    acme = json.loads((ROOT / "tests" / "fixtures" / "jobs.json").read_text(encoding="utf-8"))[0]
    reqs = [{"skill_id": r["skill_id"], "level": r["level"], "importance": r["importance"],
             "why": r["evidence_text"]} for r in acme["requirements"]]
    public = {"title": "Mobile App Engineer (Co-op)", "description": "Build and own the ops team's app.",
              "location": "Boston, MA (hybrid)", "sponsorship": True, "clearance": "none",
              "pay": "35-45 USD/hour"}
    private = {"requirements": reqs, "seniority": "co-op", "team_context": "2 engineers, no designer",
               "timeline": "start Jan 2027"}
    conn = _db.connect()
    try:
        conn.execute("INSERT INTO roles (id, company, paid, status, public_json, private_json, created)"
                     " VALUES ('r001', 'Acme', 0, ?, ?, ?, ?)",
                     (status, json.dumps(public), json.dumps(private), _db.now()))
        if with_job:
            job_reqs = [{**r, "evidence_text": r["why"]} for r in reqs]
            conn.execute(
                "INSERT INTO jobs (id, source, company, title, url, location, description, role_id,"
                " requirements_json, sponsorship, clearance, pay, paid, first_seen, notified)"
                " VALUES ('internal:r001', 'internal', 'Acme', ?, NULL, ?, ?, 'r001', ?, 1, 'none',"
                " '35-45 USD/hour', 0, ?, 0)",
                (public["title"], public["location"], public["description"], json.dumps(job_reqs), _db.now()))
        conn.commit()
    finally:
        conn.close()


def _shortlist(monkeypatch, *args):
    return _run(monkeypatch, match_candidates, "--role", "r001", *args)


def test_unapproved_role_raises(tmp_db, monkeypatch):
    _seed(monkeypatch)
    _insert_role(status="draft", with_job=False)
    with pytest.raises(ValueError, match="role r001 is 'draft'; approve it first"):
        _shortlist(monkeypatch)


def test_unknown_role_raises(tmp_db, monkeypatch):
    _seed(monkeypatch)
    with pytest.raises(ValueError, match="role r001 not found"):
        _shortlist(monkeypatch)


def test_approved_role_without_job_raises(tmp_db, monkeypatch):
    _seed(monkeypatch)
    _insert_role(with_job=False)
    with pytest.raises(RuntimeError, match="internal:r001 is missing"):
        _shortlist(monkeypatch)


def test_shortlist(tmp_db, monkeypatch):
    _seed(monkeypatch)
    _insert_role()
    _shortlist(monkeypatch)
    out = _shortlist(monkeypatch, "--limit", "50")
    assert (out["role_id"], out["job_id"], out["evaluated"]) == ("r001", "internal:r001", 30)
    assert sum(out["counts"].values()) == 30
    assert out["counts"]["excluded"] == 2

    rows = {r["candidate_id"]: r for r in out["shortlist"]}
    assert rows["c002"]["route"] == "match"
    assert "At my campus job I ran the MySQL database" in rows["c002"]["top_evidence"][1]
    assert "c013" not in rows and "c014" not in rows
    assert len(out["shortlist"]) == 30 - out["counts"]["hidden"] - out["counts"]["excluded"]
    assert out["shortlist"][0]["candidate_id"] == "c004"  # eager for Acme, first among equal scores
    for row in out["shortlist"]:
        assert set(row) == {"candidate_id", "name", "score", "route", "flags", "gaps_text", "top_evidence"}
        assert row["route"] in ("match", "stretch", "review")

    conn = _db.connect()
    try:
        stored = conn.execute("SELECT COUNT(*) FROM matches WHERE job_id = 'internal:r001'").fetchone()[0]
    finally:
        conn.close()
    assert stored == 30

    assert len(_shortlist(monkeypatch)["shortlist"]) == 10
