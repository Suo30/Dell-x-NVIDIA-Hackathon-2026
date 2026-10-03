import copy
import json
import random

import _match
import pytest
from conftest import ROOT

FIX = ROOT / "tests" / "fixtures"


@pytest.fixture
def profile():
    return json.loads((FIX / "profile.json").read_text(encoding="utf-8"))


@pytest.fixture
def jobs():
    return json.loads((FIX / "jobs.json").read_text(encoding="utf-8"))


def _req(match, importance="must", closable=None):
    if closable is None:
        closable = match == "partial" or (match == "none" and importance == "nice")
    return {"skill_id": "python", "importance": importance, "required": 2, "candidate_level": 0,
            "match": match, "evidence": None, "closable": closable}


def _job(**over):
    job = {"id": "test:x:1", "company": "Acme", "requirements": [], "sponsorship": None,
           "clearance": "none", "location": None, "pay": None, "paid": 0}
    job.update(over)
    return job


def _with_pref(profile, stance, min_pay=None, company="acme"):
    p = copy.deepcopy(profile)
    p["company_prefs"] = [{"company": company, "stance": stance, "min_pay": min_pay}]
    return p


# score

def test_score_all_strong():
    assert _match.score([_req("strong"), _req("strong", "nice")]) == 100.0


def test_score_mixed():
    reqs = [_req("strong"), _req("partial"), _req("none", "nice")]
    assert _match.score(reqs) == 60.0


def test_score_empty_raises():
    with pytest.raises(RuntimeError):
        _match.score([])


# per requirement

@pytest.mark.parametrize("have,required,importance,match,closable", [
    (2, 2, "must", "strong", False),
    (3, 2, "nice", "strong", False),
    (1, 2, "must", "partial", True),
    (None, 1, "must", "none", False),
    (None, 1, "nice", "none", True),
    (1, 3, "must", "none", False),
    (1, 3, "nice", "none", True),
])
def test_requirement_match(profile, have, required, importance, match, closable):
    p = copy.deepcopy(profile)
    p["skills"] = [s for s in p["skills"] if s["skill_id"] != "docker"]
    if have is not None:
        p["skills"].append({"skill_id": "docker", "level": have,
                            "evidence": [{"source": "chat", "text": "used Docker"}]})
    job = _job(requirements=[{"skill_id": "docker", "level": required, "importance": importance}])
    r = _match.evaluate(job, p)["detail"]["requirements"][0]
    assert (r["match"], r["closable"]) == (match, closable)
    assert r["candidate_level"] == (have or 0)
    assert r["evidence"] == ("used Docker" if have else None)


# route

def test_route_match_at_70():
    assert _match.route(70.0, [_req("strong")], []) == "match"


def test_route_stretch_closable():
    assert _match.route(60.0, [_req("strong"), _req("partial")], []) == "stretch"


def test_route_hidden_must_none():
    assert _match.route(60.0, [_req("strong"), _req("none")], []) == "hidden"


def test_route_stretch_boundary():
    reqs = [_req("partial")]
    assert _match.route(50.0, reqs, []) == "stretch"
    assert _match.route(49.9, reqs, []) == "hidden"


def test_route_flag_beats_score():
    assert _match.route(100.0, [_req("strong")], ["sponsorship"]) == "review"


# flags

def test_sponsorship_none_never_flags(profile):
    assert "sponsorship" not in _match.flags(_job(sponsorship=None), profile)


@pytest.mark.parametrize("needs,job_sponsors,flagged", [
    (True, False, True), (True, True, False), (False, False, False)])
def test_sponsorship_flag(profile, needs, job_sponsors, flagged):
    profile["visa"]["needs_sponsorship"] = needs
    assert ("sponsorship" in _match.flags(_job(sponsorship=job_sponsors), profile)) is flagged


@pytest.mark.parametrize("clearance,us_person,flagged", [
    ("us_person", False, True), ("clearance", False, True),
    ("us_person", True, False), ("none", False, False), (None, False, False)])
def test_clearance_flag(profile, clearance, us_person, flagged):
    profile["visa"]["us_person"] = us_person
    assert ("clearance" in _match.flags(_job(clearance=clearance), profile)) is flagged


@pytest.mark.parametrize("location,remote,flagged", [
    ("Austin, TX", "hybrid", True),
    ("Austin, TX", "any", False),
    ("Boston, MA", "onsite", False),
    ("Austin, TX (hybrid)", "onsite", False),
    ("Remote (US)", "onsite", False),
    (None, "hybrid", False),
    ("", "hybrid", False),
])
def test_location_flag(profile, location, remote, flagged):
    profile["location"]["remote"] = remote
    assert ("location" in _match.flags(_job(location=location), profile)) is flagged


def test_flag_order(profile):
    job = _job(sponsorship=False, clearance="us_person", location="Austin, TX")
    assert _match.flags(job, profile) == ["sponsorship", "clearance", "location"]


# prefs

def test_never_excludes(profile):
    assert _match.apply_prefs("match", _job(), _with_pref(profile, "never"))[0] == "excluded"


def test_no_pref_unchanged(profile):
    assert _match.apply_prefs("match", _job(), profile) == ("match", None, False)


def test_only_strong_offer_pay_unknown(profile):
    out = _match.apply_prefs("match", _job(pay=None), _with_pref(profile, "only_strong_offer", 30))
    assert out == ("review", "only_strong_offer: pay not stated", False)


def test_only_strong_offer_pay_ok(profile):
    out = _match.apply_prefs("stretch", _job(pay="35-45 USD/hour"),
                             _with_pref(profile, "only_strong_offer", 30))
    assert out == ("stretch", None, False)


def test_only_strong_offer_min_pay_null(profile):
    out = _match.apply_prefs("match", _job(pay="35 USD/hour"), _with_pref(profile, "only_strong_offer"))
    assert out[0] == "match"


def test_only_strong_offer_below_min(profile):
    out = _match.apply_prefs("match", _job(pay="35-45 USD/hour"),
                             _with_pref(profile, "only_strong_offer", 40))
    assert out == ("review", "only_strong_offer: pay 35 below minimum 40", False)


def test_only_strong_offer_leaves_hidden(profile):
    out = _match.apply_prefs("hidden", _job(pay=None), _with_pref(profile, "only_strong_offer", 40))
    assert out[0] == "hidden"


def test_eager(profile):
    assert _match.apply_prefs("stretch", _job(company="ACME"), _with_pref(profile, "eager")) == \
        ("stretch", None, True)


def test_pref_other_company_ignored(profile):
    out = _match.apply_prefs("match", _job(company="Globex"), _with_pref(profile, "never"))
    assert out[0] == "match"


def test_pref_note_in_detail(profile, jobs):
    p = _with_pref(profile, "only_strong_offer", 45)
    out = _match.evaluate(jobs[0], p)
    assert out["route"] == "review"
    assert out["detail"]["pref_note"] == "only_strong_offer: pay 35 below minimum 45"


# pay

def test_parse_hourly():
    assert abs(_match.parse_hourly("120,000 USD/year") - 120000 / 2080) < 1e-6
    assert _match.parse_hourly("35-45 USD/hour") == 35.0
    assert _match.parse_hourly("$27.50/hr") == 27.5
    assert _match.parse_hourly("competitive") is None
    assert _match.parse_hourly(None) is None


# sort

def test_sort_key():
    rows = [
        {"id": "a", "route": "match", "score": 90.0, "eager": False, "paid": 0},
        {"id": "b", "route": "match", "score": 80.0, "eager": True, "paid": 0},
        {"id": "c", "route": "match", "score": 80.0, "eager": False, "paid": 1},
        {"id": "d", "route": "match", "score": 80.0, "eager": False, "paid": 0},
        {"id": "e", "route": "stretch", "score": 99.0, "eager": True, "paid": 1},
        {"id": "f", "route": "review", "score": 100.0, "eager": False, "paid": 0},
        {"id": "g", "route": "hidden", "score": 40.0, "eager": False, "paid": 0},
        {"id": "h", "route": "excluded", "score": 100.0, "eager": True, "paid": 1},
    ]
    shuffled = rows[:]
    random.Random(1).shuffle(shuffled)
    assert [r["id"] for r in sorted(shuffled, key=_match.sort_key)] == list("abcdefgh")


# gaps and evidence

def test_gap_text():
    assert _match.gap_text("MySQL", 2, 1) == "The evidence did not show MySQL at level 2 (has level 1)"
    assert _match.gap_text("MySQL", 2, 0) == "The evidence did not show MySQL at level 2 (no evidence found)"


def test_gaps_only_for_non_strong(profile, jobs):
    for job in jobs:
        out = _match.evaluate(job, profile)
        reqs = out["detail"]["requirements"]
        assert len(out["detail"]["gaps_text"]) == sum(r["match"] != "strong" for r in reqs)
        for line in out["detail"]["gaps_text"]:
            assert "lack" not in line.lower()


def test_top_evidence_order():
    detail = {"requirements": [
        {**_req("strong", "nice"), "evidence": "nice one"},
        {**_req("strong", "must"), "evidence": "must one"},
        {**_req("strong", "must"), "evidence": None},
        {**_req("partial", "must"), "evidence": "partial"},
        {**_req("strong", "must"), "evidence": "must one"},
    ]}
    assert _match.top_evidence(detail) == ["must one", "nice one"]
    assert _match.top_evidence(detail, n=1) == ["must one"]


def test_empty_requirements_raises(profile):
    with pytest.raises(RuntimeError, match="test:x:1"):
        _match.evaluate(_job(), profile)


def test_bad_importance_raises(profile):
    job = _job(requirements=[{"skill_id": "python", "level": 1, "importance": "maybe"}])
    with pytest.raises(RuntimeError, match="maybe"):
        _match.evaluate(job, profile)


# fixtures end to end

def test_fixture_jobs_vs_jordan(profile, jobs):
    out = [_match.evaluate(j, profile) for j in jobs]
    assert out[0]["route"] in ("match", "stretch")
    assert out[1]["route"] == "review" and "sponsorship" in out[1]["detail"]["flags"]
    assert profile["location"]["remote"] != "any"
    assert "location" in out[2]["detail"]["flags"]
    assert "clearance" in out[3]["detail"]["flags"]
    assert out[4]["route"] == "match"
    assert out[5]["route"] == "hidden"
    assert jobs[6]["paid"] == 1 and jobs[6]["company"] != jobs[0]["company"]
    for o in out:
        assert set(o) == {"score", "route", "eager", "detail"}
        assert set(o["detail"]) == {"requirements", "flags", "pref_note", "gaps_text"}


@pytest.mark.parametrize("stored,expected", [(None, None), (0, False), (1, True)])
def test_job_from_row(tmp_db, profile, jobs, stored, expected):
    import _db

    conn = _db.connect()
    try:
        conn.execute(
            "INSERT INTO jobs (id, source, company, title, location, requirements_json, sponsorship, "
            "clearance, pay, paid, first_seen) VALUES ('test:acme:1', 'test', 'Acme', 'T', 'Boston, MA', "
            "?, ?, 'none', '35-45 USD/hour', 1, 'now')",
            (json.dumps(jobs[0]["requirements"]), stored),
        )
        row = conn.execute("SELECT * FROM jobs").fetchone()
    finally:
        conn.close()
    job = _match.job_from_row(row)
    assert job == {"id": "test:acme:1", "requirements": jobs[0]["requirements"], "sponsorship": expected,
                   "clearance": "none", "location": "Boston, MA", "company": "Acme",
                   "pay": "35-45 USD/hour", "paid": 1}
    assert job["sponsorship"] is expected
    _match.evaluate(job, profile)


def test_job_from_row_unextracted_raises(tmp_db):
    import _db

    conn = _db.connect()
    try:
        conn.execute("INSERT INTO jobs (id, source, first_seen) VALUES ('test:x:1', 'test', 'now')")
        row = conn.execute("SELECT * FROM jobs").fetchone()
    finally:
        conn.close()
    with pytest.raises(RuntimeError, match="test:x:1"):
        _match.job_from_row(row)
