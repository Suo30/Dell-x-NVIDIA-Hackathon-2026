"""SQLite access. Owner: D.

    connect() -> sqlite3.Connection
        Opens DB_PATH, row_factory = sqlite3.Row, runs db/schema.sql
        (all CREATE IF NOT EXISTS, so safe every time), returns the connection.
    now() -> str
        UTC ISO-8601 timestamp for created/updated/first_seen columns.
    next_id(conn, table, prefix) -> str
        Next sequential id for candidates ("c") or roles ("r"), e.g. "c031".
        The only way new ids are made.

JSON columns (*_json) hold json.dumps() strings; callers json.loads() them.
"""
import sqlite3
from datetime import datetime, timezone

import _config

_ID_TABLES = {"candidates", "roles"}


def connect():
    path = _config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.executescript(_config.SCHEMA_PATH.read_text(encoding="utf-8"))
    return conn


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def next_id(conn, table, prefix):
    if table not in _ID_TABLES:
        raise RuntimeError(f"next_id: table {table!r} is not one of {sorted(_ID_TABLES)}")
    top = 0
    # Non-numeric suffix raises ValueError: corrupt id
    for (rid,) in conn.execute(f"SELECT id FROM {table} WHERE id LIKE ?", (prefix + "%",)):
        top = max(top, int(rid[len(prefix):]))
    return f"{prefix}{top + 1:03d}"
