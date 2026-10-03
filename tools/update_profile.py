"""Candidate: one chat statement -> profile changes (skills, prefs, visa, location, notes).

Contract (MASTER_CONTEXT section 8):
    update_profile.py --candidate ID --note "I'd only work at Acme for a great offer"
    -> {"candidate_id", "changes": [...]}
Owner: D
"""
import argparse

import _cli


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--candidate", required=True)
    p.add_argument("--note", required=True)
    args = p.parse_args()
    return {"error": "not implemented: update_profile"}


if __name__ == "__main__":
    _cli.run(main)
