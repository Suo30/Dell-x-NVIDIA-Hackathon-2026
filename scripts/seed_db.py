"""Init the DB from db/schema.sql, load data/candidates/*.json and data/snapshots/*.json.
Owner: D
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import _cli  # noqa: E402


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--reset", action="store_true", help="delete DB_PATH first")
    args = p.parse_args()
    return {"error": "not implemented: seed_db"}


if __name__ == "__main__":
    _cli.run(main)
