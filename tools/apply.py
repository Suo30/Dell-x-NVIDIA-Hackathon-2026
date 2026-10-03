"""Candidate: record an in-app application.

This only writes a row to the applications table. It never contacts or submits
to an external ATS (Greenhouse, Lever or any other); the student applies there
themselves through the job url.

Contract (MASTER_CONTEXT section 8):
    apply.py --candidate ID --job ID
    -> {"application": {"job_id", "candidate_id", "status": "submitted", "created"},
        "already_applied": bool}
Applying twice returns the existing row with already_applied true.
Owner: B
"""
import argparse

import _cli
import _db


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--candidate", required=True)
    p.add_argument("--job", required=True)
    args = p.parse_args()

    conn = _db.connect()
    try:
        if conn.execute("SELECT 1 FROM candidates WHERE id = ?", (args.candidate,)).fetchone() is None:
            raise ValueError(f"candidate {args.candidate} not found")
        if conn.execute("SELECT 1 FROM jobs WHERE id = ?", (args.job,)).fetchone() is None:
            raise ValueError(f"job {args.job} not found")
        cur = conn.execute(
            "INSERT OR IGNORE INTO applications (job_id, candidate_id, status, created) "
            "VALUES (?, ?, 'submitted', ?)",
            (args.job, args.candidate, _db.now()),
        )
        already_applied = cur.rowcount == 0
        conn.commit()
        row = conn.execute(
            "SELECT job_id, candidate_id, status, created FROM applications WHERE job_id = ? AND candidate_id = ?",
            (args.job, args.candidate),
        ).fetchone()
    finally:
        conn.close()
    return {"application": dict(row), "already_applied": already_applied}


if __name__ == "__main__":
    _cli.run(main)
