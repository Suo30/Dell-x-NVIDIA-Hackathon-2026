"""Employer: approve a draft role, apply edits, publish it as job internal:{role_id}.

Contract (MASTER_CONTEXT section 8):
    approve_role.py --role ID [--edits-file PATH]
    -> {"role_id", "job_id": "internal:ID", "status": "approved"}
Owner: C
"""
import argparse

import _cli


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--role", required=True)
    p.add_argument("--edits-file", help="JSON with any of {public, private} keys to merge")
    args = p.parse_args()
    return {"error": "not implemented: approve_role"}


if __name__ == "__main__":
    _cli.run(main)
