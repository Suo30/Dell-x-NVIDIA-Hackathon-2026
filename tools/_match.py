"""Scoring, flags, routes, sort. Pure code, no model. Owner: B.
Rules: MASTER_CONTEXT section 7. Both match_jobs.py (B) and
match_candidates.py (C) call evaluate(), so keep its signature stable.

    evaluate(job: dict, profile: dict) -> dict
        job: {"id", "requirements": [...6.4...], "sponsorship": bool|None,
              "clearance": "none"|"us_person"|"clearance"|None,
              "location": str|None, "company": str|None, "pay": str|None, "paid": int}
        profile: candidate profile (6.2)
        returns {"score": float, "route": "match"|"stretch"|"review"|"hidden"|"excluded",
                 "eager": bool, "detail": {...6.5...}}

    score(detail_requirements) -> float              7.2
    flags(job, profile) -> list[str]                 7.3, order: sponsorship, clearance, location
    route(score, detail_requirements, flags) -> str  7.4
    apply_prefs(route, job, profile) -> (route, pref_note|None, eager)   7.5
        Prefs only demote: "never" -> "excluded"; "only_strong_offer" turns
        match/stretch into review unless pay (lower bound) >= min_pay.
    sort_key(row) -> tuple                           7.6; row has route, score, eager, paid
    gap_text(skill_name, required, candidate_level) -> str
        "The evidence did not show MySQL at level 2 (has level 1)". Never "lacks".
    top_evidence(detail, n=2) -> list[str]
        Evidence of strong must requirements, then strong nice, deduplicated.
    parse_hourly(pay) -> float|None
        First number in the pay text, hourly USD; values over 1000 are annual (/2080).
"""
import re

import _taxonomy
import aux_math

ROUTE_ORDER = {"match": 0, "stretch": 1, "review": 2, "hidden": 3, "excluded": 4}
WEIGHT = {"must": 2, "nice": 1}
CREDIT = {"strong": 1.0, "partial": 0.5, "none": 0.0}
HOURS_PER_YEAR = 2080


def _requirement(req, by_skill, job_id):
    if req["importance"] not in WEIGHT:
        raise RuntimeError(f"job {job_id}: {req['skill_id']} has importance {req['importance']!r}")
    required = req["level"]
    level, evidence = 0, None
    if req["skill_id"] in by_skill:
        skill = by_skill[req["skill_id"]]
        level = skill["level"]
        if skill["evidence"]:
            evidence = skill["evidence"][0]["text"]
    if level >= required:
        match = "strong"
    elif level > 0 and level == required - 1:
        match = "partial"
    else:
        match = "none"
    closable = match == "partial" or (match == "none" and req["importance"] == "nice")
    return {"skill_id": req["skill_id"], "importance": req["importance"], "required": required,
            "candidate_level": level, "match": match, "evidence": evidence, "closable": closable}


def evaluate(job, profile):
    if not job["requirements"]:
        raise RuntimeError(f"job {job['id']} has no requirements; match only extracted jobs")
    by_skill = {s["skill_id"]: s for s in profile["skills"]}
    reqs = [_requirement(r, by_skill, job["id"]) for r in job["requirements"]]
    score_value = score(reqs)
    flag_list = flags(job, profile)
    route_value, pref_note, eager = apply_prefs(route(score_value, reqs, flag_list), job, profile)
    gaps = [gap_text(_taxonomy.name_of(r["skill_id"]), r["required"], r["candidate_level"])
            for r in reqs if r["match"] != "strong"]
    return {"score": score_value, "route": route_value, "eager": eager,
            "detail": {"requirements": reqs, "flags": flag_list, "pref_note": pref_note,
                       "gaps_text": gaps}}


def score(detail_requirements):
    if not detail_requirements:
        raise RuntimeError("score: no requirements")
    total = sum(WEIGHT[r["importance"]] for r in detail_requirements)
    got = sum(WEIGHT[r["importance"]] * CREDIT[r["match"]] for r in detail_requirements)
    return round(100 * got / total, 1)


def flags(job, profile):
    visa, loc = profile["visa"], profile["location"]
    out = []
    if visa["needs_sponsorship"] and job["sponsorship"] is False:
        out.append("sponsorship")
    if job["clearance"] in ("us_person", "clearance") and not visa["us_person"]:
        out.append("clearance")
    if job["location"] and loc["remote"] != "any":
        where = job["location"].lower()
        cities = [p.split(",", 1)[0].strip().lower() for p in loc["preferred"]]
        flexible = "remote" in where or "hybrid" in where
        if not flexible and not any(c and c in where for c in cities):
            out.append("location")
    return out


def route(score_value, detail_requirements, flag_list):
    if flag_list:
        return "review"
    if aux_math.ge(score_value, 70):
        return "match"
    gaps_closable = all(r["closable"] for r in detail_requirements if r["match"] != "strong")
    if aux_math.ge(score_value, 50) and gaps_closable:
        return "stretch"
    return "hidden"


def _fmt(x):
    return f"{round(x, 2):g}"


def apply_prefs(route_value, job, profile):
    company = (job["company"] or "").lower()
    prefs = [p for p in profile["company_prefs"] if company and p["company"].lower() == company]
    if not prefs:
        return route_value, None, False
    pref = prefs[0]
    if pref["stance"] == "never":
        return "excluded", None, False
    if pref["stance"] == "eager":
        return route_value, None, True
    if pref["stance"] == "only_strong_offer" and route_value in ("match", "stretch"):
        pay = parse_hourly(job["pay"])
        if pay is None:
            return "review", "only_strong_offer: pay not stated", False
        if pref["min_pay"] is not None and aux_math.lt(pay, pref["min_pay"]):
            note = f"only_strong_offer: pay {_fmt(pay)} below minimum {_fmt(pref['min_pay'])}"
            return "review", note, False
    return route_value, None, False


def parse_hourly(pay):
    if pay is None:
        return None
    nums = re.findall(r"\d[\d,]*\.?\d*", pay)
    if not nums:
        return None
    value = float(nums[0].replace(",", ""))
    if aux_math.lt(1000, value):
        value /= HOURS_PER_YEAR
    return value


def sort_key(row):
    return (ROUTE_ORDER[row["route"]], -row["score"], not row["eager"], not row["paid"])


def gap_text(skill_name, required, candidate_level):
    base = f"The evidence did not show {skill_name} at level {required}"
    if candidate_level == 0:
        return f"{base} (no evidence found)"
    return f"{base} (has level {candidate_level})"


def top_evidence(detail, n=2):
    strong = [r for r in detail["requirements"] if r["match"] == "strong" and r["evidence"] is not None]
    ordered = [r for r in strong if r["importance"] == "must"] + [r for r in strong if r["importance"] == "nice"]
    out = []
    for r in ordered:
        if r["evidence"] not in out:
            out.append(r["evidence"])
    return out[:n]
