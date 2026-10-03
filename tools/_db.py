"""SQLite access. Owner: D.

    connect() -> sqlite3.Connection
        Opens DB_PATH, row_factory = sqlite3.Row, runs db/schema.sql
        (all CREATE IF NOT EXISTS, so safe every time), returns the connection.
    now() -> str
        UTC ISO-8601 timestamp for created/updated/first_seen columns.

JSON columns (*_json) hold json.dumps() strings; callers json.loads() them.
"""
import _config


def connect():
    raise NotImplementedError("_db.connect (owner: D)")


def now():
    raise NotImplementedError("_db.now (owner: D)")
