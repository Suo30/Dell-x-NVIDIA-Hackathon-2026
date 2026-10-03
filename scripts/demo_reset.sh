#!/usr/bin/env bash
# Reset the DB to the demo start state. Owner: D.
# Rebuilds from data/ only (no network): candidates + job snapshots, no roles.
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-python3}"
"$PY" scripts/seed_db.py --reset
"$PY" tools/fetch_jobs.py --offline
echo "demo reset done"
