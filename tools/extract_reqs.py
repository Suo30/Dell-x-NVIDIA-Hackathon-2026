"""Candidate: job description -> requirements_json (6.4), sponsorship, clearance and pay via the model.

Contract (MASTER_CONTEXT section 8):
    extract_reqs.py [--pending] [--limit 20]
    -> {"processed": n, "failed": [{"job_id", "error"}], "dropped_skills": {job_id: [{"skill", "reason"}]}}

Never touches source='internal' jobs (approve_role copies their requirements from the role).
Pay is stored as hourly text ("39-49 USD/hour"), converted in code from the model's min/max/period.
A job with no taxonomy skills is stored as requirements_json "[]" so --pending skips it next time.
Commits after each job, so a crash midway keeps the finished work.
Owner: B
"""
import argparse
import json
import math

import _cli
import _db
import _llm
import _role
import _taxonomy
import aux_math

DESCRIPTION_CHARS = 6000
PER_HOUR = {"hour": 1, "week": 40, "month": 2080 / 12, "year": 2080}

SYSTEM = """You read one job description and list its requirements against a fixed
skills taxonomy, including soft skills. Only use skill_ids from the list below;
never invent one. Include soft skills (communication, teamwork, leadership, ...)
only when the posting states them, weighted the same as technical skills by importance.

Skill levels:
1 = used in a course or small project
2 = used in a job, internship or substantial project
3 = designed, led or owned something with it

Rules:
- importance is "must" for required or "minimum" qualifications and "nice" for preferred ones.
- sponsorship is false only if the posting says it will not sponsor visas or requires work
  authorization without sponsorship. It is true if it says it sponsors, and null if it says nothing.
- clearance is "clearance" if a security clearance is required (or must be obtainable). It is
  "us_person" if US citizenship, US person status or export control (ITAR/EAR) is required.
  Otherwise "none".
- pay is the stated pay in USD with its period, or null if not stated. Never guess.

Taxonomy:
{taxonomy}

Return JSON only, this exact shape:
{{"requirements": [
  {{"skill_id": "string", "level": 1, "importance": "must|nice", "why": "short reason",
    "evidence_text": "verbatim line from the posting"}}
 ],
 "sponsorship": true | false | null,
 "clearance": "none" | "us_person" | "clearance",
 "pay": {{"min": number, "max": number or null, "period": "hour|week|month|year"}} or null}}
If the posting states nothing matchable, return "requirements": []."""

_MOCK = {
    "requirements": [
        {"skill_id": "python", "level": 2, "importance": "must", "why": "owns backend scripts", "evidence_text": "2+ years of Python experience"},
        {"skill_id": "mysql", "level": 2, "importance": "must", "why": "owns the data layer", "evidence_text": "Experience with MySQL or similar relational databases"},
        {"skill_id": "react-native", "level": 1, "importance": "nice", "why": "mobile app is React Native", "evidence_text": "Familiarity with React Native a plus"},
        {"skill_id": "communication", "level": 2, "importance": "must", "why": "works directly with ops team", "evidence_text": "Strong written and verbal communication skills"},
        {"skill_id": "teamwork", "level": 2, "importance": "nice", "why": "small 2-engineer team", "evidence_text": "Comfortable collaborating closely in a small team"},
    ],
    "sponsorship": None,
    "clearance": "none",
    "pay": {"min": 30, "max": 40, "period": "hour"},
}


def _extract(job_row):
    system = SYSTEM.format(taxonomy=_taxonomy.prompt_block())
    user = (f"TITLE: {job_row['title']}\nCOMPANY: {job_row['company']}\n\n"
            f"DESCRIPTION:\n{job_row['description'][:DESCRIPTION_CHARS]}")
    out = _llm.chat_json(system, user, mock=_MOCK, max_tokens=4000)
    if "error" in out:
        return out
    if not isinstance(out.get("requirements"), list):
        return {"error": "model output missing requirements list"}
    return out


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _hourly_text(pay):
    # Model boundary: pay may be malformed; unparseable pay is unknown, never zero
    if not isinstance(pay, dict) or not _is_number(pay.get("min")) or aux_math.ge(0, pay["min"]):
        return None
    period = pay.get("period")
    if not isinstance(period, str) or period.strip().lower() not in PER_HOUR:
        return None
    hours = PER_HOUR[period.strip().lower()]
    lo = pay["min"] / hours
    if _is_number(pay.get("max")):
        return f"{lo:.0f}-{pay['max'] / hours:.0f} USD/hour"
    return f"{lo:.0f} USD/hour"


def _sponsorship(value):
    # Model boundary: anything but true, false or null is unknown, which never flags
    return value if value is None or isinstance(value, bool) else None


def _clearance(value):
    # Model boundary: an unknown clearance value counts as none
    return value if isinstance(value, str) and value in _role.CLEARANCE else "none"


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--pending", action="store_true", help="only jobs with requirements_json IS NULL")
    p.add_argument("--limit", type=int, default=20)
    args = p.parse_args()
    if args.limit < 1:
        raise ValueError(f"--limit must be at least 1, got {args.limit}")

    query = "SELECT id, title, company, description FROM jobs WHERE source != 'internal'"
    if args.pending:
        query += " AND requirements_json IS NULL"
    query += " ORDER BY first_seen, id LIMIT ?"

    processed, failed, dropped_skills = 0, [], {}
    conn = _db.connect()
    try:
        for row in conn.execute(query, (args.limit,)).fetchall():
            extracted = _extract(row)
            if "error" in extracted:
                failed.append({"job_id": row["id"], "error": extracted["error"]})
                continue
            requirements, dropped = _role.clean_requirements(extracted["requirements"], source=row["id"])
            if dropped:
                dropped_skills[row["id"]] = dropped
            # Model boundary: sponsorship, clearance and pay may be absent
            sponsorship = _sponsorship(extracted.get("sponsorship"))
            conn.execute(
                "UPDATE jobs SET requirements_json=?, sponsorship=?, clearance=?, pay=? WHERE id=?",
                (json.dumps(requirements, ensure_ascii=False),
                 None if sponsorship is None else int(sponsorship),
                 _clearance(extracted.get("clearance")),
                 _hourly_text(extracted.get("pay")),
                 row["id"]),
            )
            conn.commit()
            if requirements:
                processed += 1
            else:
                failed.append({"job_id": row["id"], "error": "no taxonomy skills found"})
    finally:
        conn.close()
    return {"processed": processed, "failed": failed, "dropped_skills": dropped_skills}


if __name__ == "__main__":
    _cli.run(main)
