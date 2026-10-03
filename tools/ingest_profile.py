"""Candidate: resume text + notes -> taxonomy-mapped profile (6.2), stored in candidates.

Contract (MASTER_CONTEXT section 8):
    ingest_profile.py --name "X" --text-file PATH [--notes "..."]
    -> {"candidate_id", "skills_found", "profile"}
Owner: D
"""
import argparse

import _cli


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--name", required=True)
    p.add_argument("--text-file", required=True)
    p.add_argument("--notes", default="")
    args = p.parse_args()
    return {"error": "not implemented: ingest_profile"}


if __name__ == "__main__":
    _cli.run(main)
