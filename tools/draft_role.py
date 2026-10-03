"""Employer: clarified conversation -> draft role with public JD + private context (6.3).

Contract (MASTER_CONTEXT section 8):
    draft_role.py --company "X" --conversation-file PATH [--paid]
    -> {"role_id", "status": "draft", "company", "public", "private", "dropped_skills"}
Owner: C
"""
import argparse
import json
from pathlib import Path

import _cli
import _db
import _llm
import _role
import _taxonomy

SYSTEM = """You turn a hiring manager's conversation into one job description for a university career office.
Return only JSON:
{"public": {"title": str, "description": str, "location": str or null,
            "sponsorship": true|false|null, "clearance": "none"|"us_person"|"clearance",
            "pay": str or null},
 "private": {"requirements": [{"skill_id": str, "level": 1|2|3, "importance": "must"|"nice",
                               "why": str}],
             "seniority": str or null, "team_context": str or null, "timeline": str or null}}
Rules:
- description: 80 to 150 words, plain language, only the work: what the person will build and own,
  and with which tools. No logistics: never mention team size, engineers, designers, start date,
  months, timeline, location or pay; those have their own fields.
- location: "City, ST (onsite|hybrid|remote)" when known.
- sponsorship: true if they said they can sponsor visas, false if they cannot, null if not discussed.
- clearance: "us_person" if US citizenship or export control is required, "clearance" if a security
  clearance is required, otherwise "none".
- pay: as stated, like "35-45 USD/hour" or "90000-110000 USD/year"; null if not stated.
- requirements: 3 to 8 items. skill_id only from the list below. Use the most specific skill the
  manager named (MySQL, not SQL). "must" only for skills the manager named or that the described
  work cannot be done without, at most 4. Skills you add beyond what was said are "nice" at level 1.
  level: 1 = course or small project, 2 = used in a job or substantial project, 3 = designed, led or
  owned it. why: one short phrase tied to the conversation.
- seniority: one of co-op, intern, new grad, experienced.
Skills:
{taxonomy}"""

_MOCK = {
    "public": {
        "title": "Mobile App Engineer (Co-op)",
        "description": (
            "You will build and own the React Native app our operations team uses every day, "
            "together with the MySQL backend behind it. You will work directly with ops staff "
            "to turn their requests into features and ship them."
        ),
        "location": "Boston, MA (hybrid)",
        "sponsorship": True,
        "clearance": "none",
        "pay": "35-45 USD/hour",
    },
    "private": {
        "requirements": [
            {"skill_id": "react-native", "level": 2, "importance": "must", "why": "owns the mobile app"},
            {"skill_id": "mysql", "level": 2, "importance": "must", "why": "owns the MySQL backend"},
            {"skill_id": "python", "level": 1, "importance": "nice", "why": "backend scripts"},
            {"skill_id": "git", "level": 1, "importance": "nice", "why": "shared codebase"},
        ],
        "seniority": "co-op",
        "team_context": "2 engineers, no designer",
        "timeline": "start Jan 2027",
    },
}

NO_SKILLS = "model found no taxonomy skills; ask the manager what the person will build"


def _text(value):
    # Model boundary: free-text private fields are a string or None
    if not isinstance(value, str):
        return None
    return value.strip() or None


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--company", required=True)
    p.add_argument("--conversation-file", required=True)
    p.add_argument("--paid", action="store_true")
    args = p.parse_args()

    company = args.company.strip()
    if not company:
        raise ValueError("--company must not be empty")
    text = Path(args.conversation_file).read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"{args.conversation_file}: conversation file is empty")

    system = SYSTEM.replace("{taxonomy}", _taxonomy.prompt_block())
    user = f"COMPANY: {company}\n\nCONVERSATION:\n{text}"
    out = _llm.chat_json(system, user, mock=_MOCK, max_tokens=4000)
    if "error" in out:
        return out
    for key in ("public", "private"):
        if key not in out:
            return {"error": f"model output missing {key}"}
    raw_private = out["private"]
    if not isinstance(raw_private, dict):
        raise ValueError("draft: private must be an object")  # noqa: TRY004, bad model data per AGENTS.md
    if "requirements" not in raw_private:
        return {"error": "model output missing private.requirements"}

    public = _role.clean_public(out["public"], "draft")
    requirements, dropped = _role.clean_requirements(raw_private["requirements"], "draft")
    if not requirements:
        return {"error": NO_SKILLS, "dropped_skills": dropped}
    # Model boundary: optional text fields may be absent
    private = {"requirements": requirements,
               **{k: _text(raw_private.get(k)) for k in ("seniority", "team_context", "timeline")}}
    _role.validate({"public": public, "private": private}, "draft")

    conn = _db.connect()
    try:
        role_id = _db.next_id(conn, "roles", "r")
        conn.execute(
            "INSERT INTO roles (id, company, paid, status, public_json, private_json, created) "
            "VALUES (?, ?, ?, 'draft', ?, ?, ?)",
            (role_id, company, int(args.paid), json.dumps(public, ensure_ascii=False),
             json.dumps(private, ensure_ascii=False), _db.now()),
        )
        conn.commit()
    finally:
        conn.close()

    return {"role_id": role_id, "status": "draft", "company": company, "public": public,
            "private": private, "dropped_skills": dropped}


if __name__ == "__main__":
    _cli.run(main)
