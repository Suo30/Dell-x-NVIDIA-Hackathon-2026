"""Employer: show a role.

Contract (MASTER_CONTEXT section 8):
    show_role.py --role ID
    -> {"role_id", "company", "paid", "status", "public", "private", "job_id"}
job_id is "internal:ID" once approved, else null.
Owner: C
"""
import argparse
import json

import _cli
import _db


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--role", required=True)
    args = p.parse_args()

    conn = _db.connect()
    try:
        row = conn.execute("SELECT * FROM roles WHERE id = ?", (args.role,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise ValueError(f"role {args.role} not found")

    return {
        "role_id": row["id"],
        "company": row["company"],
        "paid": bool(row["paid"]),
        "status": row["status"],
        "public": json.loads(row["public_json"]),
        "private": json.loads(row["private_json"]),
        "job_id": f"internal:{row['id']}" if row["status"] == "approved" else None,
    }


if __name__ == "__main__":
    _cli.run(main)
