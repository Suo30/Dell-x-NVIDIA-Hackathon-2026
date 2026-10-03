"""Role validation and model-output cleaning (MASTER_CONTEXT 6.3). Owner: C.

    validate(role: {"public", "private"}, source: str) -> None
        Raises ValueError(f"{source}: {field} {problem}") on the first problem.
    clean_requirements(raw, source) -> (requirements, dropped)
        Model boundary: resolves aliases, enforces level 1-3 and must|nice,
        dedupes skills, keeps evidence_text if present. dropped = [{"skill", "reason"}].
    clean_public(raw, source) -> dict
        Model boundary: coerces sponsorship and clearance; raises ValueError if unusable.

Used by draft_role, approve_role and extract_reqs (job requirements share the 6.3 shape).
"""
import _taxonomy

PUBLIC_KEYS = ("title", "description", "location", "sponsorship", "clearance", "pay")
PRIVATE_KEYS = ("requirements", "seniority", "team_context", "timeline")
REQUIREMENT_KEYS = ("skill_id", "level", "importance", "why")
CLEARANCE = {"none", "us_person", "clearance"}
IMPORTANCE = {"must", "nice"}


def _fail(source, field, problem):
    raise ValueError(f"{source}: {field} {problem}")


def _require(obj, keys, source, field):
    if not isinstance(obj, dict):
        _fail(source, field, "must be an object")
    for k in keys:
        if k not in obj:
            _fail(source, f"{field}.{k}", "is missing")


def _optional_str(value, source, field):
    if value is not None and not isinstance(value, str):
        _fail(source, field, f"must be a string or null, got {value!r}")


def validate(role, source):
    _require(role, ("public", "private"), source, "role")
    public, private = role["public"], role["private"]

    _require(public, PUBLIC_KEYS, source, "public")
    for k in ("title", "description"):
        if not isinstance(public[k], str) or not public[k].strip():
            _fail(source, f"public.{k}", "must be a non-empty string")
    _optional_str(public["location"], source, "public.location")
    _optional_str(public["pay"], source, "public.pay")
    if public["sponsorship"] is not None and not isinstance(public["sponsorship"], bool):
        _fail(source, "public.sponsorship", f"must be true, false or null, got {public['sponsorship']!r}")
    if public["clearance"] not in CLEARANCE:
        _fail(source, "public.clearance", f"is {public['clearance']!r}, expected one of {sorted(CLEARANCE)}")

    _require(private, PRIVATE_KEYS, source, "private")
    for k in ("seniority", "team_context", "timeline"):
        _optional_str(private[k], source, f"private.{k}")
    reqs = private["requirements"]
    if not isinstance(reqs, list) or not reqs:
        _fail(source, "private.requirements", "must be a non-empty list")
    known = {s["id"] for s in _taxonomy.load()}
    seen = set()
    for i, req in enumerate(reqs):
        field = f"private.requirements[{i}]"
        _require(req, REQUIREMENT_KEYS, source, field)
        if req["skill_id"] not in known:
            _fail(source, f"{field}.skill_id", f"{req['skill_id']!r} is not in skills.json")
        if req["skill_id"] in seen:
            _fail(source, f"{field}.skill_id", f"{req['skill_id']!r} is listed twice")
        seen.add(req["skill_id"])
        if type(req["level"]) is not int or not 1 <= req["level"] <= 3:
            _fail(source, f"{field}.level", f"is {req['level']!r}, expected 1, 2 or 3")
        if req["importance"] not in IMPORTANCE:
            _fail(source, f"{field}.importance", f"is {req['importance']!r}, expected must or nice")
        if not isinstance(req["why"], str) or not req["why"].strip():
            _fail(source, f"{field}.why", "must be a non-empty string")


def _level(value):
    if type(value) is int:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _merge(old, new):
    old_rank = (old["importance"] == "must", old["level"])
    new_rank = (new["importance"] == "must", new["level"])
    keep = new if new_rank > old_rank else old
    whys = [old["why"]] + ([new["why"]] if new["why"] != old["why"] else [])
    merged = {**keep, "why": "; ".join(whys)}
    if "evidence_text" not in merged and "evidence_text" in old:
        merged["evidence_text"] = old["evidence_text"]
    return merged


def clean_requirements(raw, source):
    # Model boundary: requirements come from model output (or a person's typed edits)
    if not isinstance(raw, list):
        raise ValueError(f"{source}: requirements must be a list")  # noqa: TRY004, bad data per AGENTS.md
    kept, dropped = {}, []
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
            dropped.append({"skill": name, "reason": f"level {item.get('level')}"})
            continue
        importance = str(item.get("importance")).strip().lower()
        if importance not in IMPORTANCE:
            dropped.append({"skill": name, "reason": f"importance {item.get('importance')}"})
            continue
        why = str(item.get("why") or "").strip() or _taxonomy.name_of(skill_id)
        req = {"skill_id": skill_id, "level": level, "importance": importance, "why": why}
        evidence = item.get("evidence_text")
        if isinstance(evidence, str) and evidence.strip():
            req["evidence_text"] = evidence.strip()
        kept[skill_id] = _merge(kept[skill_id], req) if skill_id in kept else req
    return list(kept.values()), dropped


def _sponsorship(value):
    if value is None or isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("yes", "true"):
        return True
    if text in ("no", "false"):
        return False
    return None  # unknown never flags


def _text_or_none(value):
    if not isinstance(value, str):
        return None
    return value.strip() or None


def clean_public(raw, source):
    # Model boundary: public JD fields from model output
    if not isinstance(raw, dict):
        raise ValueError(f"{source}: public must be an object")  # noqa: TRY004, bad data per AGENTS.md
    out = {}
    for k in ("title", "description"):
        value = raw.get(k)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{source}: public.{k} must be a non-empty string")
        out[k] = value.strip()
    clearance = str(raw.get("clearance") or "").strip().lower().replace(" ", "_")
    out["location"] = _text_or_none(raw.get("location"))
    out["sponsorship"] = _sponsorship(raw.get("sponsorship"))
    out["clearance"] = clearance if clearance in CLEARANCE else "none"
    out["pay"] = _text_or_none(raw.get("pay"))
    return out
