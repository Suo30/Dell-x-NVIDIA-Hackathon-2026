"""Employer: clarified conversation -> draft role with public JD + private context (6.3).

Contract (MASTER_CONTEXT section 8):
    draft_role.py --company "X" --conversation-file PATH [--paid]
    -> {"role_id", "status": "draft", "public", "private"}
Owner: C
"""
import argparse

import _cli


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--company", required=True)
    p.add_argument("--conversation-file", required=True)
    p.add_argument("--paid", action="store_true")
    args = p.parse_args()
    return {"error": "not implemented: draft_role"}


if __name__ == "__main__":
    _cli.run(main)
