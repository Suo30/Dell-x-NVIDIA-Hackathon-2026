"""Employer: rank all candidates against a role's private context (uses _match.evaluate).

Contract (MASTER_CONTEXT section 8):
    match_candidates.py --role ID [--limit 10]
    -> {"shortlist": [{"candidate_id", "name", "score", "route", "flags", "gaps_text", "top_evidence"}]}
Owner: C
"""
import argparse

import _cli


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--role", required=True)
    p.add_argument("--limit", type=int, default=10)
    args = p.parse_args()
    return {"error": "not implemented: match_candidates"}


if __name__ == "__main__":
    _cli.run(main)
