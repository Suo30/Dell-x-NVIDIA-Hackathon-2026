"""Candidate: pull postings from ATS APIs (section 10) into jobs; snapshot every fetch.

Contract (MASTER_CONTEXT section 8):
    fetch_jobs.py [--source greenhouse|lever|workday|all] [--offline]
    -> {"new": [{"id", "company", "title", "url"}]}
Owner: B
"""
import argparse

import _cli


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--source", default="all", choices=["greenhouse", "lever", "workday", "all"])
    p.add_argument("--offline", action="store_true", help="read data/snapshots instead of the network")
    args = p.parse_args()
    return {"error": "not implemented: fetch_jobs"}


if __name__ == "__main__":
    _cli.run(main)
