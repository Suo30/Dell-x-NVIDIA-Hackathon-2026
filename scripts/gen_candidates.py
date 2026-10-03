"""Build the 30 synthetic profiles into data/candidates/*.json (no model needed).
Owner: D
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import _cli  # noqa: E402


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    pass
    args = p.parse_args()
    return {"error": "not implemented: gen_candidates"}


if __name__ == "__main__":
    _cli.run(main)
