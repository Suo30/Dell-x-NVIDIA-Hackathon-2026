"""Candidate: score every job with requirements against one candidate; store in matches.

Contract (MASTER_CONTEXT section 8):
    match_jobs.py --candidate ID [--limit 5]
    -> {"matches": [{"job_id", "company", "title", "url", "score", "route", "flags", "gaps_text", "top_evidence"}]}
Owner: B
"""
import argparse

import _cli


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--candidate", required=True)
    p.add_argument("--limit", type=int, default=5)
    args = p.parse_args()
    return {"error": "not implemented: match_jobs"}


if __name__ == "__main__":
    _cli.run(main)
