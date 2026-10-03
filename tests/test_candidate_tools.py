import json
import sqlite3
import sys
import urllib.error

import _db
import _llm
import apply
import extract_reqs
import fetch_jobs
import list_jobs
import match_jobs
import pytest
import seed_db


def _run(monkeypatch, module, *args):
    monkeypatch.setattr(sys, "argv", [f"{module.__name__}.py", *args])
    return module.main()


def _seed(monkeypatch, *flags):
    return _run(monkeypatch, seed_db, "--reset", *flags)


def _rows(db, sql, params=()):
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def _insert_job(job_id, source, requirements_json=None, clearance=None, pay=None):
    conn = _db.connect()
    try:
        conn.execute(
            "INSERT INTO jobs (id, source, company, title, url, location, description, requirements_json,"
            " clearance, pay, first_seen) VALUES (?, ?, 'Acme', 'Mechanical Engineering Intern', NULL,"
            " 'Somerville, MA', 'Design parts in SolidWorks.', ?, ?, ?, ?)",
            (job_id, source, requirements_json, clearance, pay, _db.now()),
        )
        conn.commit()
    finally:
        conn.close()


def _job(job_id, title, location):
    return {"id": job_id, "source": "greenhouse", "company": "Acme", "title": title, "url": f"https://x/{job_id}",
            "location": location, "description": "text"}


def _greenhouse_raw(native_id, title, location):
    return {"id": native_id, "title": title, "absolute_url": f"https://x/{native_id}",
            "location": {"name": location}, "content": "&lt;p&gt;Python &amp;amp; SQL&lt;/p&gt;"}


# fetch_jobs

def test_html_to_text_unescapes_and_strips():
    assert fetch_jobs._html_to_text("&lt;p&gt;A &amp;amp; B&lt;/p&gt;&lt;li&gt;x&lt;/li&gt;") == "A & B\nx"


def test_select_filters_us_early_career():
    jobs = [
        _job("1", "Mechanical Engineering Intern", "Somerville, MA"),
        _job("2", "Software Engineering Intern", "Boston, Massachusetts, USA"),
        _job("3", "Internal Tools Engineer", "Boston, MA"),
        _job("4", "International Sales Lead", "Boston, MA"),
        _job("5", "Software Engineer Intern", "Paris, France"),
    ]
    kept = fetch_jobs._select(jobs, 5)
    assert [j["title"] for j in kept] == ["Mechanical Engineering Intern", "Software Engineering Intern"]


def test_select_dedupes_title_prefers_ma():
    jobs = [_job("1", "Software Engineer, Internship", "New York, NY"),
            _job("2", "Software Engineer, Internship", "Boston, MA"),
            _job("3", "Software Engineer, Internship", "Seattle, WA")]
    kept = fetch_jobs._select(jobs, 5)
    assert len(kept) == 1
    assert kept[0]["location"] == "Boston, MA"


def test_select_sorts_by_id_and_caps():
    jobs = [_job(str(i), f"Intern {i}", "Boston, MA") for i in (3, 1, 2)]
    assert [j["id"] for j in fetch_jobs._select(jobs, 2)] == ["1", "2"]


def test_normalize_lever_joins_lists():
    raw = {
        "id": "abc", "text": "Software Engineer, Internship", "hostedUrl": "https://jobs.lever.co/x/abc",
        "categories": {"commitment": "Internship"},
        "descriptionPlain": "About us.\n",
        "lists": [{"text": "What We Require", "content": "<li>Python</li><li>US citizenship</li>"}],
        "additionalPlain": "Pay: $10,000/month",
    }
    job = fetch_jobs._normalize_lever("Palantir", "palantir", raw)
    assert job == {
        "id": "lever:palantir:abc", "source": "lever", "company": "Palantir",
        "title": "Software Engineer, Internship", "url": "https://jobs.lever.co/x/abc", "location": None,
        "description": "About us.\n\nWhat We Require\n\nPython\nUS citizenship\n\nPay: $10,000/month",
    }
    del raw["additionalPlain"]
    assert fetch_jobs._normalize_lever("Palantir", "palantir", raw)["description"].endswith("US citizenship")


def test_fetch_offline_reports_new_once(tmp_db, tmp_path, monkeypatch):
    snap = tmp_path / "snapshots"
    snap.mkdir()
    jobs = [_job("greenhouse:acme:1", "Intern A", "Boston, MA"), _job("greenhouse:acme:2", "Intern B", "Boston, MA")]
    (snap / "greenhouse-acme.json").write_text(json.dumps(jobs), encoding="utf-8")
    monkeypatch.setattr(fetch_jobs, "SNAPSHOT_DIR", snap)

    first = _run(monkeypatch, fetch_jobs, "--offline")
    assert len(first["new"]) == 2
    assert first["new"][0] == {"id": "greenhouse:acme:1", "company": "Acme", "title": "Intern A",
                               "url": "https://x/greenhouse:acme:1"}
    assert first["total"] == 2 and first["failed"] == []
    second = _run(monkeypatch, fetch_jobs, "--offline")
    assert second["new"] == []
    assert second["total"] == 2
    assert _run(monkeypatch, fetch_jobs, "--offline", "--source", "lever")["new"] == []


def test_load_snapshot_missing_key_raises(tmp_path, monkeypatch):
    bad = _job("greenhouse:acme:1", "Intern A", "Boston, MA")
    del bad["url"]
    (tmp_path / "greenhouse-acme.json").write_text(json.dumps([bad]), encoding="utf-8")
    monkeypatch.setattr(fetch_jobs, "SNAPSHOT_DIR", tmp_path)
    with pytest.raises(RuntimeError, match=r"greenhouse-acme.json: job \[0\] is missing \['url'\]"):
        fetch_jobs._load_snapshots("all")


def test_fetch_online_failure_is_reported(tmp_db, tmp_path, monkeypatch):
    companies = tmp_path / "companies.json"
    companies.write_text(json.dumps([
        {"company": "Broken", "source": "greenhouse", "slug": "broken"},
        {"company": "Acme", "source": "greenhouse", "slug": "acme"},
    ]), encoding="utf-8")
    monkeypatch.setattr(fetch_jobs, "COMPANIES", companies)
    monkeypatch.setattr(fetch_jobs, "SNAPSHOT_DIR", tmp_path / "snapshots")

    def fake_get_json(url):
        if "/broken/" in url:
            raise urllib.error.URLError("connection refused")
        return {"jobs": [_greenhouse_raw(7, "Software Engineering Intern", "Boston, MA"),
                         _greenhouse_raw(8, "Senior Engineer", "Boston, MA")]}

    monkeypatch.setattr(fetch_jobs, "_get_json", fake_get_json)
    out = _run(monkeypatch, fetch_jobs, "--source", "all")
    assert [f["company"] for f in out["failed"]] == ["Broken"]
    assert "connection refused" in out["failed"][0]["error"]
    assert [j["id"] for j in out["new"]] == ["greenhouse:acme:7"]
    row = _rows(tmp_db, "SELECT * FROM jobs WHERE id = 'greenhouse:acme:7'")[0]
    assert row["description"] == "Python & SQL" and row["location"] == "Boston, MA"
    snapshot = json.loads((tmp_path / "snapshots" / "greenhouse-acme.json").read_text(encoding="utf-8"))
    assert [j["id"] for j in snapshot] == ["greenhouse:acme:7"]
    assert not (tmp_path / "snapshots" / "greenhouse-broken.json").exists()


def test_committed_snapshots_load():
    jobs = fetch_jobs._load_snapshots("all")
    assert len(jobs) >= 20
    assert {j["company"] for j in jobs} == {"Formlabs", "Datadog", "Waymo", "Robinhood", "Figma", "Palantir"}
    assert all("&lt;" not in j["description"] and "<p>" not in j["description"] for j in jobs)


# extract_reqs

@pytest.mark.parametrize("pay,expected", [
    ({"min": 30, "max": 40, "period": "hour"}, "30-40 USD/hour"),
    ({"min": 1575, "max": 1950, "period": "week"}, "39-49 USD/hour"),
    ({"min": 10000, "max": None, "period": "month"}, "58 USD/hour"),
    ({"min": 104000, "max": 124800, "period": "year"}, "50-60 USD/hour"),
    ({"min": 40, "max": None, "period": "hour"}, "40 USD/hour"),
    ({"min": 40, "period": "hour"}, "40 USD/hour"),
    ({"min": 114400, "max": 114400, "period": "year"}, "55 USD/hour"),
    ({"min": 40, "max": 50, "period": "fortnight"}, None),
    ({"min": "40", "max": 50, "period": "hour"}, None),
    ({"min": 0, "max": None, "period": "hour"}, None),
    ("35-45 an hour", None),
    (None, None),
])
def test_hourly_text(pay, expected):
    assert extract_reqs._hourly_text(pay) == expected


def test_extract_sets_columns(tmp_db, monkeypatch):
    _insert_job("greenhouse:acme:1", "greenhouse")
    calls = []

    def fake_chat_json(system, user, *, mock, max_tokens):
        calls.append({"user": user, "max_tokens": max_tokens})
        return {
            "requirements": [
                {"skill_id": "SolidWorks", "level": 2, "importance": "must", "why": "designs parts",
                 "evidence_text": "Design parts in SolidWorks."},
                {"skill_id": "cobol", "level": 1, "importance": "nice", "why": "legacy", "evidence_text": "COBOL"},
            ],
            "sponsorship": None,
            "clearance": "us_person",
            "pay": {"min": 1575, "max": 1950, "period": "week"},
        }

    monkeypatch.setattr(_llm, "chat_json", fake_chat_json)
    out = _run(monkeypatch, extract_reqs, "--pending")
    assert out == {"processed": 1, "failed": [],
                   "dropped_skills": {"greenhouse:acme:1": [{"skill": "cobol", "reason": "not in taxonomy"}]}}
    assert calls[0]["max_tokens"] == 4000
    assert "TITLE: Mechanical Engineering Intern" in calls[0]["user"]
    row = _rows(tmp_db, "SELECT * FROM jobs WHERE id = 'greenhouse:acme:1'")[0]
    assert json.loads(row["requirements_json"]) == [
        {"skill_id": "solidworks", "level": 2, "importance": "must", "why": "designs parts",
         "evidence_text": "Design parts in SolidWorks."}]
    assert row["clearance"] == "us_person"
    assert row["pay"] == "39-49 USD/hour"
    assert row["sponsorship"] is None


def test_extract_coerces_bad_model_fields(tmp_db, monkeypatch):
    _insert_job("greenhouse:acme:1", "greenhouse")
    monkeypatch.setattr(_llm, "chat_json", lambda *a, **k: {
        "requirements": [{"skill_id": "python", "level": 1, "importance": "must", "why": "scripts"}],
        "sponsorship": "maybe", "clearance": "top secret", "pay": "competitive"})
    _run(monkeypatch, extract_reqs)
    row = _rows(tmp_db, "SELECT * FROM jobs")[0]
    assert (row["sponsorship"], row["clearance"], row["pay"]) == (None, "none", None)


def test_extract_skips_internal(tmp_db, mock_llm, monkeypatch):
    reqs = json.dumps([{"skill_id": "mysql", "level": 2, "importance": "must", "why": "owns the data layer",
                        "evidence_text": "owns the data layer"}])
    _insert_job("internal:r001", "internal", requirements_json=reqs, clearance="none", pay="35-45 USD/hour")
    _insert_job("greenhouse:acme:1", "greenhouse")
    before = dict(_rows(tmp_db, "SELECT * FROM jobs WHERE id = 'internal:r001'")[0])

    out = _run(monkeypatch, extract_reqs)
    assert out["processed"] == 1
    assert dict(_rows(tmp_db, "SELECT * FROM jobs WHERE id = 'internal:r001'")[0]) == before
    ats = _rows(tmp_db, "SELECT * FROM jobs WHERE id = 'greenhouse:acme:1'")[0]
    assert ats["pay"] == "30-40 USD/hour" and ats["clearance"] == "none"
    assert "react-native" in {r["skill_id"] for r in json.loads(ats["requirements_json"])}


def test_extract_model_error_goes_to_failed(tmp_db, monkeypatch):
    _insert_job("greenhouse:acme:1", "greenhouse")
    monkeypatch.setattr(_llm, "chat_json", lambda *a, **k: {"error": "model unreachable at http://x"})
    out = _run(monkeypatch, extract_reqs, "--pending")
    assert out == {"processed": 0, "failed": [{"job_id": "greenhouse:acme:1", "error": "model unreachable at http://x"}],
                   "dropped_skills": {}}
    assert _rows(tmp_db, "SELECT requirements_json FROM jobs")[0]["requirements_json"] is None


def test_extract_no_skills_stores_empty_list(tmp_db, monkeypatch):
    _insert_job("greenhouse:acme:1", "greenhouse")
    monkeypatch.setattr(_llm, "chat_json", lambda *a, **k: {
        "requirements": [{"skill_id": "cobol", "level": 1, "importance": "must", "why": "x"}],
        "sponsorship": None, "clearance": "none", "pay": None})
    out = _run(monkeypatch, extract_reqs, "--pending")
    assert out["processed"] == 0
    assert out["failed"] == [{"job_id": "greenhouse:acme:1", "error": "no taxonomy skills found"}]
    assert _rows(tmp_db, "SELECT requirements_json FROM jobs")[0]["requirements_json"] == "[]"
    assert _run(monkeypatch, extract_reqs, "--pending") == {"processed": 0, "failed": [], "dropped_skills": {}}


# list_jobs

def test_list_jobs_source_filter(tmp_db, monkeypatch):
    _seed(monkeypatch, "--with-test-jobs")
    _insert_job("internal:r001", "internal", requirements_json="[]")
    _insert_job("greenhouse:acme:1", "greenhouse")

    out = _run(monkeypatch, list_jobs, "--source", "internal")
    assert out["total"] == 1
    assert [j["id"] for j in out["jobs"]] == ["internal:r001"]
    assert out["jobs"][0]["extracted"] is True

    ats = _run(monkeypatch, list_jobs, "--source", "greenhouse")["jobs"][0]
    assert ats["extracted"] is False
    assert set(ats) == {"id", "source", "company", "title", "url", "location", "pay", "extracted"}

    everything = _run(monkeypatch, list_jobs, "--limit", "3")
    assert len(everything["jobs"]) == 3
    assert everything["total"] == 9


# apply

def test_apply_twice_reports_already_applied(tmp_db, monkeypatch):
    _seed(monkeypatch, "--with-test-jobs")
    first = _run(monkeypatch, apply, "--candidate", "c001", "--job", "test:acme:1")
    assert first["already_applied"] is False
    assert first["application"]["status"] == "submitted"
    assert first["application"]["job_id"] == "test:acme:1" and first["application"]["candidate_id"] == "c001"
    second = _run(monkeypatch, apply, "--candidate", "c001", "--job", "test:acme:1")
    assert second == {"application": first["application"], "already_applied": True}
    assert len(_rows(tmp_db, "SELECT * FROM applications")) == 1


def test_apply_unknown_job_raises(tmp_db, monkeypatch):
    _seed(monkeypatch, "--with-test-jobs")
    with pytest.raises(ValueError, match="job test:nope:9 not found"):
        _run(monkeypatch, apply, "--candidate", "c001", "--job", "test:nope:9")
    with pytest.raises(ValueError, match="candidate c999 not found"):
        _run(monkeypatch, apply, "--candidate", "c999", "--job", "test:acme:1")
    assert _rows(tmp_db, "SELECT * FROM applications") == []


# match_jobs

def test_match_jobs_hides_hidden(tmp_db, monkeypatch):
    _seed(monkeypatch, "--with-test-jobs")
    _insert_job("greenhouse:acme:1", "greenhouse", requirements_json="[]")

    out = _run(monkeypatch, match_jobs, "--candidate", "c001", "--limit", "20")
    shown = {m["job_id"]: m for m in out["matches"]}
    assert "test:cloudline:6" not in shown
    assert "greenhouse:acme:1" not in shown
    assert shown["test:acme:1"]["source"] == "test"
    assert shown["test:acme:1"]["pay"] == "35-45 USD/hour"
    assert {"job_id", "company", "title", "url", "score", "route", "flags", "gaps_text", "top_evidence",
            "category_scores", "pref_note", "source", "pay"} <= set(shown["test:acme:1"])
    assert shown["test:northwind:4"]["flags"] == ["clearance"]
    assert all(m["route"] not in ("hidden", "excluded") for m in out["matches"])

    stored = {r["job_id"]: r["route"] for r in _rows(tmp_db, "SELECT job_id, route FROM matches")}
    assert stored["test:cloudline:6"] == "hidden"
    assert "greenhouse:acme:1" not in stored
    assert len(stored) == 7


def test_match_jobs_limit_and_order(tmp_db, monkeypatch):
    _seed(monkeypatch, "--with-test-jobs")
    out = _run(monkeypatch, match_jobs, "--candidate", "c001", "--limit", "2")
    assert len(out["matches"]) == 2
    assert all(m["route"] == "match" for m in out["matches"])


def test_match_jobs_unknown_candidate_raises(tmp_db, monkeypatch):
    _seed(monkeypatch)
    with pytest.raises(ValueError, match="candidate c999 not found"):
        _run(monkeypatch, match_jobs, "--candidate", "c999")
