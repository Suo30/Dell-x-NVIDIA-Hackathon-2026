"""Candidate: list jobs in the DB, newest first.

Contract (MASTER_CONTEXT section 8):
    list_jobs.py [--limit 10] [--source internal]
    -> {"jobs": [{"id", "source", "company", "title", "url", "location", "pay", "extracted"}],
        "total": n}
total counts every job matching --source, not only the listed ones.
Owner: B
"""
import argparse

import _cli
import _db


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--source", help="greenhouse, lever, internal or test")
    args = p.parse_args()
    if args.limit < 1:
        raise ValueError(f"--limit must be at least 1, got {args.limit}")

    where, params = ("WHERE source = ?", (args.source,)) if args.source else ("", ())
    conn = _db.connect()
    try:
        rows = conn.execute(
            "SELECT id, source, company, title, url, location, pay, "
            "requirements_json IS NOT NULL AS extracted "
            f"FROM jobs {where} ORDER BY first_seen DESC, id LIMIT ?",
            (*params, args.limit),
        ).fetchall()
        total = conn.execute(f"SELECT COUNT(*) FROM jobs {where}", params).fetchone()[0]
    finally:
        conn.close()
    jobs = [{**dict(r), "extracted": bool(r["extracted"])} for r in rows]
    return {"jobs": jobs, "total": total}


if __name__ == "__main__":
    _cli.run(main)
