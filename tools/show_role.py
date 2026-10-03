"""Employer: show a role.

Contract (MASTER_CONTEXT section 8):
    show_role.py --role ID
    -> {"role_id", "public", "private", "status"}
Owner: C
"""
import argparse

import _cli


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--role", required=True)
    args = p.parse_args()
    return {"error": "not implemented: show_role"}


if __name__ == "__main__":
    _cli.run(main)
