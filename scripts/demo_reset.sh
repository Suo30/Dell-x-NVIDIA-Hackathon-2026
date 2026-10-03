#!/usr/bin/env bash
# Reset the DB to the demo start state. Owner: D.
# First run or --rebuild: seed, load snapshots, extract with the LIVE model (minutes), save work/demo_start.db.
# Later runs: copy work/demo_start.db over DB_PATH (seconds). Never saves a mock-extracted DB.
# Usage: bash scripts/demo_reset.sh [--rebuild]
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-python3}"
DB="$("$PY" -c 'import sys; sys.path.insert(0, "tools"); import _config; print(_config.DB_PATH.as_posix())')"
MOCK="$("$PY" -c 'import sys; sys.path.insert(0, "tools"); import _config; print(int(_config.MOCK))')"
SAVED=work/demo_start.db
mkdir -p work

# step TOOL ARGS...: run a tool, print its JSON, stop if it reports an error; output in $OUT
step() {
  OUT="$("$PY" "$@")"
  echo "$OUT"
  if ! printf '%s' "$OUT" | "$PY" -c 'import json, sys; sys.exit("error" in json.load(sys.stdin))'; then
    echo "demo reset FAILED at $1" >&2
    exit 1
  fi
}

if [ "${1:-}" = "--rebuild" ] || [ ! -f "$SAVED" ]; then
  step scripts/seed_db.py --reset
  step tools/fetch_jobs.py --offline
  step tools/extract_reqs.py --pending --limit 100
  FAILED="$(printf '%s' "$OUT" | "$PY" -c 'import json, sys; print(len(json.load(sys.stdin)["failed"]))')"
  if [ "$FAILED" != 0 ]; then echo "extract_reqs failed for $FAILED jobs (see failed above)"; fi
  if [ "$MOCK" = 1 ]; then
    echo "MOCK_LLM=1: demo DB built but NOT saved"
  else
    cp "$DB" "$SAVED"
    echo "saved $SAVED"
  fi
else
  cp "$SAVED" "$DB"
fi
"$PY" tools/list_jobs.py --limit 1
echo "demo reset done"
