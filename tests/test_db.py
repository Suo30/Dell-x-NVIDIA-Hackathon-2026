from datetime import datetime, timedelta

import pytest

import _config
import _db


@pytest.fixture
def conn(tmp_db):
    c = _db.connect()
    yield c
    c.close()


def _add_candidate(conn, cid):
    conn.execute(
        "INSERT INTO candidates (id, name, profile_json, updated) VALUES (?, ?, ?, ?)",
        (cid, "x", "{}", _db.now()),
    )
    conn.commit()


def test_connect_creates_missing_dir_and_tables(tmp_path, monkeypatch):
    path = tmp_path / "missing" / "dir" / "a.db"
    monkeypatch.setattr(_config, "DB_PATH", path)
    c = _db.connect()
    try:
        names = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY 1")]
    finally:
        c.close()
    assert path.is_file()
    assert names == ["applications", "candidates", "jobs", "matches", "roles"]


def test_connect_twice_keeps_rows(tmp_db):
    c = _db.connect()
    try:
        _add_candidate(c, "c001")
    finally:
        c.close()
    c = _db.connect()
    try:
        rows = c.execute("SELECT id FROM candidates").fetchall()
    finally:
        c.close()
    assert [r["id"] for r in rows] == ["c001"]


def test_now_is_utc_iso():
    ts = datetime.fromisoformat(_db.now())
    assert ts.utcoffset() == timedelta(0)


def test_next_id_empty(conn):
    assert _db.next_id(conn, "candidates", "c") == "c001"


def test_next_id_after_gap(conn):
    _add_candidate(conn, "c001")
    _add_candidate(conn, "c007")
    assert _db.next_id(conn, "candidates", "c") == "c008"


def test_next_id_tables_independent(conn):
    _add_candidate(conn, "c001")
    assert _db.next_id(conn, "roles", "r") == "r001"


def test_next_id_rejects_other_tables(conn):
    with pytest.raises(RuntimeError, match="jobs"):
        _db.next_id(conn, "jobs", "j")
