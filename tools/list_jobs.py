"""Candidate: list jobs in the DB.

Contract (MASTER_CONTEXT section 8):
    list_jobs.py [--limit 10] [--source internal]
    -> {"jobs": [...]}
Owner: B
"""
import argparse

import _cli


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--source")
    args = p.parse_args()
    return {"error": "not implemented: list_jobs"}


if __name__ == "__main__":
    _cli.run(main)
