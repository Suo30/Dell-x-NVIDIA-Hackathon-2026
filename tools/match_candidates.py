"""Employer: rank all candidates against an approved role's private requirements (uses _match.evaluate).

Contract (MASTER_CONTEXT section 8):
    match_candidates.py --role ID [--limit 10]
    -> {"role_id", "job_id", "evaluated", "counts",
        "shortlist": [{"candidate_id", "name", "score", "route", "flags", "gaps_text", "top_evidence"}]}
Every candidate is evaluated against the role's internal job and upserted into matches.
counts is per route over all evaluated. The shortlist leaves out hidden and excluded
candidates and never carries pref_note (it reveals a student's private stance).
Owner: D
"""
import argparse
import json

import _cli
import _db
import _match

UPSERT = (
    "INSERT INTO matches (job_id, candidate_id, score, route, detail_json, created) "
    "VALUES (?, ?, ?, ?, ?, ?) "
    "ON CONFLICT(job_id, candidate_id) DO UPDATE SET "
    "score = excluded.score, route = excluded.route, detail_json = excluded.detail_json, "
    "created = excluded.created"
)
OFF_SHORTLIST = {"hidden", "excluded"}


def _load_job(conn, role_id):
    role = conn.execute("SELECT id, status FROM roles WHERE id = ?", (role_id,)).fetchone()
    if role is None:
        raise ValueError(f"role {role_id} not found")
    if role["status"] != "approved":
        raise ValueError(f"role {role_id} is {role['status']!r}; approve it first")
    job_id = f"internal:{role_id}"
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        raise RuntimeError(f"role {role_id} is approved but job {job_id} is missing; approve_role writes it")
    return _match.job_from_row(row)


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--role", required=True)
    p.add_argument("--limit", type=int, default=10)
    args = p.parse_args()
    if args.limit < 1:
        raise ValueError(f"--limit must be at least 1, got {args.limit}")

    conn = _db.connect()
    try:
        job = _load_job(conn, args.role)
        candidates = conn.execute("SELECT id, name, profile_json FROM candidates ORDER BY id").fetchall()
        counts = dict.fromkeys(_match.ROUTE_ORDER, 0)
        ranked = []
        created = _db.now()
        for cand in candidates:
            result = _match.evaluate(job, json.loads(cand["profile_json"]))
            detail = result["detail"]
            conn.execute(UPSERT, (job["id"], cand["id"], result["score"], result["route"],
                                  json.dumps(detail, ensure_ascii=False), created))
            counts[result["route"]] += 1
            if result["route"] not in OFF_SHORTLIST:
                key = _match.sort_key({"route": result["route"], "score": result["score"],
                                       "eager": result["eager"], "paid": job["paid"]})
                ranked.append((key, {
                    "candidate_id": cand["id"],
                    "name": cand["name"],
                    "score": result["score"],
                    "route": result["route"],
                    "flags": detail["flags"],
                    "gaps_text": detail["gaps_text"],
                    "top_evidence": _match.top_evidence(detail),
                }))
        conn.commit()
    finally:
        conn.close()

    ranked.sort(key=lambda pair: pair[0])
    return {"role_id": args.role, "job_id": job["id"], "evaluated": len(candidates), "counts": counts,
            "shortlist": [item for _, item in ranked[:args.limit]]}


if __name__ == "__main__":
    _cli.run(main)
