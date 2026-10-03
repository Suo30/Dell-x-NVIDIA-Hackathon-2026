"""Structural validation of a candidate profile (MASTER_CONTEXT 6.2). Owner: D.

    validate(profile: dict, source: str) -> None
        Raises ValueError(f"{source}: {field} {problem}") on the first problem.
        source names where the profile came from (a file name or candidate id).

Called by seed_db, ingest_profile and update_profile before a profile is stored.
"""
import _taxonomy

KEYS = ("id", "name", "school", "program", "visa", "availability", "location",
        "skills", "bullets", "company_prefs", "notes")
VISA_KEYS = ("status", "needs_sponsorship", "us_person")
REMOTE = {"any", "remote", "hybrid", "onsite"}
STANCES = {"eager", "neutral", "only_strong_offer", "never"}
SOURCES = {"resume", "chat"}


def _fail(source, field, problem):
    raise ValueError(f"{source}: {field} {problem}")


def _require(obj, keys, source, prefix=""):
    if not isinstance(obj, dict):
        _fail(source, prefix.rstrip(".") or "profile", "must be an object")
    for k in keys:
        if k not in obj:
            _fail(source, prefix + k, "is missing")


def _is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def validate(profile, source):
    _require(profile, KEYS, source)
    for k in ("id", "name"):
        if not isinstance(profile[k], str) or not profile[k].strip():
            _fail(source, k, "must be a non-empty string")

    visa = profile["visa"]
    _require(visa, VISA_KEYS, source, "visa.")
    for k in ("needs_sponsorship", "us_person"):
        if not isinstance(visa[k], bool):
            _fail(source, f"visa.{k}", f"must be true or false, got {visa[k]!r}")

    loc = profile["location"]
    _require(loc, ("preferred", "remote"), source, "location.")
    if not isinstance(loc["preferred"], list):
        _fail(source, "location.preferred", "must be a list")
    if loc["remote"] not in REMOTE:
        _fail(source, "location.remote", f"is {loc['remote']!r}, expected one of {sorted(REMOTE)}")

    for i, pref in enumerate(profile["company_prefs"]):
        field = f"company_prefs[{i}]"
        _require(pref, ("company", "stance", "min_pay"), source, field + ".")
        if pref["stance"] not in STANCES:
            _fail(source, f"{field}.stance", f"is {pref['stance']!r}, expected one of {sorted(STANCES)}")
        if pref["min_pay"] is not None and not _is_number(pref["min_pay"]):
            _fail(source, f"{field}.min_pay", f"must be a number or null, got {pref['min_pay']!r}")

    known = {s["id"] for s in _taxonomy.load()}
    seen = set()
    for i, skill in enumerate(profile["skills"]):
        field = f"skills[{i}]"
        _require(skill, ("skill_id", "level", "evidence"), source, field + ".")
        if skill["skill_id"] not in known:
            _fail(source, f"{field}.skill_id", f"{skill['skill_id']!r} is not in skills.json")
        if skill["skill_id"] in seen:
            _fail(source, f"{field}.skill_id", f"{skill['skill_id']!r} is listed twice")
        seen.add(skill["skill_id"])
        if type(skill["level"]) is not int or not 1 <= skill["level"] <= 3:
            _fail(source, f"{field}.level", f"is {skill['level']!r}, expected 1, 2 or 3")
        if not skill["evidence"]:
            _fail(source, f"{field}.evidence", "is empty")
        for j, ev in enumerate(skill["evidence"]):
            _require(ev, ("source", "text"), source, f"{field}.evidence[{j}].")
            if ev["source"] not in SOURCES:
                _fail(source, f"{field}.evidence[{j}].source", f"is {ev['source']!r}, expected resume or chat")
            if not isinstance(ev["text"], str) or not ev["text"].strip():
                _fail(source, f"{field}.evidence[{j}].text", "must be a non-empty string")

    bullet_ids = set()
    for i, b in enumerate(profile["bullets"]):
        _require(b, ("id", "text"), source, f"bullets[{i}].")
        if b["id"] in bullet_ids:
            _fail(source, f"bullets[{i}].id", f"{b['id']!r} is not unique")
        bullet_ids.add(b["id"])
