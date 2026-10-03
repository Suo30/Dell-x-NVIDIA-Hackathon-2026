import os
from pathlib import Path

DATA_DIR = Path(".data")
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

# Qwen is served locally through an OpenAI-compatible endpoint (NIM, vLLM,
# llama.cpp, or another local runtime). No cloud LLM endpoint is supported.
LOCAL_LLM_BASE_URL = os.getenv("LOCAL_LLM_BASE_URL", "http://127.0.0.1:8001/v1")
LOCAL_LLM_MODEL = os.getenv("LOCAL_LLM_MODEL", "qwen")
LOCAL_LLM_TIMEOUT_SECONDS = float(os.getenv("LOCAL_LLM_TIMEOUT_SECONDS", "120"))

WEB_REQUEST_TIMEOUT_SECONDS = float(os.getenv("WEB_REQUEST_TIMEOUT_SECONDS", "20"))
MAX_SOURCE_INPUT_CHARS = 30_000
MAX_EVIDENCE_EXCERPT_CHARS = 8_000
USER_AGENT = "EvidenceFirstRecruitingAssistant/0.2"
