"""Candidate: record an in-app application (never submits to an external ATS).

Contract (MASTER_CONTEXT section 8):
    apply.py --candidate ID --job ID
    -> {"application": {"job_id", "candidate_id", "status": "submitted"}}
Owner: B
"""
import argparse

import _cli


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--candidate", required=True)
    p.add_argument("--job", required=True)
    args = p.parse_args()
    return {"error": "not implemented: apply"}


if __name__ == "__main__":
    _cli.run(main)
