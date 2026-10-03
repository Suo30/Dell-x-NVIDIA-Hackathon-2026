"""Candidate: job description -> requirements_json (6.4) via the model.

Contract (MASTER_CONTEXT section 8):
    extract_reqs.py [--pending] [--limit 20]
    -> {"processed": n, "failed": [...]}
Owner: B
"""
import argparse

import _cli


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--pending", action="store_true", help="only jobs with requirements_json IS NULL")
    p.add_argument("--limit", type=int, default=20)
    args = p.parse_args()
    return {"error": "not implemented: extract_reqs"}


if __name__ == "__main__":
    _cli.run(main)
