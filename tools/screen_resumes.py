"""Employer: screen outside applicants' resumes against an approved role (recruit_assistant).

Contract (MASTER_CONTEXT section 8):
    screen_resumes.py --role ID --resumes PATH [PATH ...] [--consent-confirmed] [--discover]
    screen_resumes.py --title "X" --jd-file PATH --resumes PATH [PATH ...] [...]
    -> {"intake_id", "run_id", "role_id", "rubric_source", "shortlist_count", "results": [...], "notice"}

--role builds the rubric in code from the role's private requirements (same skills.json
requirements match_candidates uses). --title/--jd-file lets the model write the rubric.
Without --consent-confirmed only the resume text is used (no web calls).
--consent-confirmed also reads GitHub/LinkedIn links written in the resume;
--discover additionally searches the web for unlinked profiles (needs mcporter + Exa).
Needs requirements-recruit.txt. Results are stored under work/recruit/.
Owner: A
"""
import argparse
import json
import os
import sys
from pathlib import Path

import _cli
import _config
import _db
import _taxonomy

IMPORTANCE_WEIGHT = {"must": 2, "nice": 1}
LEVELS = {
    1: "used in a course or small project",
    2: "used in a job, internship or substantial project",
    3: "designed, led or owned something with it",
}


def load_role(role_id):
    conn = _db.connect()
    try:
        row = conn.execute(
            "SELECT company, status, public_json, private_json FROM roles WHERE id = ?", (role_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise ValueError(f"role {role_id} not found")
    if row["status"] != "approved":
        raise ValueError(f"role {role_id} is {row['status']!r}; approve it before screening applicants")
    return row["company"], json.loads(row["public_json"]), json.loads(row["private_json"])


def role_job_description(company, public, private):
    lines = [
        f"{public['title']} at {company}",
        public["description"],
        f"Location: {public['location']}",
        f"Seniority: {private['seniority']}",
        "Requirements:",
    ]
    for req in private["requirements"]:
        lines.append(
            f"- {_taxonomy.name_of(req['skill_id'])}, level {req['level']} "
            f"({LEVELS[req['level']]}), {req['importance']}: {req['why']}"
        )
    return "\n".join(lines)


def rubric_criteria(requirements):
    """Role requirements (6.3) -> recruit_assistant rubric criteria dicts, weights summing to 100."""
    if not requirements:
        raise ValueError("role has no requirements to screen against")
    total = sum(IMPORTANCE_WEIGHT[r["importance"]] for r in requirements)
    return [
        {
            "criterion_id": r["skill_id"],
            # Title is matched word by word against evidence, so the level stays in the description
            "title": _taxonomy.name_of(r["skill_id"]),
            "description": f"Level {r['level']}: {LEVELS[r['level']]}. Why: {r['why']}",
            "required": r["importance"] == "must",
            "weight": 100 * IMPORTANCE_WEIGHT[r["importance"]] / total,
        }
        for r in requirements
    ]


def resume_paths(items):
    from recruit_assistant.config import ALLOWED_RESUME_EXTENSIONS

    paths = []
    for item in items:
        p = Path(item)
        if p.is_dir():
            paths.extend(sorted(f for f in p.iterdir() if f.suffix.lower() in ALLOWED_RESUME_EXTENSIONS))
        elif p.is_file():
            paths.append(p)
        else:
            raise ValueError(f"resume path {item} does not exist")
    if not paths:
        raise ValueError(f"no resumes found in {items}")
    return paths


def summarize(candidate):
    fit = candidate.fit_analysis
    d = fit.decision
    out = {
        "file": candidate.original_filename,
        "resume_id": candidate.resume_id,
        "status": fit.status,
        "route": fit.route,
        "rank": None,
        "top_30_percent": False,
        "evidence_score": None,
        "coverage": None,
        "fit_label": None,
        "required_met": None,
        "hard_gaps": [],
        "summary": fit.summary,
        "strengths": fit.strengths[:3],
        "unknowns": fit.unknowns[:3],
        "sources": [{"platform": s.platform, "url": s.url, "status": s.status} for s in candidate.sources],
    }
    if d is not None:
        out.update(
            rank=d.shortlist_rank,
            top_30_percent=d.top_30_percent,
            evidence_score=d.evidence_score,
            coverage=d.evidence_coverage,
            fit_label=d.fit_label,
            required_met=f"{d.required_criteria_met}/{d.required_criteria_total}",
            hard_gaps=d.hard_requirement_gaps,
        )
    return out


def screen(role_id, title, jd_text, resumes, consent, discover):
    from recruit_assistant.models import JobRubric, ResearchRequest, RubricCriterion
    from recruit_assistant.research import run_research
    from recruit_assistant.storage import create_job_intake_from_paths

    if discover and not consent:
        raise ValueError("--discover needs --consent-confirmed")
    rubric = None
    if role_id:
        company, public, private = load_role(role_id)
        title = public["title"]
        jd_text = role_job_description(company, public, private)
        rubric = JobRubric(
            criteria=[RubricCriterion(**c) for c in rubric_criteria(private["requirements"])],
            model=f"role {role_id} requirements; assessed by {_config.LLM_MODEL}",
        )
    job = create_job_intake_from_paths(title, jd_text, resume_paths(resumes), consent)
    run = run_research(
        job,
        ResearchRequest(
            consent_confirmed=consent,
            use_candidate_provided_links=consent,
            discover_public_profiles=discover,
        ),
        rubric,
    )
    results = sorted(
        (summarize(c) for c in run.candidates),
        key=lambda r: (r["rank"] is None, r["rank"] or 0),
    )
    return {
        "intake_id": job.job_id,
        "run_id": run.run_id,
        "role_id": role_id,
        "rubric_source": "role" if role_id else ("model" if run.rubric else "unavailable"),
        "shortlist_count": run.shortlist_count,
        "results": results,
        "slack": slack_report(title or "Uploaded role", results, run.safety_notice),
        "notice": run.safety_notice,
    }


FIT_LABELS = {
    "strong_role_alignment": "Strong demonstrated alignment",
    "potential_role_alignment": "Potential alignment — review needed",
    "insufficient_demonstrated_evidence": (
        "Insufficient demonstrated evidence — review needed"
    ),
    "analysis_unavailable": "Analysis unavailable — review needed",
}


def slack_report(job_name, results, notice):
    """Short Slack-safe report. Same scores as Streamlit."""
    lines = [
        f"*Fit review: {job_name}*",
        "Evidence-first scoring. This is not a hiring decision.",
    ]
    shortlisted = [row for row in results if row.get("top_30_percent")]
    if shortlisted:
        lines.append("*Top 30% for human review*")
        for row in shortlisted:
            score = row["evidence_score"]
            score_text = f"{score:.1f}/100" if score is not None else "n/a"
            lines.append(f"• #{row['rank']} {row['file']} — {score_text}")
    for row in results:
        lines.append(f"*{row['file']}*")
        if row["evidence_score"] is None:
            lines.append(f"• {row['summary']}")
            continue
        label = FIT_LABELS.get(row["fit_label"], row["fit_label"] or "review needed")
        lines.append(f"• Score {row['evidence_score']:.1f}/100 · {label}")
        if row["required_met"]:
            coverage = row["coverage"]
            cover = f"{coverage:.0f}%" if coverage is not None else "n/a"
            lines.append(f"• Required criteria {row['required_met']} · coverage {cover}")
        if row["hard_gaps"]:
            lines.append("• Hard gaps: " + "; ".join(row["hard_gaps"][:3]))
        if row["strengths"]:
            lines.append("• Strengths: " + "; ".join(row["strengths"][:2]))
        if row["unknowns"]:
            lines.append("• Evidence did not show: " + "; ".join(row["unknowns"][:2]))
    lines.append(notice)
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--role")
    src.add_argument("--title")
    p.add_argument("--jd-file")
    p.add_argument("--resumes", nargs="+", required=True, help="resume files or directories")
    p.add_argument("--consent-confirmed", action="store_true")
    p.add_argument("--discover", action="store_true")
    args = p.parse_args()
    if bool(args.title) != bool(args.jd_file):
        raise ValueError("--title and --jd-file go together")
    jd_text = Path(args.jd_file).read_text(encoding="utf-8") if args.jd_file else None
    resumes = [str(Path(r).resolve()) for r in args.resumes]
    # recruit_assistant reads RECRUIT_DATA_DIR at import and lives at the repo root
    os.environ.setdefault("RECRUIT_DATA_DIR", str(_config.WORK_DIR / "recruit"))
    sys.path.insert(0, str(_config.REPO))
    try:
        import recruit_assistant.research  # noqa: F401
    except ModuleNotFoundError as e:
        raise RuntimeError(f"{e}; run: pip install -r requirements-recruit.txt") from e
    return screen(args.role, args.title, jd_text, resumes, args.consent_confirmed, args.discover)


if __name__ == "__main__":
    _cli.run(main)
