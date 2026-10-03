import copy
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys

import _match
import _profile
import _taxonomy
import pytest
import seed_db
from conftest import ROOT

CAND_DIR = ROOT / "data" / "candidates"
GEN = ROOT / "scripts" / "gen_candidates.py"


def _profiles():
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(CAND_DIR.glob("*.json"))]


def _jobs():
    return json.loads((ROOT / "tests" / "fixtures" / "jobs.json").read_text(encoding="utf-8"))


def _gen(out):
    res = subprocess.run([sys.executable, str(GEN), "--out", str(out)],
                         capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(res.stdout)


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# generator

def test_gen_deterministic(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    assert _gen(a)["written"] == 28
    _gen(b)
    names = sorted(p.name for p in a.glob("*.json"))
    assert names == [f"c{i:03d}.json" for i in range(3, 31)]
    for n in names:
        assert (a / n).read_bytes() == (b / n).read_bytes()


def test_committed_files_match_generator(tmp_path):
    _gen(tmp_path)
    for p in tmp_path.glob("*.json"):
        assert p.read_bytes() == (CAND_DIR / p.name).read_bytes(), f"{p.name} is stale, rerun gen_candidates"


def test_gen_leaves_heroes_alone(tmp_path):
    shutil.copytree(CAND_DIR, tmp_path / "c")
    before = {n: _digest(tmp_path / "c" / n) for n in ("c001.json", "c002.json")}
    _gen(tmp_path / "c")
    assert {n: _digest(tmp_path / "c" / n) for n in before} == before


def test_c001_is_jordan_fixture():
    fixture = json.loads((ROOT / "tests" / "fixtures" / "profile.json").read_text(encoding="utf-8"))
    assert json.loads((CAND_DIR / "c001.json").read_text(encoding="utf-8")) == fixture


def test_all_profiles_valid_and_ids_match():
    paths = sorted(CAND_DIR.glob("*.json"))
    assert [p.stem for p in paths] == [f"c{i:03d}" for i in range(1, 31)]
    for p in paths:
        profile = json.loads(p.read_text(encoding="utf-8"))
        _profile.validate(profile, p.name)
        assert profile["id"] == p.stem


# spread

def test_spread_visa_and_chat():
    ps = _profiles()
    assert sum(p["visa"]["status"] == "F-1" and p["visa"]["needs_sponsorship"] for p in ps) >= 10
    assert sum(p["visa"]["us_person"] for p in ps) >= 5
    chat_only = [p for p in ps
                 if any(all(e["source"] == "chat" for e in s["evidence"]) for s in p["skills"])]
    assert len(chat_only) >= 8


def test_spread_company_prefs():
    ps = _profiles()
    assert sum(bool(p["company_prefs"]) for p in ps) >= 6
    acme = {x["stance"] for p in ps for x in p["company_prefs"] if x["company"].lower() == "acme"}
    assert acme == {"eager", "neutral", "only_strong_offer", "never"}


def test_spread_skill_coverage():
    used = {s["skill_id"] for p in _profiles() for s in p["skills"]}
    assert len(used) >= 0.8 * len(_taxonomy.load())


def test_spread_routes():
    ps, jobs = _profiles(), _jobs()
    demo = [_match.evaluate(jobs[0], p) for p in ps]
    assert sum(e["route"] == "match" for e in demo) >= 5
    assert sum(e["route"] == "stretch" for e in demo) >= 3
    no_sponsor = [(p, _match.evaluate(jobs[1], p)) for p in ps]
    f1_review = [p for p, e in no_sponsor if p["visa"]["status"] == "F-1"
                 and e["route"] == "review" and "sponsorship" in e["detail"]["flags"]]
    assert len(f1_review) >= 2


# seed_db

def _seed(monkeypatch, *flags):
    monkeypatch.setattr(sys, "argv", ["seed_db.py", "--reset", *flags])
    return seed_db.main()


def _rows(db, sql):
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def test_seed_twice(tmp_db, monkeypatch):
    out = _seed(monkeypatch)
    assert out == {"db": str(tmp_db), "candidates": 30, "jobs": 0}
    _seed(monkeypatch)
    rows = _rows(tmp_db, "SELECT * FROM candidates")
    assert len(rows) == 30
    assert all(r["synthetic"] == 1 and r["consent_auto"] == 1 for r in rows)
    assert _rows(tmp_db, "SELECT count(*) AS n FROM jobs")[0]["n"] == 0


def test_seed_profile_json_round_trips(tmp_db, monkeypatch):
    _seed(monkeypatch)
    for r in _rows(tmp_db, "SELECT id, profile_json FROM candidates"):
        on_disk = json.loads((CAND_DIR / f"{r['id']}.json").read_text(encoding="utf-8"))
        assert json.loads(r["profile_json"]) == on_disk


def test_bad_level_names_file_and_field(tmp_path):
    profile = json.loads((CAND_DIR / "c001.json").read_text(encoding="utf-8"))
    profile["skills"][0]["level"] = 4
    (tmp_path / "c001.json").write_text(json.dumps(profile), encoding="utf-8")
    with pytest.raises(ValueError) as e:
        seed_db.load_candidates(tmp_path)
    assert "c001.json" in str(e.value) and "skills[0].level" in str(e.value)


def test_id_must_match_filename(tmp_path):
    shutil.copy(CAND_DIR / "c001.json", tmp_path / "c099.json")
    with pytest.raises(ValueError, match="c099.json"):
        seed_db.load_candidates(tmp_path)


@pytest.mark.parametrize("mutate,field", [
    (lambda p: p.pop("visa"), "visa"),
    (lambda p: p["visa"].pop("us_person"), "visa.us_person"),
    (lambda p: p["location"].update(remote="sometimes"), "location.remote"),
    (lambda p: p["company_prefs"].append({"company": "X", "stance": "maybe", "min_pay": None}),
     "company_prefs[0].stance"),
    (lambda p: p["skills"][0].update(skill_id="cobol"), "skills[0].skill_id"),
    (lambda p: p["skills"][0]["evidence"].clear(), "skills[0].evidence"),
    (lambda p: p["skills"][0]["evidence"][0].update(source="linkedin"), "skills[0].evidence[0].source"),
    (lambda p: p["bullets"].append({"id": "b1", "text": "dup"}), "bullets[3].id"),
])
def test_validate_rejects(mutate, field):
    profile = json.loads((CAND_DIR / "c001.json").read_text(encoding="utf-8"))
    mutate(profile)
    with pytest.raises(ValueError) as e:
        _profile.validate(profile, "c001.json")
    assert str(e.value).startswith(f"c001.json: {field} ")


# integration

def _job_from_row(r):
    return {"id": r["id"], "company": r["company"], "location": r["location"], "pay": r["pay"],
            "paid": r["paid"], "clearance": r["clearance"],
            "sponsorship": None if r["sponsorship"] is None else bool(r["sponsorship"]),
            "requirements": json.loads(r["requirements_json"])}


def test_seed_with_test_jobs_and_match(tmp_db, monkeypatch):
    out = _seed(monkeypatch, "--with-test-jobs")
    assert out["jobs"] == len(_jobs())
    jobs = {r["id"]: _job_from_row(r) for r in _rows(tmp_db, "SELECT * FROM jobs")}
    assert all(j["id"].startswith("test:") for j in jobs.values())
    cands = [json.loads(r["profile_json"]) for r in _rows(tmp_db, "SELECT profile_json FROM candidates")]
    demo, no_sponsor = jobs[_jobs()[0]["id"]], jobs[_jobs()[1]["id"]]
    routes = [_match.evaluate(demo, p)["route"] for p in cands]
    assert "match" in routes and "stretch" in routes
    flagged = [e for e in (_match.evaluate(no_sponsor, p) for p in cands)
               if e["route"] == "review" and "sponsorship" in e["detail"]["flags"]]
    assert flagged


def test_chat_evidence_raises_c002_score():
    c002 = json.loads((CAND_DIR / "c002.json").read_text(encoding="utf-8"))
    resume_only = copy.deepcopy(c002)
    for s in resume_only["skills"]:
        s["evidence"] = [e for e in s["evidence"] if e["source"] != "chat"]
    resume_only["skills"] = [s for s in resume_only["skills"] if s["evidence"]]
    job = _jobs()[0]
    assert _match.evaluate(job, resume_only)["score"] < _match.evaluate(job, c002)["score"]
