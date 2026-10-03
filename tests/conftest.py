import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "scripts")]

import _config  # noqa: E402


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(_config, "DB_PATH", tmp_path / "t.db")
    return _config.DB_PATH


@pytest.fixture
def mock_llm(monkeypatch):
    monkeypatch.setattr(_config, "MOCK", True)
