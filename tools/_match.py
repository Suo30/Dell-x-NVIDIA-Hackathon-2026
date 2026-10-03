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

ROUTE_ORDER = {"match": 0, "stretch": 1, "review": 2, "hidden": 3, "excluded": 4}


def evaluate(job, profile):
    raise NotImplementedError("_match.evaluate (owner: B)")


def score(detail_requirements):
    raise NotImplementedError("_match.score (owner: B)")


def flags(job, profile):
    raise NotImplementedError("_match.flags (owner: B)")


def route(score_value, detail_requirements, flag_list):
    raise NotImplementedError("_match.route (owner: B)")


def apply_prefs(route_value, job, profile):
    raise NotImplementedError("_match.apply_prefs (owner: B)")


def sort_key(row):
    raise NotImplementedError("_match.sort_key (owner: B)")


def gap_text(skill_name, required, candidate_level):
    raise NotImplementedError("_match.gap_text (owner: B)")
