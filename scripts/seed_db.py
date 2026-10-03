"""Init the DB from db/schema.sql, load data/candidates/*.json and data/snapshots/*.json.
Owner: D
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import _cli  # noqa: E402
import _config  # noqa: E402
import _db  # noqa: E402


def _load_candidates(conn):
    count = 0
    for path in sorted((_config.DATA_DIR / "candidates").glob("*.json")):
        # Boundary: synthetic profile files are hand/script-authored external input.
        profile = json.loads(path.read_text(encoding="utf-8"))
        conn.execute(
            "INSERT OR IGNORE INTO candidates (id, name, profile_json, consent_auto, synthetic, updated) "
            "VALUES (?, ?, ?, 1, 1, ?)",
            (profile["id"], profile["name"], json.dumps(profile), _db.now()),
        )
        count += 1
    return count


def _load_snapshots(conn):
    count = 0
    for path in sorted((_config.DATA_DIR / "snapshots").glob("*.json")):
        # Boundary: snapshots are offline copies of fetched ATS API responses.
        jobs = json.loads(path.read_text(encoding="utf-8"))
        for job in jobs:
            conn.execute(
                "INSERT OR IGNORE INTO jobs "
                "(id, source, company, title, url, location, description, role_id, "
                "requirements_json, sponsorship, clearance, pay, paid, first_seen, notified) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
                (
                    job["id"], job["source"], job["company"], job["title"], job["url"],
                    job.get("location"), job.get("description"), job.get("role_id"),
                    job.get("requirements_json"), job.get("sponsorship"), job.get("clearance"),
                    job.get("pay"), job.get("paid", 0), _db.now(),
                ),
            )
            count += 1
    return count


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--reset", action="store_true", help="delete DB_PATH first")
    args = p.parse_args()

    if args.reset and _config.DB_PATH.exists():
        _config.DB_PATH.unlink()

    conn = _db.connect()
    candidates_loaded = _load_candidates(conn)
    jobs_loaded = _load_snapshots(conn)
    conn.commit()
    conn.close()
    return {"candidates_loaded": candidates_loaded, "jobs_loaded": jobs_loaded}


if __name__ == "__main__":
    _cli.run(main)
