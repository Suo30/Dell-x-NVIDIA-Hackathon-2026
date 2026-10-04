"""Init the DB from db/schema.sql and load data/candidates/*.json (optionally test jobs).
Owner: D

    seed_db.py [--reset] [--with-test-jobs]

--reset deletes DB_PATH first. --with-test-jobs loads tests/fixtures/jobs.json
(source "test"); demo_reset.sh never passes it. Job snapshots are loaded by
fetch_jobs.py --offline, not here.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import _cli
import _config
import _db
import _profile

TEST_JOBS = _config.REPO / "tests" / "fixtures" / "jobs.json"


def load_candidates(cand_dir):
    profiles = []
    for path in sorted(cand_dir.glob("*.json")):
        profile = json.loads(path.read_text(encoding="utf-8"))
        _profile.validate(profile, path.name)
        if profile["id"] != path.stem:
            raise ValueError(f"{path.name}: id {profile['id']!r} does not match the file name")
        profiles.append(profile)
    return profiles


def _insert_candidates(conn, profiles):
    now = _db.now()
    for p in profiles:
        conn.execute(
            "INSERT OR REPLACE INTO candidates (id, name, profile_json, consent_auto, synthetic, updated)"
            " VALUES (?, ?, ?, 1, 1, ?)",
            (p["id"], p["name"], json.dumps(p, ensure_ascii=False), now),
        )


def _insert_test_jobs(conn, jobs):
    now = _db.now()
    for j in jobs:
        sponsorship = None if j["sponsorship"] is None else int(j["sponsorship"])
        conn.execute(
            "INSERT OR IGNORE INTO jobs (id, source, company, title, url, location, description,"
            " requirements_json, sponsorship, clearance, pay, paid, first_seen)"
            " VALUES (?, 'test', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (j["id"], j["company"], j["title"], j["url"], j["location"], j["description"],
             json.dumps(j["requirements"], ensure_ascii=False), sponsorship, j["clearance"],
             j["pay"], j["paid"], now),
        )


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--reset", action="store_true", help="delete DB_PATH first")
    p.add_argument("--with-test-jobs", action="store_true", help="also load tests/fixtures/jobs.json")
    args = p.parse_args()

    path = _config.DB_PATH
    if args.reset:
        path.unlink(missing_ok=True)
    profiles = load_candidates(_config.DATA_DIR / "candidates")
    jobs = json.loads(TEST_JOBS.read_text(encoding="utf-8")) if args.with_test_jobs else []

    conn = _db.connect()
    try:
        _insert_candidates(conn, profiles)
        _insert_test_jobs(conn, jobs)
        conn.commit()
    finally:
        conn.close()
    return {"db": str(path), "candidates": len(profiles), "jobs": len(jobs)}


if __name__ == "__main__":
    _cli.run(main)
