"""SQLite access. Owner: D.

    connect() -> sqlite3.Connection
        Opens DB_PATH, row_factory = sqlite3.Row, runs db/schema.sql
        (all CREATE IF NOT EXISTS, so safe every time), returns the connection.
    now() -> str
        UTC ISO-8601 timestamp for created/updated/first_seen columns.

JSON columns (*_json) hold json.dumps() strings; callers json.loads() them.
"""
import sqlite3
from datetime import datetime, timezone

import _config


def connect():
    _config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_config.DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.executescript(_config.SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()
    return conn


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
