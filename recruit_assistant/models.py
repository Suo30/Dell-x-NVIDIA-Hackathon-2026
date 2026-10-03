from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ResumeRecord(BaseModel):
    resume_id: str
    original_filename: str
    stored_filename: str
    content_type: str | None
    size_bytes: int
    content_hash: str
    uploaded_at: str
    parsing_status: Literal["pending", "complete", "failed"] = "pending"
    parsing_error: str | None = None
    text_path: str | None = None
    text_hash: str | None = None
    extracted_links: list[str] = Field(default_factory=list)


class JobIntake(BaseModel):
    job_id: str
    job_name: str
    job_description: str
    created_at: str
    resume_count: int
    resumes: list[ResumeRecord]
    professional_research_consent: bool = False


class JobSummary(BaseModel):
    job_id: str
    job_name: str
    job_description: str
    created_at: str
    resume_count: int


class IntakeResponse(BaseModel):
    message: str = "Job intake saved successfully."
    job: JobIntake


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str


class ErrorResponse(BaseModel):
    detail: str
    field: str | None = Field(default=None)


class CandidateProfileInput(BaseModel):
    resume_id: str
    github_url: HttpUrl | None = None
    linkedin_url: HttpUrl | None = None
    identity_confirmed: bool = False

    @model_validator(mode="after")
    def require_confirmation_for_supplied_links(self) -> "CandidateProfileInput":
        if (self.github_url or self.linkedin_url) and not self.identity_confirmed:
            raise ValueError(
                "identity_confirmed must be true for manager-supplied profile URLs"
            )
        return self


class ResearchRequest(BaseModel):
    consent_confirmed: bool
    use_candidate_provided_links: bool = True
    discover_public_profiles: bool = True
    candidates: list[CandidateProfileInput] = Field(default_factory=list)


class IdentityHints(BaseModel):
    full_name: str | None = None
    locations: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    employers: list[str] = Field(default_factory=list)


class SourceEvidence(BaseModel):
    platform: Literal["github", "linkedin"]
    url: str
    retrieved_at: str
    content_hash: str | None = None
    status: Literal["verified", "unavailable", "needs_identity_review"]
    identity_basis: Literal["resume_link", "manager_confirmed", "unverified"]
    match_signals: list[str] = Field(default_factory=list)
    job_relevant_excerpt: str | None = None
    error: str | None = None


class RubricCriterion(BaseModel):
    criterion_id: str
    title: str
    description: str
    required: bool
    weight: float = Field(gt=0, le=100)


class JobRubric(BaseModel):
    criteria: list[RubricCriterion]
    model: str


class CriterionAssessment(BaseModel):
    criterion_id: str | None = None
    criterion: str
    required: bool = False
    weight: float = Field(default=0, ge=0, le=100)
    assessment: Literal["demonstrated", "partial", "unknown", "conflicting"]
    evidence: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


class SourceAssessment(BaseModel):
    source: Literal["resume", "projects", "github", "linkedin"]
    weight: float = Field(gt=0, le=100)
    assessment: Literal["strong", "moderate", "weak", "conflicting", "unknown"]
    score: float | None = Field(default=None, ge=0, le=100)
    rationale: str
    evidence: list[str] = Field(default_factory=list)


class ExperienceCheck(BaseModel):
    required_years: float | None = Field(default=None, ge=0)
    stated_years: float | None = Field(default=None, ge=0)
    calculated_years: float | None = Field(default=None, ge=0)
    effective_years: float | None = Field(default=None, ge=0)
    meets_requirement: bool | None = None
    note: str


class CandidateDecision(BaseModel):
    evidence_score: float | None = Field(default=None, ge=0, le=100)
    evidence_coverage: float = Field(ge=0, le=100)
    required_criteria_score: float | None = Field(default=None, ge=0, le=100)
    preferred_criteria_score: float | None = Field(default=None, ge=0, le=100)
    required_criteria_met: int = Field(default=0, ge=0)
    required_criteria_total: int = Field(default=0, ge=0)
    experience_check: ExperienceCheck | None = None
    hard_requirement_gaps: list[str] = Field(default_factory=list)
    fit_label: Literal[
        "strong_role_alignment",
        "potential_role_alignment",
        "insufficient_demonstrated_evidence",
        "analysis_unavailable",
    ]
    required_criteria_supported: bool
    source_assessments: list[SourceAssessment] = Field(default_factory=list)
    top_30_percent: bool = False
    shortlist_rank: int | None = None
    notice: str = (
        "Evidence-based decision support only; this is not a final employment decision."
    )


class FitAnalysis(BaseModel):
    status: Literal["complete", "local_model_unavailable", "insufficient_evidence"]
    route: Literal["advance_for_human_review", "human_review_required"]
    summary: str
    strengths: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    criteria: list[CriterionAssessment] = Field(default_factory=list)
    decision: CandidateDecision | None = None
    model: str | None = None


class CandidateResearch(BaseModel):
    resume_id: str
    original_filename: str
    sources: list[SourceEvidence]
    fit_analysis: FitAnalysis


class ResearchRun(BaseModel):
    run_id: str
    job_id: str
    created_at: str
    policy_version: str = "evidence-first-v1"
    safety_notice: str = (
        "Decision support only. Unknown or missing evidence is not negative evidence; "
        "a person remains responsible for every employment decision."
    )
    rubric: JobRubric | None = None
    shortlist_count: int = 0
    candidates: list[CandidateResearch]


class ResearchResponse(BaseModel):
    message: str = "Professional evidence research completed."
    run: ResearchRun
