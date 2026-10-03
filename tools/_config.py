"""Runtime settings for every tool. Stdlib only.

Reads <repo>/.env if present (real env vars win), then exposes:
    REPO, DATA_DIR, DB_PATH, LLM_BASE_URL, LLM_MODEL, MOCK
Relative DB_PATH / DATA_DIR resolve against the repo root, so tools work
no matter which directory the agent runs them from.
"""
import os
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load_dotenv(path):
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def _path(name, default):
    p = Path(os.environ.get(name) or default)
    return p if p.is_absolute() else REPO / p


_load_dotenv(REPO / ".env")

DATA_DIR = _path("DATA_DIR", "data")
DB_PATH = _path("DB_PATH", "app.db")
SCHEMA_PATH = REPO / "db" / "schema.sql"
WORK_DIR = REPO / "work"
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:8000/v1").rstrip("/")
LLM_MODEL = os.environ.get("LLM_MODEL", "nvidia/Qwen3.6-35B-A3B-NVFP4")
MOCK = os.environ.get("MOCK_LLM", "0") == "1"
