"""Candidate: job description -> requirements_json (6.4) via the model.

Contract (MASTER_CONTEXT section 8):
    extract_reqs.py [--pending] [--limit 20]
    -> {"processed": n, "failed": [...]}
Owner: B
"""
import argparse
import json

import _cli
import _db
import _taxonomy
from _llm import chat_json

SYSTEM = """You read one job description and list its requirements against a fixed
skills taxonomy, including soft skills. Only use skill_ids from the list below;
never invent one. Include soft skills (communication, teamwork, leadership, ...)
whenever the posting states or clearly implies them, weighted the same as technical
skills by importance.

Skill levels:
1 = used in a course or small project
2 = used in a job, internship or substantial project
3 = designed, led or owned something with it

importance is "must" (required) or "nice" (desired/preferred).

Taxonomy:
{taxonomy}

Return JSON only, this exact shape:
{{"requirements": [
  {{"skill_id": "string", "level": 1, "importance": "must", "why": "short reason",
    "evidence_text": "verbatim line from the posting"}}
]}}
If the posting states nothing matchable, return {{"requirements": []}}."""

_MOCK = {
    "requirements": [
        {"skill_id": "python", "level": 2, "importance": "must", "why": "owns backend scripts", "evidence_text": "2+ years of Python experience"},
        {"skill_id": "mysql", "level": 2, "importance": "must", "why": "owns the data layer", "evidence_text": "Experience with MySQL or similar relational databases"},
        {"skill_id": "react_native", "level": 1, "importance": "nice", "why": "mobile app is React Native", "evidence_text": "Familiarity with React Native a plus"},
        {"skill_id": "communication", "level": 2, "importance": "must", "why": "works directly with ops team", "evidence_text": "Strong written and verbal communication skills"},
        {"skill_id": "teamwork", "level": 2, "importance": "nice", "why": "small 2-engineer team", "evidence_text": "Comfortable collaborating closely in a small team"},
    ]
}


def _extract(job_row):
    system = SYSTEM.format(taxonomy=_taxonomy.prompt_block())
    user = f"TITLE: {job_row['title']}\nCOMPANY: {job_row['company']}\n\nDESCRIPTION:\n{job_row['description']}"
    return chat_json(system, user, mock=_MOCK, max_tokens=3072)


def _resolve_requirements(raw_requirements):
    requirements = []
    for raw in raw_requirements:
        skill_id = _taxonomy.resolve(raw["skill_id"])
        if skill_id is None:
            continue
        if raw["importance"] not in ("must", "nice"):
            continue
        requirements.append({
            "skill_id": skill_id,
            "level": raw["level"],
            "importance": raw["importance"],
            "why": raw["why"],
            "evidence_text": raw["evidence_text"],
        })
    return requirements


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--pending", action="store_true", help="only jobs with requirements_json IS NULL")
    p.add_argument("--limit", type=int, default=20)
    args = p.parse_args()

    conn = _db.connect()
    query = "SELECT id, title, company, description FROM jobs"
    if args.pending:
        query += " WHERE requirements_json IS NULL"
    query += " LIMIT ?"
    rows = conn.execute(query, (args.limit,)).fetchall()

    processed = 0
    failed = []
    for row in rows:
        extracted = _extract(row)
        if "error" in extracted:
            failed.append({"job_id": row["id"], "error": extracted["error"]})
            continue
        requirements = _resolve_requirements(extracted["requirements"])
        conn.execute(
            "UPDATE jobs SET requirements_json = ? WHERE id = ?",
            (json.dumps(requirements), row["id"]),
        )
        processed += 1

    conn.commit()
    conn.close()
    return {"processed": processed, "failed": failed}


if __name__ == "__main__":
    _cli.run(main)
