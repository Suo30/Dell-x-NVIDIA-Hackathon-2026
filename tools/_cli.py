"""Shared entry point so every tool honors the contract:
exit 0, exactly one JSON object on stdout, {"error": "..."} on failure.
Diagnostics (tracebacks, argparse usage) go to stderr only.

Usage at the bottom of each tool:
    if __name__ == "__main__":
        _cli.run(main)      # main() returns a dict
"""
import json
import sys
import traceback


def emit(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def run(main):
    try:
        result = main()
    except SystemExit as e:
        if e.code in (0, None):  # --help
            raise
        result = {"error": "bad arguments, see stderr for usage"}
    except Exception as e:
        traceback.print_exc(file=sys.stderr)
        result = {"error": f"{type(e).__name__}: {e}"}
    if not isinstance(result, dict):
        result = {"error": f"tool returned {type(result).__name__}, expected dict"}
    emit(result)
    sys.exit(0)
