#!/usr/bin/env bash
# Runs every tool once with MOCK_LLM=1 on a throwaway DB.
# Each line: OK (valid JSON, no error), ERR (valid JSON with "error", e.g. a stub), FAIL (contract broken).
# STRICT=1: ERR and failed expects count as FAIL. Exception: screen_resumes ERR when recruit deps are missing.
# Exit code is the number of FAIL lines. Usage: [STRICT=1] bash tests/smoke.sh
cd "$(dirname "$0")/.."
if [ -z "${PY:-}" ]; then
  if python3 -c "" 2>/dev/null; then PY=python3; else PY=python; fi
fi
STRICT="${STRICT:-0}"
export MOCK_LLM=1
export DB_PATH="work/smoke.db"
mkdir -p work
rm -f "$DB_PATH"
FAILS=0
RECRUIT=1
"$PY" -c "import fastapi, pydantic, docx" 2>/dev/null || RECRUIT=0

# count VERDICT NAME -> applies STRICT, counts FAIL, prints the line
count() {
  local verdict="$1" name="$2"
  if [ "$STRICT" = 1 ]; then
    case "$verdict" in ERR*)
      if [ "$name" = screen_resumes ] && [ "$RECRUIT" = 0 ]; then
        verdict="$verdict (recruit deps missing, allowed)"
      else
        verdict="FAIL $verdict"
      fi;;
    esac
  fi
  case "$verdict" in FAIL*) FAILS=$((FAILS+1));; esac
  printf '%-18s %s\n' "$name" "$verdict"
}

# run NAME CMD...  -> sets $OUT to stdout
run() {
  local name="$1"; shift
  OUT="$("$PY" "$@" 2>work/smoke.stderr)"; local code=$?
  local verdict
  verdict="$(printf '%s' "$OUT" | "$PY" -c '
import json, sys
try:
    o = json.loads(sys.stdin.read())
except Exception:
    print("FAIL not JSON"); sys.exit()
if not isinstance(o, dict):
    print("FAIL not an object")
elif "error" in o:
    print("ERR  " + str(o["error"])[:70])
else:
    print("OK")
')"
  [ "$code" -ne 0 ] && verdict="FAIL exit $code"
  count "$verdict" "$name"
}

# expect NAME PYTHON_EXPR -> evaluates EXPR against $OUT (o = parsed JSON); ERR if false, FAIL under STRICT=1
expect() {
  local name="$1" expr="$2"
  local verdict
  verdict="$(printf '%s' "$OUT" | "$PY" -c '
import json, sys
try:
    o = json.loads(sys.stdin.read())
    ok = eval(sys.argv[1], {"o": o})
except Exception as e:
    print("ERR  expect raised %s: %s" % (type(e).__name__, str(e)[:50])); sys.exit()
print("OK" if ok else "ERR  expect false: " + sys.argv[1][:60])
' "$expr")"
  count "$verdict" "$name"
}

# get KEY -> value of top-level KEY in $OUT, or empty
get() { printf '%s' "$OUT" | "$PY" -c "import json,sys
try: print(json.loads(sys.stdin.read()).get('$1') or '')
except Exception: print('')"; }

run seed_db          scripts/seed_db.py --reset
run fetch_jobs       tools/fetch_jobs.py --offline
run extract_reqs     tools/extract_reqs.py --pending --limit 3
run list_jobs        tools/list_jobs.py --limit 3
run ingest_profile   tools/ingest_profile.py --name "Jordan Rivera" --text-file tests/fixtures/resume.txt --notes "I also know Docker"
CAND="$(get candidate_id)"; CAND="${CAND:-c001}"
run update_profile   tools/update_profile.py --candidate "$CAND" --note "I'd only go to Acme for a really strong offer"
run draft_role       tools/draft_role.py --company "Acme" --conversation-file tests/fixtures/conversation.txt
ROLE="$(get role_id)"; ROLE="${ROLE:-r001}"
run show_role        tools/show_role.py --role "$ROLE"
run approve_role     tools/approve_role.py --role "$ROLE"
JOB="$(get job_id)"; JOB="${JOB:-internal:$ROLE}"
run list_internal    tools/list_jobs.py --source internal
expect "  role listed"   "any(j['id'] == 'internal:$ROLE' for j in o['jobs'])"
run match_candidates tools/match_candidates.py --role "$ROLE" --limit 5
run match_jobs       tools/match_jobs.py --candidate "$CAND" --limit 50
expect "  connected"     "any(m['job_id'] == 'internal:$ROLE' for m in o['matches'])"
run apply            tools/apply.py --candidate "$CAND" --job "$JOB"
run screen_resumes   tools/screen_resumes.py --role "$ROLE" --resumes tests/fixtures/resume.txt

echo "FAIL count: $FAILS"
exit "$FAILS"
