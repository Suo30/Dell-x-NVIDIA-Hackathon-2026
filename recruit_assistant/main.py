from typing import Annotated

from fastapi import FastAPI, File, Form, UploadFile

from recruit_assistant import __version__
from recruit_assistant.models import (
    HealthResponse,
    IntakeResponse,
    JobIntake,
    JobSummary,
    ResearchRequest,
    ResearchResponse,
)
from recruit_assistant.research import run_research
from recruit_assistant.storage import create_job_intake, get_job, list_jobs

app = FastAPI(
    title="Evidence-First Recruiting Assistant",
    description=(
        "Local-first intake and consent-gated professional evidence research. "
        "Qwen inference runs through a localhost-only endpoint."
    ),
    version=__version__,
)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(version=__version__)


@app.post("/jobs/intake", response_model=IntakeResponse, status_code=201)
async def intake_job(
    job_name: Annotated[str, Form()],
    job_description: Annotated[str, Form()],
    resumes: Annotated[list[UploadFile], File()],
    professional_research_consent: Annotated[bool, Form()] = False,
) -> IntakeResponse:
    """
    Create a new job intake session.

    - **job_name**: Short title for the role
    - **job_description**: Full job description / requirements
    - **resumes**: 1 to 20 resume files (.pdf, .docx, .doc, .txt)
    """
    job = await create_job_intake(
        job_name,
        job_description,
        resumes,
        professional_research_consent=professional_research_consent,
    )
    return IntakeResponse(job=job)


@app.get("/jobs", response_model=list[JobSummary])
def get_jobs() -> list[JobSummary]:
    return list_jobs()


@app.get("/jobs/{job_id}", response_model=JobIntake)
def get_job_by_id(job_id: str) -> JobIntake:
    return get_job(job_id)


@app.post("/jobs/{job_id}/research", response_model=ResearchResponse)
def research_job(job_id: str, request: ResearchRequest) -> ResearchResponse:
    """
    Suggest corroborated public profiles for identity review, research
    candidate-provided or manager-confirmed profiles, then use local Qwen to
    prepare evidence-based decision support.

    Name-only matches and unconfirmed suggestions are excluded from analysis.
    """
    job = get_job(job_id)
    run = run_research(job, request)
    return ResearchResponse(run=run)
