#!/usr/bin/env bash
# Laptop gate before deploying to the box. Each step prints PASS or FAIL.
# Offline by default (MOCK_LLM, temp DBs, app.db untouched). --live also hits
# the real model through the tunnel: ssh -L 8000:127.0.0.1:8000 dell@172.20.65.171
# Usage: bash scripts/check_local.sh [--live]
# Exit code is the number of failed steps.
cd "$(dirname "$0")/.."
LIVE=0
[ "${1:-}" = "--live" ] && LIVE=1

if [ -z "${PY:-}" ]; then
  for c in .venv/Scripts/python .venv/bin/python python3 python; do
    if "$c" -c "" 2>/dev/null; then PY="$c"; break; fi
  done
fi
export PY
mkdir -p work
FAILS=0

step() {
  local name="$1"; shift
  if "$@" >work/check_local.log 2>&1; then
    printf 'PASS  %s\n' "$name"
  else
    printf 'FAIL  %s (output below)\n' "$name"
    sed 's/^/      /' work/check_local.log | tail -25
    FAILS=$((FAILS+1))
  fi
}

mock_selfcheck() {
  MOCK_LLM=1 "$PY" tools/_llm.py | "$PY" -c 'import json,sys; o=json.load(sys.stdin); sys.exit(0 if o["ok"] else 1)'
}

live_selfcheck() {
  out="$(MOCK_LLM=0 "$PY" tools/_llm.py)"
  echo "$out"
  printf '%s' "$out" | "$PY" -c 'import json,sys; o=json.load(sys.stdin); print("seconds:", o["seconds"]); sys.exit(0 if o["ok"] else 1)'
}

echo "python: $PY ($("$PY" --version 2>&1))"
step "python >= 3.10"            "$PY" -c 'import sys; sys.exit(sys.version_info < (3, 10))'
step "pytest installed"          "$PY" -c 'import pytest'
step "unit tests (pytest -q)"    "$PY" -m pytest -q
step "smoke (MOCK_LLM=1, STRICT)" env STRICT=1 bash tests/smoke.sh
step "skill files lint"          "$PY" scripts/check_skills.py
step "_llm self-check (mock)"    mock_selfcheck
step "candidates match generator" "$PY" -m pytest -q tests/test_seed.py -k committed_files

if [ "$LIVE" = 1 ]; then
  before=$FAILS
  step "tunnel up (GET /models)" curl -sf -m 5 http://127.0.0.1:8000/v1/models
  if [ "$FAILS" -gt "$before" ]; then
    echo "      tunnel down: open it, then rerun with --live. Remaining live steps not run."
  else
    step "_llm self-check (live)" live_selfcheck
    step "live tests"             env LLM_LIVE=1 MOCK_LLM=0 "$PY" -m pytest -m live -q -rs
  fi
fi

echo "FAILED steps: $FAILS"
exit "$FAILS"
