"""STRETCH ONLY: suggest resume bullet rewrites for one job. Do not start before 16:00 freeze is safe.

Contract (MASTER_CONTEXT section 8):
    tailor.py --candidate ID --job ID
    -> {"suggestions": [...]}
Owner: stretch, unowned
"""
import argparse

import _cli


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--candidate", required=True)
    p.add_argument("--job", required=True)
    args = p.parse_args()
    return {"error": "not implemented: tailor"}


if __name__ == "__main__":
    _cli.run(main)
