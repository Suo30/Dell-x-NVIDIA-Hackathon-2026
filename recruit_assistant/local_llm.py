import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from recruit_assistant.config import (
    MAX_EVIDENCE_EXCERPT_CHARS,
    MAX_SOURCE_INPUT_CHARS,
)
from recruit_assistant.models import (
    CriterionAssessment,
    FitAnalysis,
    IdentityHints,
    SourceEvidence,
)
from recruit_assistant.models import (
    CandidateDecision,
    ExperienceCheck,
    JobRubric,
    RubricCriterion,
    SourceAssessment,
)

# Shared box model client and settings (.env, LLM_BASE_URL, LLM_MODEL, MOCK_LLM).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import _config  # noqa: E402
import _llm  # noqa: E402

# Box host or tunnel (127.0.0.1) and the sandbox route (inference.local).
LOCAL_MODEL_HOSTS = {"localhost", "127.0.0.1", "::1", "inference.local"}
MOCK_RESPONSE = {"error": "MOCK_LLM=1: recruit_assistant has no canned model output"}

SOURCE_WEIGHTS = {
    "resume": 40.0,
    "projects": 30.0,
    "github": 20.0,
    "linkedin": 10.0,
}
ASSESSMENT_SCORES = {
    "strong": 100.0,
    "moderate": 70.0,
    "weak": 35.0,
    "conflicting": 20.0,
    "unknown": None,
}
CRITERION_SCORES = {
    "demonstrated": 100.0,
    "partial": 70.0,
    "unknown": 0.0,
    "conflicting": 0.0,
}
STRONG_MATCH_SCORE = 80.0
POTENTIAL_MATCH_SCORE = 35.0
MIN_STRONG_EVIDENCE_COVERAGE = 40.0
MIN_REQUIRED_CONFIDENCE = 0.60


class LocalModelUnavailable(RuntimeError):
    pass


def _model_name() -> str:
    return _config.LLM_MODEL


def _ensure_local_endpoint() -> None:
    hostname = urlparse(_config.LLM_BASE_URL).hostname
    if hostname not in LOCAL_MODEL_HOSTS:
        raise LocalModelUnavailable(
            f"LLM_BASE_URL host {hostname!r} is not the local box model; cloud LLM calls are disabled."
        )


def complete_json(system_prompt: str, user_prompt: str) -> dict[str, Any]:
    _ensure_local_endpoint()
    result = _llm.chat_json(system_prompt, user_prompt, mock=MOCK_RESPONSE)
    if "error" in result:
        raise LocalModelUnavailable(f"Box model call failed: {result['error']}")
    return result



def _string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str) and value.strip():
        return [value]
    return []


def _evidence_polarity(evidence: list[str]) -> tuple[bool, bool]:
    negative_markers = (
        "no evidence",
        "no explicit evidence",
        "no demonstrated",
        "not demonstrated",
        "does not demonstrate",
        "lacks ",
        "lack of ",
        "unknown",
        "none",
        "no production",
    )
    positive = False
    negative = False
    for excerpt in evidence:
        normalized = " ".join(excerpt.lower().split())
        if not normalized:
            continue
        if any(marker in normalized for marker in negative_markers):
            negative = True
        else:
            positive = True
    return positive, negative


def _criterion_evidence_overlap(title: str, evidence: list[str]) -> float:
    ignored = {
        "and",
        "with",
        "using",
        "experience",
        "development",
        "skills",
        "knowledge",
        "ability",
        "required",
        "professional",
    }

    def terms(value: str) -> set[str]:
        words = {
            word[:-1] if word.endswith("s") and len(word) > 4 else word
            for word in re.findall(r"[a-z0-9]+", value.lower())
            if len(word) > 1
        }
        return words - ignored

    criterion_terms = terms(title)
    evidence_terms = terms(" ".join(evidence))
    if not criterion_terms:
        return 0.0
    return len(criterion_terms & evidence_terms) / len(criterion_terms)


def extract_identity_hints(resume_text: str) -> IdentityHints:
    result = complete_json(
        system_prompt=(
            "Extract only explicit identity-resolution hints from a resume. Return "
            "JSON only. Do not infer or return age, gender, race, ethnicity, "
            "nationality, religion, disability, health, family status, or photos."
        ),
        user_prompt=(
            "Return exactly {\"full_name\":\"... or null\",\"locations\":[\"...\"],"
            "\"roles\":[\"...\"],\"employers\":[\"...\"]}. Include only facts stated "
            "in the resume. Locations are used only to disambiguate public profiles "
            "and never for candidate scoring. Keep at most 3 values per list.\n\n"
            f"RESUME:\n{resume_text[:MAX_SOURCE_INPUT_CHARS]}"
        ),
    )
    try:
        return IdentityHints(
            full_name=(
                str(result["full_name"]).strip()
                if result.get("full_name")
                else None
            ),
            locations=[
                str(item).strip()
                for item in result.get("locations", [])[:3]
                if str(item).strip()
            ],
            roles=[
                str(item).strip()
                for item in result.get("roles", [])[:3]
                if str(item).strip()
            ],
            employers=[
                str(item).strip()
                for item in result.get("employers", [])[:3]
                if str(item).strip()
            ],
        )
    except (TypeError, ValueError) as exc:
        raise LocalModelUnavailable(
            f"Local Qwen returned invalid identity hints: {exc}"
        ) from exc


def sanitize_linkedin_evidence(page_text: str, job_description: str) -> str:
    result = complete_json(
        system_prompt=(
            "You filter professional evidence for employment decision support. "
            "Return JSON only. Keep only verifiable, job-relevant professional facts. "
            "Exclude age, dates implying age, gender, race, ethnicity, nationality, "
            "religion, disability, health, family status, photos, location unless the "
            "job explicitly requires it, and popularity metrics. Do not infer facts."
        ),
        user_prompt=(
            "Return {\"excerpt\": \"...\"}. Use concise bullet-like plain text and preserve "
            "uncertainty. If there is no relevant evidence, use an empty string.\n\n"
            f"JOB DESCRIPTION:\n{job_description[:MAX_SOURCE_INPUT_CHARS]}\n\n"
            f"PUBLIC PROFESSIONAL PAGE:\n{page_text[:MAX_SOURCE_INPUT_CHARS]}"
        ),
    )
    return str(result.get("excerpt", "")).strip()[:MAX_EVIDENCE_EXCERPT_CHARS]


def build_job_rubric(job_description: str) -> JobRubric:
    try:
        result = complete_json(
            system_prompt=(
                "You create a role-specific hiring evidence rubric from only the job "
                "description. Return JSON only. Do not introduce protected traits, "
                "personality proxies, prestige, popularity, or requirements absent from "
                "the job description."
            ),
            user_prompt=(
                "Create 4-6 job-relevant criteria. Distinguish required from preferred. "
                "Weights must reflect importance and should total 100. Keep criteria "
                "specific enough to distinguish adjacent roles (for example, software "
                "engineering experience alone does not demonstrate AI engineering). "
                "Use required=true only for qualifications explicitly described as "
                "required or essential. Do not turn every named tool into a separate "
                "gate; group tools that demonstrate one broader capability. A candidate "
                "may demonstrate a capability with an equivalent tool unless the job "
                "explicitly says a named tool is mandatory. Responsibilities describe "
                "the work but are not automatically hard requirements. "
                "Use a different descriptive criterion_id for every criterion. "
                "Return exactly:\n"
                "{\"criteria\":[{\"criterion_id\":\"backend_experience\",\"title\":\"...\","
                "\"description\":\"observable evidence expected\",\"required\":true,"
                "\"weight\":25.0}]}\n\n"
                f"JOB DESCRIPTION:\n{job_description[:MAX_SOURCE_INPUT_CHARS]}"
            ),
        )
        criteria = [
            RubricCriterion.model_validate(item)
            for item in result.get("criteria", [])
        ]
    except (LocalModelUnavailable, ValueError, TypeError) as exc:
        if isinstance(exc, LocalModelUnavailable):
            raise
        raise LocalModelUnavailable(f"Local Qwen returned an invalid rubric: {exc}") from exc

    if not criteria:
        raise LocalModelUnavailable("Local Qwen returned an empty job rubric.")
    total = sum(criterion.weight for criterion in criteria)
    if total <= 0:
        raise LocalModelUnavailable("Local Qwen returned invalid rubric weights.")
    normalized = []
    used_ids: set[str] = set()
    for index, criterion in enumerate(criteria, start=1):
        base_id = re.sub(r"[^a-z0-9]+", "_", criterion.title.lower()).strip("_")
        base_id = base_id or f"criterion_{index}"
        criterion_id = base_id
        suffix = 2
        while criterion_id in used_ids:
            criterion_id = f"{base_id}_{suffix}"
            suffix += 1
        used_ids.add(criterion_id)
        normalized.append(
            criterion.model_copy(
                update={
                    "criterion_id": criterion_id,
                    "weight": criterion.weight * 100 / total,
                }
            )
        )
    return JobRubric(criteria=normalized, model=_model_name())


def analyze_fit(
    job_description: str,
    resume_text: str | None,
    sources: list[SourceEvidence],
    rubric: JobRubric | None = None,
) -> FitAnalysis:
    source_text = "\n\n".join(
        f"{source.platform.upper()} ({source.url}):\n"
        f"{source.job_relevant_excerpt or '[no usable evidence]'}"
        for source in sources
        if source.status == "verified"
    )
    if not resume_text and not source_text:
        return FitAnalysis(
            status="insufficient_evidence",
            route="human_review_required",
            summary="No readable resume or verified professional evidence was available.",
            unknowns=["Candidate qualifications could not be assessed from supplied evidence."],
        )
    if rubric is None:
        return FitAnalysis(
            status="local_model_unavailable",
            route="human_review_required",
            summary="A role-specific rubric could not be generated by local Qwen.",
            unknowns=["Fit analysis was not performed."],
            decision=CandidateDecision(
                evidence_coverage=0,
                fit_label="analysis_unavailable",
                required_criteria_supported=False,
            ),
            model=_model_name(),
        )

    try:
        result = complete_json(
            system_prompt=(
                "You are an evidence extraction assistant, not the hiring decision-maker. "
                "Apply the supplied rubric consistently. Assess only explicit job-relevant "
                "evidence. Never use or infer protected "
                "traits or popularity. Missing information is 'unknown', never negative. "
                "Return JSON only and quote short supporting excerpts. Do not rank people. "
                "Evaluate relevance to this exact role, not generic technical strength. "
                "Refer to the person as 'the candidate' or by name; do not infer pronouns."
            ),
            user_prompt=(
                "Assess every supplied rubric criterion and each evidence source. Personal "
                "projects means role-relevant project work found in the resume or GitHub. "
                "Use unknown when a source is missing or does not establish relevance. "
                "Use demonstrated when direct professional, academic, or substantial "
                "project evidence supports the core capability; the evidence does not "
                "need to repeat every keyword in the criterion. Use partial for adjacent, "
                "limited, or incomplete evidence. Use unknown only when there is no usable "
                "evidence, and conflicting only when two supplied facts directly disagree. "
                "Return exactly:\n"
                "{\"summary\":\"...\",\"strengths\":[\"...\"],\"unknowns\":[\"...\"],"
                "\"criteria\":[{\"criterion_id\":\"...\",\"criterion\":\"...\","
                "\"required\":true,"
                "\"assessment\":\"demonstrated|partial|unknown|conflicting\","
                "\"evidence\":[\"short quote\"],\"confidence\":0.95}],"
                "\"source_assessments\":[{\"source\":\"resume|projects|github|linkedin\","
                "\"assessment\":\"strong|moderate|weak|conflicting|unknown\","
                "\"rationale\":\"role-specific reason\",\"evidence\":[\"short quote\"]}]}\n\n"
                "Confidence must agree with the assessment and evidence: use 0.90-1.00 "
                "for demonstrated criteria supported by direct evidence, 0.75-0.89 for "
                "demonstrated equivalent evidence, 0.55-0.74 for partial evidence, and "
                "0.0 for unknown criteria. Evidence entries must be short excerpts from "
                "the supplied resume or verified professional evidence, not conclusions. "
                f"JOB DESCRIPTION:\n{job_description[:MAX_SOURCE_INPUT_CHARS]}\n\n"
                f"FIXED RUBRIC:\n{rubric.model_dump_json()}\n\n"
                f"RESUME:\n{(resume_text or '[unavailable]')[:MAX_SOURCE_INPUT_CHARS]}\n\n"
                f"VERIFIED PROFESSIONAL EVIDENCE:\n{source_text[:MAX_SOURCE_INPUT_CHARS]}"
            ),
        )
        criteria = _build_criterion_assessments(
            result.get("criteria", []),
            rubric,
        )
        source_assessments = _build_source_assessments(
            result.get("source_assessments", []),
            resume_available=bool(resume_text),
            github_available=any(
                source.platform == "github" and source.status == "verified"
                for source in sources
            ),
            linkedin_available=any(
                source.platform == "linkedin" and source.status == "verified"
                for source in sources
            ),
        )
    except (LocalModelUnavailable, ValueError, TypeError) as exc:
        return FitAnalysis(
            status="local_model_unavailable",
            route="human_review_required",
            summary=str(exc),
            unknowns=["Fit analysis was not performed."],
            decision=CandidateDecision(
                evidence_coverage=0,
                fit_label="analysis_unavailable",
                required_criteria_supported=False,
            ),
            model=_model_name(),
        )

    experience_check = _experience_check(
        job_description,
        resume_text or "",
    )
    hard_requirement_gaps = _hard_requirement_gaps(experience_check)
    required = [criterion for criterion in criteria if criterion.required]
    required_supported = all(
        criterion.assessment in {"demonstrated", "partial"}
        and criterion.confidence >= MIN_REQUIRED_CONFIDENCE
        for criterion in required
    ) and not hard_requirement_gaps
    available = [
        assessment
        for assessment in source_assessments
        if assessment.score is not None
    ]
    available_weight = sum(assessment.weight for assessment in available)
    assessment_by_id = {item.criterion_id: item for item in criteria}

    def weighted_criterion_score(required_value: bool | None) -> float | None:
        selected = [
            item
            for item in rubric.criteria
            if required_value is None or item.required is required_value
        ]
        selected_weight = sum(item.weight for item in selected)
        if not selected_weight:
            return None
        return sum(
            CRITERION_SCORES[assessment_by_id[item.criterion_id].assessment]
            * assessment_by_id[item.criterion_id].confidence
            * item.weight
            for item in selected
        ) / selected_weight

    evidence_score = weighted_criterion_score(None)
    required_criteria_score = weighted_criterion_score(True)
    preferred_criteria_score = weighted_criterion_score(False)
    required_criteria_met = sum(
        item.assessment in {"demonstrated", "partial"}
        and item.confidence >= MIN_REQUIRED_CONFIDENCE
        for item in required
    )
    if evidence_score is not None and hard_requirement_gaps:
        evidence_score = min(evidence_score, 49.0)
    evidence_coverage = available_weight
    has_conflict = any(
        assessment.assessment == "conflicting" for assessment in source_assessments
    ) or any(criterion.assessment == "conflicting" for criterion in criteria)
    if (
        evidence_score is not None
        and evidence_score >= STRONG_MATCH_SCORE
        and evidence_coverage >= MIN_STRONG_EVIDENCE_COVERAGE
        and required_supported
        and not has_conflict
    ):
        fit_label = "strong_role_alignment"
        route = "advance_for_human_review"
    elif (
        evidence_score is not None
        and evidence_score >= POTENTIAL_MATCH_SCORE
        and not hard_requirement_gaps
        and not has_conflict
    ):
        fit_label = "potential_role_alignment"
        route = "human_review_required"
    else:
        fit_label = "insufficient_demonstrated_evidence"
        route = "human_review_required"

    return FitAnalysis(
        status="complete",
        route=route,
        summary=str(result.get("summary", "")).strip(),
        strengths=_string_list(result.get("strengths", [])),
        unknowns=_string_list(result.get("unknowns", [])),
        criteria=criteria,
        decision=CandidateDecision(
            evidence_score=round(evidence_score, 1) if evidence_score is not None else None,
            evidence_coverage=round(evidence_coverage, 1),
            required_criteria_score=(
                round(required_criteria_score, 1)
                if required_criteria_score is not None
                else None
            ),
            preferred_criteria_score=(
                round(preferred_criteria_score, 1)
                if preferred_criteria_score is not None
                else None
            ),
            required_criteria_met=required_criteria_met,
            required_criteria_total=len(required),
            experience_check=experience_check,
            hard_requirement_gaps=hard_requirement_gaps,
            fit_label=fit_label,
            required_criteria_supported=required_supported,
            source_assessments=source_assessments,
        ),
        model=_model_name(),
    )


def _experience_check(
    job_description: str,
    resume_text: str,
) -> ExperienceCheck | None:
    required_section = re.split(
        r"\bpreferred\s+qualifications?\b",
        job_description,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    years_pattern = re.compile(
        r"\b(\d{1,2})\+?\s*(?:years?|yrs?)\s+of"
        r"(?:\s+[a-zA-Z/-]+){0,6}?\s+experience\b",
        re.IGNORECASE,
    )
    required_years = [
        int(match.group(1))
        for match in years_pattern.finditer(required_section)
    ]
    stated_years = [
        int(match.group(1))
        for match in years_pattern.finditer(resume_text)
    ]
    required = float(max(required_years)) if required_years else None
    stated = float(max(stated_years)) if stated_years else None
    calculated = _calculate_work_history_years(resume_text)
    available = [value for value in (stated, calculated) if value is not None]
    effective = max(available) if available else None
    if required is None and effective is None:
        return None
    meets = (
        effective >= required
        if required is not None and effective is not None
        else None
    )
    details = []
    if stated is not None:
        details.append(f"resume statement: {stated:g} years")
    if calculated is not None:
        details.append(f"dated work history: {calculated:g} years")
    note = "; ".join(details) if details else "No explicit tenure evidence found."
    return ExperienceCheck(
        required_years=required,
        stated_years=stated,
        calculated_years=calculated,
        effective_years=effective,
        meets_requirement=meets,
        note=note,
    )


def _calculate_work_history_years(resume_text: str) -> float | None:
    heading = re.search(
        r"(?im)^[ \t]*(?:professional\s+|work\s+|employment\s+)?"
        r"experience(?:\s+history)?[ \t]*$",
        resume_text,
    )
    if not heading:
        return None
    section = resume_text[heading.end():]
    next_heading = re.search(
        r"(?im)^[ \t]*(?:education|projects?|skills?|certifications?|publications?|"
        r"awards?|volunteer(?:ing)?|technical\s+skills?)[ \t]*$",
        section,
    )
    if next_heading:
        section = section[:next_heading.start()]

    month_names = (
        "jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
        "jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|"
        "nov(?:ember)?|dec(?:ember)?"
    )
    range_pattern = re.compile(
        rf"(?:(?P<start_month>{month_names})[\s.,/-]*)?"
        r"(?P<start_year>(?:19|20)\d{2})\s*"
        r"(?:-|–|—|\bto\b)\s*"
        rf"(?:(?P<present>present|current|now)|"
        rf"(?:(?P<end_month>{month_names})[\s.,/-]*)?"
        r"(?P<end_year>(?:19|20)\d{2}))",
        re.IGNORECASE,
    )
    month_numbers = {
        "jan": 1,
        "feb": 2,
        "mar": 3,
        "apr": 4,
        "may": 5,
        "jun": 6,
        "jul": 7,
        "aug": 8,
        "sep": 9,
        "oct": 10,
        "nov": 11,
        "dec": 12,
    }
    now = datetime.now(timezone.utc)
    intervals: list[tuple[int, int]] = []
    for match in range_pattern.finditer(section):
        start_year = int(match.group("start_year"))
        start_month_text = match.group("start_month")
        start_month = (
            month_numbers[start_month_text[:3].lower()]
            if start_month_text
            else 1
        )
        if match.group("present"):
            end_year = now.year
            end_month = now.month
        else:
            end_year = int(match.group("end_year"))
            end_month_text = match.group("end_month")
            end_month = (
                month_numbers[end_month_text[:3].lower()]
                if end_month_text
                else 12
            )
        start_index = start_year * 12 + start_month - 1
        end_index = end_year * 12 + end_month
        if start_index < end_index <= (now.year + 1) * 12 + 12:
            intervals.append((start_index, end_index))
    if not intervals:
        return None
    intervals.sort()
    merged = [intervals[0]]
    for start, end in intervals[1:]:
        previous_start, previous_end = merged[-1]
        if start <= previous_end:
            merged[-1] = (previous_start, max(previous_end, end))
        else:
            merged.append((start, end))
    total_months = sum(end - start for start, end in merged)
    return round(total_months / 12, 1)


def _hard_requirement_gaps(
    experience_check: ExperienceCheck | None,
) -> list[str]:
    if (
        experience_check is None
        or experience_check.required_years is None
        or experience_check.effective_years is None
        or experience_check.meets_requirement is not False
    ):
        return []
    return [
        f"Requires {experience_check.required_years:g}+ years of experience; "
        f"resume evidence supports {experience_check.effective_years:g} years "
        f"({experience_check.note})."
    ]


def _build_source_assessments(
    raw_assessments: object,
    *,
    resume_available: bool,
    github_available: bool,
    linkedin_available: bool,
) -> list[SourceAssessment]:
    raw_by_source = {
        str(item.get("source")): item
        for item in raw_assessments
        if isinstance(item, dict) and item.get("source") in SOURCE_WEIGHTS
    } if isinstance(raw_assessments, list) else {}
    availability = {
        "resume": resume_available,
        "projects": resume_available or github_available,
        "github": github_available,
        "linkedin": linkedin_available,
    }
    assessments: list[SourceAssessment] = []
    for source, weight in SOURCE_WEIGHTS.items():
        raw = raw_by_source.get(source, {})
        assessment = str(raw.get("assessment", "unknown"))
        if assessment not in ASSESSMENT_SCORES or not availability[source]:
            assessment = "unknown"
        assessments.append(
            SourceAssessment(
                source=source,
                weight=weight,
                assessment=assessment,
                score=ASSESSMENT_SCORES[assessment],
                rationale=str(raw.get("rationale", "No usable evidence was available.")),
                evidence=_string_list(raw.get("evidence", [])),
            )
        )
    return assessments


def _build_criterion_assessments(
    raw_assessments: object,
    rubric: JobRubric,
) -> list[CriterionAssessment]:
    raw_items = (
        [item for item in raw_assessments if isinstance(item, dict)]
        if isinstance(raw_assessments, list)
        else []
    )
    raw_by_id = {
        str(item.get("criterion_id")): item
        for item in raw_items
    }
    valid_assessments = {"demonstrated", "partial", "unknown", "conflicting"}
    results: list[CriterionAssessment] = []
    for index, criterion in enumerate(rubric.criteria):
        raw = raw_by_id.get(criterion.criterion_id)
        if raw is None:
            raw = raw_items[index] if index < len(raw_items) else {}
        assessment = str(raw.get("assessment", "unknown"))
        if assessment not in valid_assessments:
            assessment = "unknown"
        try:
            confidence = min(1.0, max(0.0, float(raw.get("confidence", 0))))
        except (TypeError, ValueError):
            confidence = 0.0
        evidence = _string_list(raw.get("evidence", []))
        positive_evidence, negative_evidence = _evidence_polarity(evidence)
        direct_overlap = _criterion_evidence_overlap(criterion.title, evidence)
        if (
            assessment in {"unknown", "partial"}
            and positive_evidence
            and not negative_evidence
            and direct_overlap >= 0.60
        ):
            # Direct terminology overlap plus a model-selected positive excerpt
            # is explicit evidence even when a small model emits a weaker label.
            assessment = "demonstrated"
            confidence = max(confidence, 0.90)
        elif assessment == "unknown" and positive_evidence and negative_evidence:
            assessment = "conflicting"
            confidence = max(confidence, 0.75)
        elif assessment == "unknown" and positive_evidence:
            # Qwen 1.7B sometimes emits "unknown" while selecting a positive,
            # criterion-specific excerpt. Treat that contradiction as partial
            # evidence only; it can trigger review but never a strong match.
            assessment = "partial"
            confidence = max(confidence, 0.65)
        if assessment == "demonstrated" and evidence and confidence == 0.0:
            # Small local models sometimes copy the JSON schema's numeric
            # placeholder even after identifying direct supporting evidence.
            # Normalize only that internally contradictory case; unsupported
            # and unknown criteria retain zero confidence.
            confidence = 0.95
        elif assessment == "partial" and evidence and confidence == 0.0:
            confidence = 0.65
        results.append(
            CriterionAssessment(
                criterion_id=criterion.criterion_id,
                criterion=criterion.title,
                required=criterion.required,
                weight=criterion.weight,
                assessment=assessment,
                evidence=evidence,
                confidence=confidence,
            )
        )
    return results
