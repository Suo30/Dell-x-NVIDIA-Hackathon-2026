"""Employer: approve a draft role, apply edits, publish it as job internal:{role_id}.

Contract (MASTER_CONTEXT section 8):
    approve_role.py --role ID [--edits-file PATH]
    -> {"role_id", "job_id": "internal:ID", "status": "approved", "public", "private"}

Edits file: {"public": {...}, "private": {...}}, both optional, merged into the role.
private.requirements replaces the whole list. Re-approving an approved role re-applies
edits, rewrites the job (keeping first_seen) and deletes its stale matches.
Owner: C
"""
import argparse
import json
from pathlib import Path

import _cli
import _db
import _role

EDIT_KEYS = {"public": set(_role.PUBLIC_KEYS), "private": set(_role.PRIVATE_KEYS)}


def load_edits(path):
    edits = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(edits, dict):
        raise ValueError(f"{path}: edits must be a JSON object")  # noqa: TRY004, bad user data per AGENTS.md
    unknown = sorted(set(edits) - set(EDIT_KEYS))
    if unknown:
        raise ValueError(f"{path}: unknown edit keys {unknown}; only public and private are allowed")
    for section, fields in edits.items():
        if not isinstance(fields, dict):
            raise ValueError(f"{path}: {section} must be an object")  # noqa: TRY004, bad user data per AGENTS.md
        unknown = sorted(set(fields) - EDIT_KEYS[section])
        if unknown:
            raise ValueError(f"{path}: unknown {section} keys {unknown}; expected {sorted(EDIT_KEYS[section])}")
    return edits


def apply_edits(public, private, edits):
    # Edits file is user input: both sections are optional
    public.update(edits.get("public", {}))
    private_edits = dict(edits.get("private", {}))
    if "requirements" in private_edits:
        requirements, dropped = _role.clean_requirements(private_edits["requirements"], "edits")
        if dropped:
            problems = ", ".join(f"{d['skill']} ({d['reason']})" for d in dropped)
            raise ValueError(f"edits: private.requirements has unusable entries: {problems}")
        private_edits["requirements"] = requirements
    private.update(private_edits)


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--role", required=True)
    p.add_argument("--edits-file", help="JSON with any of {public, private} keys to merge")
    args = p.parse_args()

    edits = load_edits(args.edits_file) if args.edits_file else {}
    role_id = args.role
    job_id = f"internal:{role_id}"

    conn = _db.connect()
    try:
        row = conn.execute("SELECT * FROM roles WHERE id = ?", (role_id,)).fetchone()
        if row is None:
            raise ValueError(f"role {role_id} not found")
        public, private = json.loads(row["public_json"]), json.loads(row["private_json"])
        apply_edits(public, private, edits)
        _role.validate({"public": public, "private": private}, f"role {role_id}")

        prev = conn.execute("SELECT first_seen FROM jobs WHERE id = ?", (job_id,)).fetchone()
        reapprove = row["status"] == "approved"
        if reapprove != (prev is not None):
            state = "missing" if prev is None else "already present"
            raise RuntimeError(f"role {role_id} is {row['status']!r} but job {job_id} is {state}")
        first_seen = prev["first_seen"] if reapprove else _db.now()

        requirements = [{**r, "evidence_text": r["why"]} for r in private["requirements"]]
        sponsorship = None if public["sponsorship"] is None else int(public["sponsorship"])
        conn.execute(
            "UPDATE roles SET status='approved', public_json=?, private_json=? WHERE id = ?",
            (json.dumps(public, ensure_ascii=False), json.dumps(private, ensure_ascii=False), role_id),
        )
        conn.execute(
            "INSERT OR REPLACE INTO jobs (id, source, company, title, url, location, description, role_id,"
            " requirements_json, sponsorship, clearance, pay, paid, first_seen, notified)"
            " VALUES ('internal:'||?, 'internal', ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
            (role_id, row["company"], public["title"], public["location"], public["description"], role_id,
             json.dumps(requirements, ensure_ascii=False), sponsorship, public["clearance"], public["pay"],
             row["paid"], first_seen),
        )
        if reapprove:
            conn.execute("DELETE FROM matches WHERE job_id = ?", (job_id,))
        conn.commit()
    finally:
        conn.close()

    return {"role_id": role_id, "job_id": job_id, "status": "approved", "public": public, "private": private}


if __name__ == "__main__":
    _cli.run(main)
