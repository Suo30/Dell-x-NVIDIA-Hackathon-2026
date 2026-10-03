"""Candidate: score every job with requirements against one candidate; store in matches.

Contract (MASTER_CONTEXT section 8):
    match_jobs.py --candidate ID [--limit 5]
    -> {"matches": [{"job_id", "source", "company", "title", "url", "pay", "score", "route", "flags",
                     "gaps_text", "top_evidence", "category_scores", "pref_note"}]}

Every evaluated job is upserted into matches, including hidden and excluded ones.
The returned list leaves hidden and excluded out, so --limit is spent on real options.
Owner: B
"""
import argparse
import json

import _cli
import _db
import _match
import _taxonomy

NOT_SHOWN = {"hidden", "excluded"}


def _category_scores(detail_requirements):
    """Split the weighted score (7.2) by taxonomy category: soft vs technical.
    Bonus breakdown, not part of the frozen 6.5 schema."""
    skill_category = {s["id"]: s["category"] for s in _taxonomy.load()}
    groups = {"technical": [], "soft": []}
    for req in detail_requirements:
        bucket = "soft" if skill_category[req["skill_id"]] == "soft" else "technical"
        groups[bucket].append(req)
    return {name: _match.score(reqs) for name, reqs in groups.items() if reqs}


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--candidate", required=True)
    p.add_argument("--limit", type=int, default=5)
    args = p.parse_args()
    if args.limit < 1:
        raise ValueError(f"--limit must be at least 1, got {args.limit}")

    conn = _db.connect()
    try:
        candidate_row = conn.execute("SELECT profile_json FROM candidates WHERE id = ?", (args.candidate,)).fetchone()
        if candidate_row is None:
            raise ValueError(f"candidate {args.candidate} not found")
        profile = json.loads(candidate_row["profile_json"])

        job_rows = conn.execute(
            "SELECT id, source, company, title, url, location, requirements_json, sponsorship, clearance, pay, paid "
            "FROM jobs WHERE requirements_json IS NOT NULL AND requirements_json != '[]'"
        ).fetchall()

        rows = []
        for job_row in job_rows:
            result = _match.evaluate(_match.job_from_row(job_row), profile)
            conn.execute(
                "INSERT INTO matches (job_id, candidate_id, score, route, detail_json, created) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(job_id, candidate_id) DO UPDATE SET "
                "score = excluded.score, route = excluded.route, detail_json = excluded.detail_json, "
                "created = excluded.created",
                (job_row["id"], args.candidate, result["score"], result["route"],
                 json.dumps(result["detail"], ensure_ascii=False), _db.now()),
            )
            if result["route"] not in NOT_SHOWN:
                rows.append({
                    "job_id": job_row["id"],
                    "source": job_row["source"],
                    "company": job_row["company"],
                    "title": job_row["title"],
                    "url": job_row["url"],
                    "pay": job_row["pay"],
                    "score": result["score"],
                    "route": result["route"],
                    "flags": result["detail"]["flags"],
                    "gaps_text": result["detail"]["gaps_text"],
                    "top_evidence": _match.top_evidence(result["detail"]),
                    "category_scores": _category_scores(result["detail"]["requirements"]),
                    "pref_note": result["detail"]["pref_note"],
                    "_sort": {"route": result["route"], "score": result["score"],
                              "eager": result["eager"], "paid": bool(job_row["paid"])},
                })
        conn.commit()
    finally:
        conn.close()

    rows.sort(key=lambda r: (_match.sort_key(r["_sort"]), r["job_id"]))
    for row in rows:
        del row["_sort"]
    return {"matches": rows[:args.limit]}


if __name__ == "__main__":
    _cli.run(main)
