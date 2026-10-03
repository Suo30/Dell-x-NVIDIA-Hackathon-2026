import hashlib
import mimetypes
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from recruit_assistant.config import JOBS_DIR
from recruit_assistant.extraction import (
    extract_embedded_professional_links,
    extract_professional_links,
    extract_resume_text,
    text_hash,
    write_extracted_text,
)
from recruit_assistant.models import JobIntake, JobSummary, ResumeRecord, utc_now_iso
from recruit_assistant.validation import (
    validate_job_description,
    validate_job_name,
    validate_resume_count,
    validate_resume_file,
)


def _job_dir(job_id: str) -> Path:
    return JOBS_DIR / job_id


def _manifest_path(job_id: str) -> Path:
    return _job_dir(job_id) / "manifest.json"


def _read_manifest(job_id: str) -> JobIntake:
    path = _manifest_path(job_id)
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found.",
        )
    return JobIntake.model_validate_json(path.read_text(encoding="utf-8"))


def _write_manifest(job: JobIntake) -> None:
    job_dir = _job_dir(job.job_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    _manifest_path(job.job_id).write_text(
        job.model_dump_json(indent=2),
        encoding="utf-8",
    )


async def create_job_intake(
    job_name: str,
    job_description: str,
    resumes: list[UploadFile],
    professional_research_consent: bool = False,
) -> JobIntake:
    files = [
        (upload.filename, upload.content_type, await upload.read())
        for upload in resumes
    ]
    return store_job_intake(
        job_name,
        job_description,
        files,
        professional_research_consent=professional_research_consent,
    )


def create_job_intake_from_paths(
    job_name: str,
    job_description: str,
    paths: list[Path],
    professional_research_consent: bool = False,
) -> JobIntake:
    files = [
        (path.name, mimetypes.guess_type(path.name)[0], path.read_bytes())
        for path in paths
    ]
    return store_job_intake(
        job_name,
        job_description,
        files,
        professional_research_consent=professional_research_consent,
    )


def store_job_intake(
    job_name: str,
    job_description: str,
    files: list[tuple[str | None, str | None, bytes]],
    professional_research_consent: bool = False,
) -> JobIntake:
    """files: (filename, content_type, content) per resume."""
    validated_name = validate_job_name(job_name)
    validated_description = validate_job_description(job_description)
    validate_resume_count(files)

    job_id = str(uuid.uuid4())
    created_at = utc_now_iso()
    job_dir = _job_dir(job_id)
    resumes_dir = job_dir / "resumes"
    resumes_dir.mkdir(parents=True, exist_ok=True)

    resume_records: list[ResumeRecord] = []

    for filename, content_type, content in files:
        extension = validate_resume_file(filename, content_type, content)
        content_hash = hashlib.sha256(content).hexdigest()
        resume_id = str(uuid.uuid4())
        stored_filename = f"{resume_id}{extension}"
        stored_path = resumes_dir / stored_filename
        stored_path.write_bytes(content)

        parsing_status = "complete"
        parsing_error = None
        extracted_text_path = None
        extracted_text_hash = None
        extracted_links: list[str] = []
        try:
            extracted_text = extract_resume_text(content, extension)
            extracted_text_path = write_extracted_text(
                job_dir, resume_id, extracted_text
            )
            extracted_text_hash = text_hash(extracted_text)
            extracted_links = sorted(
                set(extract_professional_links(extracted_text))
                | set(extract_embedded_professional_links(content, extension))
            )
        except (ValueError, OSError) as exc:
            parsing_status = "failed"
            parsing_error = str(exc)

        resume_records.append(
            ResumeRecord(
                resume_id=resume_id,
                original_filename=filename or stored_filename,
                stored_filename=stored_filename,
                content_type=content_type,
                size_bytes=len(content),
                content_hash=content_hash,
                uploaded_at=utc_now_iso(),
                parsing_status=parsing_status,
                parsing_error=parsing_error,
                text_path=extracted_text_path,
                text_hash=extracted_text_hash,
                extracted_links=extracted_links,
            )
        )

    job = JobIntake(
        job_id=job_id,
        job_name=validated_name,
        job_description=validated_description,
        created_at=created_at,
        resume_count=len(resume_records),
        resumes=resume_records,
        professional_research_consent=professional_research_consent,
    )
    _write_manifest(job)
    return job


def get_job(job_id: str) -> JobIntake:
    return _read_manifest(job_id)


def get_resume_text(job_id: str, resume: ResumeRecord) -> str | None:
    if not resume.text_path:
        return None
    path = _job_dir(job_id) / resume.text_path
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def write_research_run(job_id: str, run_id: str, payload: str) -> None:
    research_dir = _job_dir(job_id) / "research"
    research_dir.mkdir(parents=True, exist_ok=True)
    (research_dir / f"{run_id}.json").write_text(payload, encoding="utf-8")


def list_jobs() -> list[JobSummary]:
    if not JOBS_DIR.exists():
        return []

    jobs: list[JobSummary] = []
    for manifest_path in sorted(JOBS_DIR.glob("*/manifest.json")):
        job = JobIntake.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        jobs.append(
            JobSummary(
                job_id=job.job_id,
                job_name=job.job_name,
                job_description=job.job_description,
                created_at=job.created_at,
                resume_count=job.resume_count,
            )
        )

    jobs.sort(key=lambda item: item.created_at, reverse=True)
    return jobs
