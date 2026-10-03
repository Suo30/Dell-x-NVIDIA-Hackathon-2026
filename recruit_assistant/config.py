import os
from pathlib import Path

# Relative to the working directory; tools/screen_resumes.py points it at work/recruit.
DATA_DIR = Path(os.getenv("RECRUIT_DATA_DIR", ".data"))
JOBS_DIR = DATA_DIR / "jobs"

MIN_RESUMES = 1
MAX_RESUMES = 20
MAX_JOB_NAME_LENGTH = 200
MAX_JOB_DESCRIPTION_LENGTH = 50_000
MAX_RESUME_BYTES = 10 * 1024 * 1024  # 10 MB per file

ALLOWED_RESUME_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt"}
ALLOWED_RESUME_CONTENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "text/plain",
}

# Model settings come from tools/_config.py (LLM_BASE_URL, LLM_MODEL, MOCK_LLM).

WEB_REQUEST_TIMEOUT_SECONDS = float(os.getenv("WEB_REQUEST_TIMEOUT_SECONDS", "20"))
MAX_SOURCE_INPUT_CHARS = 30_000
MAX_EVIDENCE_EXCERPT_CHARS = 8_000
USER_AGENT = "EvidenceFirstRecruitingAssistant/0.2"
