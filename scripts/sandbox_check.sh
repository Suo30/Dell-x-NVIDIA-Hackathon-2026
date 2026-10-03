#!/usr/bin/env bash
# Checks the deployed workspace from INSIDE the sandbox. Runs every check.
# Exit code 1 if any FAIL. Usage: bash scripts/sandbox_check.sh  (WORKSPACE=/path to override)
WORKSPACE="${WORKSPACE:-/sandbox/.openclaw/workspace}"
REPO="$WORKSPACE/repo"
PASS=0; FAIL=0; WARN=0

pass() { PASS=$((PASS + 1)); echo "PASS  $*"; }
fail() { FAIL=$((FAIL + 1)); echo "FAIL  $*"; }
warn() { WARN=$((WARN + 1)); echo "WARN  $*"; }

# 1. python3
HAVE_PY=0
if command -v python3 >/dev/null 2>&1; then
  HAVE_PY=1
  pass "python3: $(python3 --version 2>&1) at $(command -v python3)"
else
  fail "python3 not found; every tool needs it"
fi

# 2. Workspace layout
PROBE="$WORKSPACE/.write-probe.$$"
if ( : > "$PROBE" ) 2>/dev/null; then
  rm -f "$PROBE"
  pass "$WORKSPACE is writable"
else
  fail "$WORKSPACE is not writable"
fi
if [ -d "$REPO/tools" ]; then pass "repo present at $REPO"; else fail "repo missing: no $REPO/tools/"; fi
if [ -f "$REPO/.env" ]; then pass "$REPO/.env present"; else warn "$REPO/.env missing; tools fall back to defaults"; fi
for s in role-architect career-matcher resume-screener; do
  d="$WORKSPACE/skills/$s"
  if [ -L "$d" ] || [ -L "$d/SKILL.md" ]; then
    fail "$d is a symlink; OpenClaw rejects it, rerun deploy_box.sh"
  elif [ -f "$d/SKILL.md" ]; then
    pass "skill present: $d/SKILL.md"
  else
    fail "skill missing: $d/SKILL.md"
  fi
done
if [ -f "$WORKSPACE/AGENTS.md" ]; then pass "AGENTS.md present"; else fail "AGENTS.md missing at $WORKSPACE/AGENTS.md"; fi

# 3. Smoke test (mock LLM, throwaway DB)
if [ -f "$REPO/tests/smoke.sh" ]; then
  echo "      running MOCK_LLM=1 bash tests/smoke.sh in $REPO"
  SMOKE="$(cd "$REPO" && MOCK_LLM=1 bash tests/smoke.sh 2>&1)"; rc=$?
  printf '%s\n' "$SMOKE" | sed 's/^/      | /'
  if [ $rc -eq 0 ]; then pass "smoke.sh: 0 FAIL"; else fail "smoke.sh: $rc FAIL line(s)"; fi
else
  warn "no $REPO/tests/smoke.sh, smoke test skipped"
fi

# 4. Egress to job boards (any HTTP status counts as reachable)
egress() {
  python3 - "$1" <<'PY'
import sys, urllib.request, urllib.error
url = sys.argv[1]
try:
    with urllib.request.urlopen(url, timeout=8) as r:
        print("HTTP %d" % r.status)
except urllib.error.HTTPError as e:
    print("HTTP %d" % e.code)
except Exception as e:
    print("NOCONN %s: %s" % (type(e).__name__, e))
PY
}
for url in https://boards-api.greenhouse.io/v1/boards/ https://api.lever.co/v0/postings/; do
  if [ "$HAVE_PY" -eq 0 ]; then
    fail "egress $url: skipped, no python3"
    continue
  fi
  res="$(egress "$url")"
  case "$res" in
    "HTTP 403"|"HTTP 407")
      warn "egress $url: $res, may be the sandbox proxy denying it; check \`openshell term\` on the host" ;;
    HTTP*)
      pass "egress $url: $res (reachable)" ;;
    *)
      fail "egress $url: $res. Check \`openshell term\` on the host for a blocked request" ;;
  esac
done

echo "== sandbox_check: $PASS PASS, $WARN WARN, $FAIL FAIL =="
[ "$FAIL" -eq 0 ]
