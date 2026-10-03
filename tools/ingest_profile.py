"""Candidate: resume text + notes -> taxonomy-mapped profile (6.2), stored in candidates.

Contract (MASTER_CONTEXT section 8):
    ingest_profile.py --name "X" --text-file PATH [--notes "..."]
    -> {"candidate_id", "skills_found", "profile"}
Owner: D
"""
import argparse
import json

import _cli
import _db
import _llm
import _taxonomy

SYSTEM = """You turn a student's resume (plus optional chat notes) into a structured
profile for a career-matching tool. Only use skill_ids from the taxonomy list below;
never invent a skill_id that is not in it. Skip anything you cannot map.

Skill levels:
1 = used in a course or small project
2 = used in a job, internship or substantial project
3 = designed, led or owned something with it

Taxonomy:
{taxonomy}

Return JSON only, this exact shape:
{{
  "school": "string or null",
  "program": "string or null",
  "visa": {{"status": "string or null", "needs_sponsorship": bool, "us_person": bool}},
  "availability": {{"start": "string or null, e.g. 2027-01", "type": "string or null, e.g. co-op"}},
  "location": {{"preferred": ["city, state"], "remote": "any|remote|hybrid|onsite"}},
  "skills": [{{"skill_id": "string", "level": 1, "evidence": "verbatim line from resume or notes"}}],
  "bullets": ["verbatim resume bullet"]
}}
If a fact is not stated, use null (or an empty list/false), never guess."""

_MOCK = {
    "school": "Northeastern University",
    "program": "MS Mechanical Engineering",
    "visa": {"status": "F-1", "needs_sponsorship": True, "us_person": False},
    "availability": {"start": "2027-01", "type": "co-op"},
    "location": {"preferred": ["Boston, MA"], "remote": "any"},
    "skills": [
        {"skill_id": "python", "level": 2, "evidence": "Built a Python data pipeline that logged sensor readings from 12 test rigs into MySQL"},
        {"skill_id": "mysql", "level": 2, "evidence": "Built a Python data pipeline that logged sensor readings from 12 test rigs into MySQL"},
        {"skill_id": "solidworks", "level": 3, "evidence": "Designed a SolidWorks fixture that cut assembly time by 30%"},
        {"skill_id": "matlab", "level": 1, "evidence": "SKILLS: Python, MySQL, SolidWorks, MATLAB, React Native, Git"},
        {"skill_id": "react_native", "level": 1, "evidence": "React Native app for tracking lab equipment checkouts (course project)"},
        {"skill_id": "git", "level": 1, "evidence": "SKILLS: Python, MySQL, SolidWorks, MATLAB, React Native, Git"},
    ],
    "bullets": [
        "Built a Python data pipeline that logged sensor readings from 12 test rigs into MySQL",
        "Designed a SolidWorks fixture that cut assembly time by 30%",
        "React Native app for tracking lab equipment checkouts (course project)",
    ],
}


def _next_candidate_id(conn):
    rows = conn.execute("SELECT id FROM candidates").fetchall()
    numbers = [int(row["id"][1:]) for row in rows if row["id"][1:].isdigit()]
    return f"c{(max(numbers) + 1) if numbers else 1:03d}"


def _extract(resume_text, notes):
    system = SYSTEM.format(taxonomy=_taxonomy.prompt_block())
    user = f"RESUME:\n{resume_text}"
    if notes:
        user += f"\n\nADDITIONAL NOTES FROM CHAT:\n{notes}"
    return _llm.chat_json(system, user, mock=_MOCK, max_tokens=3072)


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--name", required=True)
    p.add_argument("--text-file", required=True)
    p.add_argument("--notes", default="")
    args = p.parse_args()

    resume_text = open(args.text_file, encoding="utf-8").read()
    extracted = _extract(resume_text, args.notes)
    if "error" in extracted:
        return {"error": extracted["error"]}

    skills = []
    for raw_skill in extracted["skills"]:
        skill_id = _taxonomy.resolve(raw_skill["skill_id"])
        if skill_id is None:
            continue
        skills.append({
            "skill_id": skill_id,
            "level": raw_skill["level"],
            "evidence": [{"source": "resume", "text": raw_skill["evidence"]}],
        })

    conn = _db.connect()
    candidate_id = _next_candidate_id(conn)
    profile = {
        "id": candidate_id,
        "name": args.name,
        "school": extracted["school"],
        "program": extracted["program"],
        "visa": extracted["visa"],
        "availability": extracted["availability"],
        "location": extracted["location"],
        "skills": skills,
        "bullets": [{"id": f"b{i + 1}", "text": text} for i, text in enumerate(extracted["bullets"])],
        "company_prefs": [],
        "notes": [args.notes] if args.notes else [],
    }
    conn.execute(
        "INSERT INTO candidates (id, name, profile_json, consent_auto, synthetic, updated) "
        "VALUES (?, ?, ?, 1, 0, ?)",
        (candidate_id, args.name, json.dumps(profile), _db.now()),
    )
    conn.commit()
    conn.close()

    return {"candidate_id": candidate_id, "skills_found": len(skills), "profile": profile}


if __name__ == "__main__":
    _cli.run(main)
