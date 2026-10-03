"""Candidate: score every job with requirements against one candidate; store in matches.

Contract (MASTER_CONTEXT section 8):
    match_jobs.py --candidate ID [--limit 5]
    -> {"matches": [{"job_id", "company", "title", "url", "score", "route", "flags", "gaps_text", "top_evidence"}]}
Owner: B
"""
import argparse
import json

import _cli
import _db
import _match


def _top_evidence(detail_requirements):
    ranked = sorted(
        (r for r in detail_requirements if r["evidence"]),
        key=lambda r: (r["match"] != "strong", r["importance"] != "must"),
    )
    return ranked[0]["evidence"] if ranked else None


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--candidate", required=True)
    p.add_argument("--limit", type=int, default=5)
    args = p.parse_args()

    conn = _db.connect()
    candidate_row = conn.execute("SELECT profile_json FROM candidates WHERE id = ?", (args.candidate,)).fetchone()
    if candidate_row is None:
        return {"error": f"no candidate with id {args.candidate!r}"}
    profile = json.loads(candidate_row["profile_json"])

    job_rows = conn.execute(
        "SELECT id, source, company, title, url, location, description, "
        "requirements_json, sponsorship, clearance, pay, paid "
        "FROM jobs WHERE requirements_json IS NOT NULL"
    ).fetchall()

    rows = []
    for job_row in job_rows:
        job = {
            "requirements": json.loads(job_row["requirements_json"]),
            "sponsorship": None if job_row["sponsorship"] is None else bool(job_row["sponsorship"]),
            "clearance": job_row["clearance"],
            "location": job_row["location"],
            "company": job_row["company"],
            "pay": job_row["pay"],
            "paid": job_row["paid"],
        }
        result = _match.evaluate(job, profile)
        route, pref_note = _match.apply_prefs(result["route"], job, profile)
        if route == "excluded":
            continue
        result["detail"]["pref_note"] = pref_note

        conn.execute(
            "INSERT INTO matches (job_id, candidate_id, score, route, detail_json, created) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(job_id, candidate_id) DO UPDATE SET "
            "score = excluded.score, route = excluded.route, detail_json = excluded.detail_json, created = excluded.created",
            (job_row["id"], args.candidate, result["score"], route, json.dumps(result["detail"]), _db.now()),
        )

        eager = any(
            pref["company"].lower() == (job_row["company"] or "").lower() and pref["stance"] == "eager"
            for pref in profile["company_prefs"]
        )
        rows.append({
            "job_id": job_row["id"],
            "company": job_row["company"],
            "title": job_row["title"],
            "url": job_row["url"],
            "score": result["score"],
            "route": route,
            "flags": result["detail"]["flags"],
            "gaps_text": result["detail"]["gaps_text"],
            "top_evidence": _top_evidence(result["detail"]["requirements"]),
            "category_scores": result["detail"]["category_scores"],
            "pref_note": pref_note,
            "_sort": {"route": route, "score": result["score"], "eager": eager, "paid": bool(job_row["paid"])},
        })

    conn.commit()
    conn.close()

    rows.sort(key=lambda r: _match.sort_key(r["_sort"]))
    for row in rows:
        del row["_sort"]

    return {"matches": rows[:args.limit]}


if __name__ == "__main__":
    _cli.run(main)
