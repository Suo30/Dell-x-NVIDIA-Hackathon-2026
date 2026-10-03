"""Candidate: one chat statement -> profile changes (skills, prefs, visa, location, notes).

Contract (MASTER_CONTEXT section 8):
    update_profile.py --candidate ID --note "I'd only work at Acme for a great offer"
    -> {"candidate_id", "changes": [...], "ignored": [{"change", "reason"}]}
The model proposes typed changes; code applies them. Invalid ones go to ignored, never stored.
If nothing applies, the note is kept in notes. Stored matches for the candidate are cleared.
Owner: D
"""
import argparse
import json

import _cli
import _db
import _llm
import _profile
import _taxonomy
import aux_math

HOURS_PER_YEAR = 2080

SYSTEM = """You record what a student just said into their career profile. Return only JSON {"changes": [...]}
using only these change types:
{"type": "skill", "skill_id": "<id from the list>", "level": 1|2|3}
{"type": "company_pref", "company": "Name", "stance": "eager|neutral|only_strong_offer|never",
 "min_pay": number or null}            (min_pay: the hourly USD minimum they named, else null)
{"type": "visa", "status": str, "needs_sponsorship": bool, "us_person": bool}
{"type": "location", "preferred": ["City, ST"], "remote": "any|remote|hybrid|onsite"}
{"type": "availability", "start": "YYYY-MM", "job_type": "co-op|internship|full-time"}
{"type": "note"}                       (anything else worth remembering)
Only record what the student stated. "Only for a really strong offer" is only_strong_offer.
Levels: 1 = course or small project, 2 = job or substantial project, 3 = designed, led or owned it."""

_MOCK = {"changes": [{"type": "company_pref", "company": "Acme", "stance": "only_strong_offer",
                      "min_pay": None}]}


class _Ignore(Exception):
    """A model-proposed change that cannot be stored; the message is the reason."""


def _compact(profile):
    return json.dumps({
        "skills": [f"{s['skill_id']}:{s['level']}" for s in profile["skills"]],
        "company_prefs": profile["company_prefs"],
        "visa": profile["visa"],
        "location": profile["location"],
        "availability": profile["availability"],
    }, ensure_ascii=False)


# Model boundary: every change below comes from model output and is checked before it is applied

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


def _pay(value):
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        pay = value
    elif isinstance(value, str):
        try:
            pay = float(value.strip().lstrip("$").replace(",", ""))
        except ValueError:
            raise _Ignore(f"min_pay {value!r} is not a number") from None
    else:
        raise _Ignore(f"min_pay {value!r} is not a number")
    if aux_math.lt(pay, 0):
        raise _Ignore(f"min_pay {value!r} is negative")
    if aux_math.lt(1000, pay):
        return round(pay / HOURS_PER_YEAR, 2)
    return pay


def _skill(profile, change, note):
    name = change.get("skill_id")
    skill_id = _taxonomy.resolve(name) if isinstance(name, str) else None
    if skill_id is None:
        raise _Ignore(f"skill {name!r} is not in the taxonomy")
    level = _level(change.get("level"))
    if level is None or not 1 <= level <= 3:
        raise _Ignore(f"level {change.get('level')!r} is not 1, 2 or 3")
    evidence = {"source": "chat", "text": note}
    for skill in profile["skills"]:
        if skill["skill_id"] == skill_id:
            known = note in [e["text"] for e in skill["evidence"]]
            if level <= skill["level"] and known:
                raise _Ignore(f"{skill_id} at level {skill['level']} with this evidence is already recorded")
            action = "raised" if level > skill["level"] else "evidence_added"
            skill["level"] = max(skill["level"], level)
            if not known:
                skill["evidence"].append(evidence)
            return {"type": "skill", "skill_id": skill_id, "level": skill["level"], "action": action}
    profile["skills"].append({"skill_id": skill_id, "level": level, "evidence": [evidence]})
    return {"type": "skill", "skill_id": skill_id, "level": level, "action": "added"}


def _company_pref(profile, change, note):
    company = _text(change.get("company"))
    if company is None:
        raise _Ignore("company is missing")
    stance = change.get("stance")
    if stance not in _profile.STANCES:
        raise _Ignore(f"stance {stance!r} is not one of {sorted(_profile.STANCES)}")
    pref = {"company": company, "stance": stance, "min_pay": _pay(change.get("min_pay"))}
    prefs = profile["company_prefs"]
    same = [i for i, p in enumerate(prefs) if p["company"].lower() == company.lower()]
    for i in reversed(same):
        del prefs[i]
    prefs.append(pref)
    return {"type": "company_pref", **pref, "action": "replaced" if same else "added"}


def _visa(profile, change, note):
    needs, us_person = change.get("needs_sponsorship"), change.get("us_person")
    if not isinstance(needs, bool) or not isinstance(us_person, bool):
        raise _Ignore("needs_sponsorship and us_person must be true or false")
    status = _text(change.get("status")) or profile["visa"]["status"]
    profile["visa"] = {"status": status, "needs_sponsorship": needs, "us_person": us_person}
    return {"type": "visa", **profile["visa"]}


def _location(profile, change, note):
    remote = change.get("remote")
    if remote not in _profile.REMOTE:
        raise _Ignore(f"remote {remote!r} is not one of {sorted(_profile.REMOTE)}")
    preferred = change.get("preferred")
    if not isinstance(preferred, list) or not all(isinstance(p, str) for p in preferred):
        raise _Ignore(f"preferred {preferred!r} is not a list of strings")
    profile["location"] = {"preferred": [p.strip() for p in preferred if p.strip()], "remote": remote}
    return {"type": "location", **profile["location"]}


def _availability(profile, change, note):
    start, job_type = change.get("start"), change.get("job_type")
    for key, value in (("start", start), ("job_type", job_type)):
        if value is not None and not isinstance(value, str):
            raise _Ignore(f"{key} {value!r} is not a string or null")
    start, job_type = _text(start), _text(job_type)
    if start is None and job_type is None:
        raise _Ignore("neither start nor job_type stated")
    old = profile["availability"]
    profile["availability"] = {"start": start or old["start"], "type": job_type or old["type"]}
    return {"type": "availability", "start": profile["availability"]["start"],
            "job_type": profile["availability"]["type"]}


def _note(profile, change, note):
    if note not in profile["notes"]:
        profile["notes"].append(note)
    return {"type": "note"}


HANDLERS = {"skill": _skill, "company_pref": _company_pref, "visa": _visa, "location": _location,
            "availability": _availability, "note": _note}


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--candidate", required=True)
    p.add_argument("--note", required=True)
    args = p.parse_args()
    note = args.note.strip()
    if not note:
        raise ValueError("--note is empty")

    conn = _db.connect()
    try:
        row = conn.execute("SELECT profile_json FROM candidates WHERE id = ?", (args.candidate,)).fetchone()
        if row is None:
            raise ValueError(f"candidate {args.candidate} not found")
        profile = json.loads(row["profile_json"])

        system = (SYSTEM + f"\nCurrent profile: {_compact(profile)}\nSkills:\n{_taxonomy.prompt_block()}")
        out = _llm.chat_json(system, note, mock=_MOCK, max_tokens=4000)
        if "error" in out:
            return {"error": out["error"]}
        # Model boundary: changes must be a list
        if not isinstance(out.get("changes"), list):
            return {"error": "model output missing changes"}

        changes, ignored = [], []
        for change in out["changes"]:
            kind = change.get("type") if isinstance(change, dict) else None
            if kind not in HANDLERS:
                ignored.append({"change": change, "reason": f"unknown change type {kind!r}"})
                continue
            try:
                changes.append(HANDLERS[kind](profile, change, note))
            except _Ignore as e:
                ignored.append({"change": change, "reason": str(e)})
        if not changes:
            changes.append(_note(profile, {"type": "note"}, note))

        _profile.validate(profile, args.candidate)
        conn.execute("UPDATE candidates SET profile_json = ?, updated = ? WHERE id = ?",
                     (json.dumps(profile, ensure_ascii=False), _db.now(), args.candidate))
        conn.execute("DELETE FROM matches WHERE candidate_id = ?", (args.candidate,))
        conn.commit()
    finally:
        conn.close()

    return {"candidate_id": args.candidate, "changes": changes, "ignored": ignored}


if __name__ == "__main__":
    _cli.run(main)
