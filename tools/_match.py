"""Scoring, flags, routes, sort. Pure code, no model. Owner: B.
Rules: MASTER_CONTEXT section 7. Both match_jobs.py (B) and
match_candidates.py (C) call evaluate(), so keep its signature stable.

    evaluate(job: dict, profile: dict) -> dict
        job: {"requirements": [...6.4...], "sponsorship": bool|None,
              "clearance": "none"|"us_person"|"clearance"|None,
              "location": str|None, "company": str|None, "pay": str|None, "paid": int}
        profile: candidate profile (6.2)
        returns {"score": float, "route": "match"|"stretch"|"review"|"hidden"|"excluded",
                 "detail": {...6.5...}}

    score(detail_requirements) -> float              7.2
    flags(job, profile) -> list[str]                 7.3
    route(score, detail_requirements, flags) -> str  7.4
    apply_prefs(route, job, profile) -> (route, pref_note|None)   7.5 ("never" -> "excluded")
    sort_key(row) -> tuple                           7.6; row has route, score, eager, paid
    gap_text(skill_name, required, candidate_level) -> str
        "The evidence did not show MySQL at level 2 (has level 1)". Never "lacks".
"""
import re

import _taxonomy

ROUTE_ORDER = {"match": 0, "stretch": 1, "review": 2, "hidden": 3, "excluded": 4}
_WEIGHT = {"must": 2, "nice": 1}
_CREDIT = {"strong": 1.0, "partial": 0.5, "none": 0.0}
_PAY_RE = re.compile(r"\d+(?:\.\d+)?")


def _classify(required_level, candidate_level):
    if candidate_level is None:
        return "none"
    if candidate_level >= required_level:
        return "strong"
    if candidate_level == required_level - 1:
        return "partial"
    return "none"


def _skill_levels(profile):
    levels = {}
    for entry in profile["skills"]:
        levels[entry["skill_id"]] = entry["level"]
    return levels


def _skill_evidence(profile):
    evidence = {}
    for entry in profile["skills"]:
        if entry["evidence"]:
            evidence[entry["skill_id"]] = entry["evidence"][0]["text"]
    return evidence


def gap_text(skill_name, required, candidate_level):
    if not candidate_level:
        return f"The evidence did not show {skill_name} at level {required}"
    return f"The evidence did not show {skill_name} at level {required} (has level {candidate_level})"


def _build_requirements(job_requirements, profile):
    levels = _skill_levels(profile)
    evidence = _skill_evidence(profile)
    detail_requirements = []
    for req in job_requirements:
        importance = req["importance"]
        if importance not in _WEIGHT:
            raise RuntimeError(
                f"requirement {req['skill_id']!r} has importance {importance!r}, expected 'must' or 'nice'"
            )
        candidate_level = levels.get(req["skill_id"])
        match = _classify(req["level"], candidate_level)
        closable = match != "none" or importance == "nice"
        detail_requirements.append({
            "skill_id": req["skill_id"],
            "importance": importance,
            "required": req["level"],
            "candidate_level": candidate_level,
            "match": match,
            "evidence": evidence.get(req["skill_id"]),
            "closable": closable,
        })
    return detail_requirements


def score(detail_requirements):
    if not detail_requirements:
        return 100.0
    weighted_credit = 0.0
    total_weight = 0.0
    for req in detail_requirements:
        weight = _WEIGHT[req["importance"]]
        weighted_credit += weight * _CREDIT[req["match"]]
        total_weight += weight
    return round(100 * weighted_credit / total_weight, 1)


def category_scores(detail_requirements):
    """Split score() by taxonomy category: soft_skill vs technical. Bonus, not in 6.5."""
    groups = {"technical": [], "soft_skill": []}
    for req in detail_requirements:
        bucket = "soft_skill" if _taxonomy.category_of(req["skill_id"]) == "soft_skill" else "technical"
        groups[bucket].append(req)
    return {name: score(reqs) for name, reqs in groups.items() if reqs}


def _parse_pay(pay_text):
    if not pay_text:
        return None
    numbers = [float(n) for n in _PAY_RE.findall(pay_text)]
    return min(numbers) if numbers else None


def flags(job, profile):
    found = []
    visa = profile["visa"]
    if visa["needs_sponsorship"] and job.get("sponsorship") is False:
        found.append("sponsorship")
    if job.get("clearance") in ("us_person", "clearance") and not visa["us_person"]:
        found.append("clearance")

    job_location = job.get("location")
    remote_pref = profile["location"]["remote"]
    # Boundary: job location is free-form JD text, not a structured field, so
    # "onsite" is inferred with a substring heuristic rather than trusted as typed data.
    if job_location and remote_pref != "any" and "remote" not in job_location.lower():
        preferred = profile["location"]["preferred"]
        if not any(pref.lower() in job_location.lower() for pref in preferred):
            found.append("location")
    return found


def route(score_value, detail_requirements, flag_list):
    if flag_list:
        return "review"
    if score_value >= 70:
        return "match"
    if 50 <= score_value < 70:
        gaps = [r for r in detail_requirements if r["match"] != "strong"]
        if all(r["closable"] for r in gaps):
            return "stretch"
    return "hidden"


def apply_prefs(route_value, job, profile):
    company = job.get("company")
    if not company:
        return route_value, None
    for pref in profile["company_prefs"]:
        if pref["company"].lower() != company.lower():
            continue
        stance = pref["stance"]
        if stance == "never":
            return "excluded", None
        if stance == "only_strong_offer":
            pay = _parse_pay(job.get("pay"))
            min_pay = pref["min_pay"]
            if pay is None:
                return "review", "only_strong_offer: pay not stated"
            if min_pay is not None and pay < min_pay:
                return "review", f"only_strong_offer: pay below ${min_pay}/hr minimum"
            return route_value, None
        return route_value, None
    return route_value, None


def sort_key(row):
    return (
        ROUTE_ORDER[row["route"]],
        -row["score"],
        0 if row["eager"] else 1,
        0 if row["paid"] else 1,
    )


def evaluate(job, profile):
    detail_requirements = _build_requirements(job["requirements"], profile)
    score_value = score(detail_requirements)
    flag_list = flags(job, profile)
    route_value = route(score_value, detail_requirements, flag_list)
    gaps_text = [
        gap_text(_taxonomy.name_of(r["skill_id"]), r["required"], r["candidate_level"])
        for r in detail_requirements
        if r["match"] != "strong"
    ]
    detail = {
        "requirements": detail_requirements,
        "flags": flag_list,
        "pref_note": None,
        "gaps_text": gaps_text,
        "category_scores": category_scores(detail_requirements),
    }
    return {"score": score_value, "route": route_value, "detail": detail}
