"""Candidate: resume text + notes -> taxonomy-mapped profile (6.2), stored in candidates.

Contract (MASTER_CONTEXT section 8):
    ingest_profile.py --name "X" --text-file PATH [--notes "..."]
    -> {"candidate_id", "skills_found", "profile", "missing", "dropped_skills"}
missing lists profile fields the resume did not state (ask the student only about these).
dropped_skills lists [{"skill", "reason"}] the model named but that could not be stored.
Owner: D
"""
import argparse
import json

import _cli
import _db
import _llm
import _profile
import _resume_text
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
  "visa": {{"status": "string or null", "needs_sponsorship": true|false|null, "us_person": true|false|null}},
  "availability": {{"start": "YYYY-MM or null", "type": "co-op|internship|full-time or null"}},
  "location": {{"preferred": ["City, ST"], "remote": "any|remote|hybrid|onsite"}},
  "skills": [{{"skill_id": "string", "level": 1, "source": "resume|chat", "evidence": "verbatim line"}}],
  "bullets": ["verbatim resume bullet"]
}}
Rules:
- List each skill_id once, with the verbatim line that best shows it as evidence.
- source is chat when the skill appears only in ADDITIONAL NOTES FROM CHAT; otherwise resume.
- F-1 or J-1 students need sponsorship and are not US persons; US citizens and green card holders are US persons.
- If a fact is not stated, use null, never guess."""

_MOCK = {
    "school": "Northeastern University",
    "program": "MS Mechanical Engineering",
    "visa": {"status": "F-1", "needs_sponsorship": True, "us_person": False},
    "availability": {"start": "2027-01", "type": "co-op"},
    "location": {"preferred": ["Boston, MA"], "remote": "any"},
    "skills": [
        {"skill_id": "python", "level": 2, "source": "resume",
         "evidence": "Built a Python data pipeline that logged sensor readings from 12 test rigs into MySQL"},
        {"skill_id": "mysql", "level": 2, "source": "resume",
         "evidence": "Built a Python data pipeline that logged sensor readings from 12 test rigs into MySQL"},
        {"skill_id": "solidworks", "level": 3, "source": "resume",
         "evidence": "Designed a SolidWorks fixture that cut assembly time by 30%"},
        {"skill_id": "matlab", "level": 1, "source": "resume",
         "evidence": "SKILLS: Python, MySQL, SolidWorks, MATLAB, React Native, Git"},
        {"skill_id": "react-native", "level": 1, "source": "resume",
         "evidence": "React Native app for tracking lab equipment checkouts (course project)"},
        {"skill_id": "git", "level": 1, "source": "resume",
         "evidence": "SKILLS: Python, MySQL, SolidWorks, MATLAB, React Native, Git"},
        {"skill_id": "docker", "level": 1, "source": "chat", "evidence": "I also know Docker"},
    ],
    "bullets": [
        "Built a Python data pipeline that logged sensor readings from 12 test rigs into MySQL",
        "Designed a SolidWorks fixture that cut assembly time by 30%",
        "React Native app for tracking lab equipment checkouts (course project)",
    ],
}


def _extract(resume_text, notes):
    system = SYSTEM.format(taxonomy=_taxonomy.prompt_block())
    user = f"RESUME:\n{resume_text}"
    if notes:
        user += f"\n\nADDITIONAL NOTES FROM CHAT:\n{notes}"
    return _llm.chat_json(system, user, mock=_MOCK, max_tokens=4000)


# Model boundary: every helper below coerces model output before _profile.validate

def _text(value):
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _level(value):
    if type(value) is int:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _choice(value, allowed, default):
    return value if isinstance(value, str) and value in allowed else default


def _visa(raw, missing):
    if isinstance(raw, dict) and isinstance(raw.get("needs_sponsorship"), bool) \
            and isinstance(raw.get("us_person"), bool):
        return {"status": _text(raw.get("status")), "needs_sponsorship": raw["needs_sponsorship"],
                "us_person": raw["us_person"]}
    missing.append("visa")
    return {"status": None, "needs_sponsorship": False, "us_person": False}


def _location(raw, missing):
    raw = raw if isinstance(raw, dict) else {}
    preferred = raw.get("preferred")
    if isinstance(preferred, list) and all(isinstance(p, str) for p in preferred):
        preferred = [p.strip() for p in preferred if p.strip()]
    else:
        preferred = []
        missing.append("location")
    return {"preferred": preferred, "remote": _choice(raw.get("remote"), _profile.REMOTE, "any")}


def _availability(raw, missing):
    if not isinstance(raw, dict):
        missing.append("availability")
        return {"start": None, "type": None}
    return {"start": _text(raw.get("start")), "type": _text(raw.get("type"))}


def _skills(raw):
    merged, dropped = {}, []
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("skill_id"), str):
            dropped.append({"skill": repr(item)[:60], "reason": "malformed"})
            continue
        name = item["skill_id"]
        skill_id = _taxonomy.resolve(name)
        if skill_id is None:
            dropped.append({"skill": name, "reason": "not in taxonomy"})
            continue
        level = _level(item.get("level"))
        if level is None or not 1 <= level <= 3:
            dropped.append({"skill": name, "reason": f"level {item.get('level')!r} is not 1, 2 or 3"})
            continue
        text = _text(item.get("evidence"))
        if text is None:
            dropped.append({"skill": name, "reason": "no evidence"})
            continue
        source = _choice(item.get("source"), _profile.SOURCES, "resume")
        if skill_id not in merged:
            merged[skill_id] = {"skill_id": skill_id, "level": level, "evidence": []}
        skill = merged[skill_id]
        skill["level"] = max(skill["level"], level)
        if text not in [e["text"] for e in skill["evidence"]]:
            skill["evidence"].append({"source": source, "text": text})
    return list(merged.values()), dropped


def _bullets(raw):
    if not isinstance(raw, list):
        return []
    texts = [b.strip() for b in raw if isinstance(b, str) and b.strip()]
    return [{"id": f"b{i + 1}", "text": t} for i, t in enumerate(texts)]


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--name", required=True)
    p.add_argument("--text-file", required=True)
    p.add_argument("--notes", default="")
    args = p.parse_args()

    resume_text = _resume_text.read(args.text_file)
    notes = args.notes.strip()
    extracted = _extract(resume_text, notes)
    if "error" in extracted:
        return {"error": extracted["error"]}
    # Model boundary: skills must be a list, the rest is coerced
    if not isinstance(extracted.get("skills"), list):
        return {"error": "model output missing skills"}
    skills, dropped = _skills(extracted["skills"])

    missing = []
    fields = {
        "school": _text(extracted.get("school")),
        "program": _text(extracted.get("program")),
        "visa": _visa(extracted.get("visa"), missing),
        "availability": _availability(extracted.get("availability"), missing),
        "location": _location(extracted.get("location"), missing),
        "skills": skills,
        "bullets": _bullets(extracted.get("bullets")),
        "company_prefs": [],
        "notes": [notes] if notes else [],
    }

    conn = _db.connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        candidate_id = _db.next_id(conn, "candidates", "c")
        profile = {"id": candidate_id, "name": args.name.strip(), **fields}
        _profile.validate(profile, candidate_id)
        conn.execute(
            "INSERT INTO candidates (id, name, profile_json, consent_auto, synthetic, updated) "
            "VALUES (?, ?, ?, 1, 0, ?)",
            (candidate_id, profile["name"], json.dumps(profile, ensure_ascii=False), _db.now()),
        )
        conn.commit()
    finally:
        conn.close()

    return {"candidate_id": candidate_id, "skills_found": len(skills), "profile": profile,
            "missing": missing, "dropped_skills": dropped}


if __name__ == "__main__":
    _cli.run(main)
