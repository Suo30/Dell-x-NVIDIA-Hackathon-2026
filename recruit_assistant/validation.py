from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from recruit_assistant.config import (
    ALLOWED_RESUME_CONTENT_TYPES,
    ALLOWED_RESUME_EXTENSIONS,
    MAX_JOB_DESCRIPTION_LENGTH,
    MAX_JOB_NAME_LENGTH,
    MAX_RESUME_BYTES,
    MAX_RESUMES,
    MIN_RESUMES,
)


def validate_job_name(job_name: str) -> str:
    name = job_name.strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Job name is required.",
        )
    if len(name) > MAX_JOB_NAME_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Job name must be at most {MAX_JOB_NAME_LENGTH} characters.",
        )
    return name


def validate_job_description(job_description: str) -> str:
    description = job_description.strip()
    if not description:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Job description is required.",
        )
    if len(description) > MAX_JOB_DESCRIPTION_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Job description must be at most "
                f"{MAX_JOB_DESCRIPTION_LENGTH} characters."
            ),
        )
    return description


def validate_resume_count(resumes: list[UploadFile]) -> None:
    count = len(resumes)
    if count < MIN_RESUMES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Upload at least {MIN_RESUMES} resume.",
        )
    if count > MAX_RESUMES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Upload at most {MAX_RESUMES} resumes.",
        )


def validate_resume_file(upload: UploadFile, content: bytes) -> str:
    filename = upload.filename or "resume"
    extension = Path(filename).suffix.lower()

    if extension not in ALLOWED_RESUME_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_RESUME_EXTENSIONS))
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Unsupported file type for '{filename}'. "
                f"Allowed extensions: {allowed}."
            ),
        )

    content_type = (upload.content_type or "").split(";")[0].strip().lower()
    if content_type and content_type not in ALLOWED_RESUME_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported content type for '{filename}': {content_type}.",
        )

    if not content:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"File '{filename}' is empty.",
        )

    if len(content) > MAX_RESUME_BYTES:
        max_mb = MAX_RESUME_BYTES // (1024 * 1024)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"File '{filename}' exceeds the {max_mb} MB limit.",
        )

    return extension
