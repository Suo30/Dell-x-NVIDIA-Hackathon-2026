#!/usr/bin/env bash
# Host-side readiness checks for the Dell box. Runs on the HOST, not in the sandbox.
# Runs every check, never stops early. Exit code 1 if any FAIL.
# Usage: bash scripts/box_preflight.sh   (SANDBOX=name to override)
SANDBOX="${SANDBOX:-my-assistant}"
API="http://127.0.0.1:8000/v1"
PASS=0; FAIL=0; WARN=0

pass() { PASS=$((PASS + 1)); echo "PASS  $*"; }
fail() { FAIL=$((FAIL + 1)); echo "FAIL  $*"; }
warn() { WARN=$((WARN + 1)); echo "WARN  $*"; }
indent() { sed 's/^/      | /'; }
have() { command -v "$1" >/dev/null 2>&1; }

# 1. vLLM /v1/models
MODEL=""
if ! have curl; then
  fail "curl not installed, cannot reach $API"
elif ! have python3; then
  fail "python3 not installed on host, cannot parse $API/models"
else
  MODELS_JSON="$(curl -sS -m 10 "$API/models" 2>&1)"
  if [ $? -ne 0 ]; then
    fail "GET $API/models: $MODELS_JSON"
  else
    MODEL="$(printf '%s' "$MODELS_JSON" | python3 -c '
import json, sys
print(json.load(sys.stdin)["data"][0]["id"])' 2>/dev/null)"
    if [ -n "$MODEL" ]; then
      pass "GET $API/models -> model id: $MODEL"
    else
      fail "GET $API/models returned no model id: $(printf '%s' "$MODELS_JSON" | head -c 200)"
    fi
  fi
fi

# 2. One-token chat completion
if [ -z "$MODEL" ]; then
  fail "chat completion skipped: no model id from /v1/models"
else
  PAYLOAD="$(python3 -c '
import json, sys
print(json.dumps({"model": sys.argv[1], "max_tokens": 1,
                  "messages": [{"role": "user", "content": "Say OK"}]}))' "$MODEL")"
  CHAT_JSON="$(curl -sS -m 120 -H 'Content-Type: application/json' -d "$PAYLOAD" "$API/chat/completions" 2>&1)"
  if [ $? -ne 0 ]; then
    fail "POST $API/chat/completions: $CHAT_JSON"
  elif printf '%s' "$CHAT_JSON" | python3 -c '
import json, sys
sys.exit(0 if json.load(sys.stdin).get("choices") else 1)' 2>/dev/null; then
    pass "one-token chat completion to $MODEL"
  else
    fail "chat completion returned no choices: $(printf '%s' "$CHAT_JSON" | head -c 200)"
  fi
fi

# 3. Port 8000 bind address
if ! have ss; then
  fail "ss not installed, cannot check port 8000 bind address"
else
  ADDRS="$(ss -ltn 2>/dev/null | awk '$4 ~ /:8000$/ {print $4}')"
  if [ -z "$ADDRS" ]; then
    fail "nothing listening on port 8000 (ss -ltn)"
  elif printf '%s\n' "$ADDRS" | grep -qvE '^(127\.0\.0\.1|\[::1\]):8000$'; then
    pass "port 8000 bound to: $(echo $ADDRS)"
  else
    warn "port 8000 bound only to $(echo $ADDRS); the sandbox reaches vLLM via host.openshell.internal, so bind 0.0.0.0"
  fi
fi

# 4. openshell inference route (local-only build)
if ! have openshell; then
  fail "openshell not installed"
else
  INF="$(openshell inference get 2>&1)"; rc=$?
  echo "      openshell inference get:"
  printf '%s\n' "$INF" | indent
  # "openai-compatible" is the local vLLM provider type, not a cloud provider
  CLOUD="$(printf '%s' "$INF" | tr 'A-Z' 'a-z' | sed 's/openai[- _]compatible//g' \
    | grep -oE 'nvidia[ _-]?endpoints?|integrate\.api\.nvidia\.com|build\.nvidia\.com|openai|anthropic' | sort -u | tr '\n' ' ' | sed 's/ $//')"
  if [ $rc -ne 0 ]; then
    fail "openshell inference get exited $rc"
  elif [ -n "$CLOUD" ]; then
    warn "inference route mentions a cloud provider ($CLOUD); this build must be local-only"
  else
    pass "openshell inference get shows no cloud provider"
  fi
fi

# 5. Slack channel on the sandbox
if ! have nemoclaw; then
  fail "nemoclaw not installed"
else
  CH="$(nemoclaw "$SANDBOX" channels list 2>&1)"; rc=$?
  echo "      nemoclaw $SANDBOX channels list:"
  printf '%s\n' "$CH" | indent
  if [ $rc -ne 0 ]; then
    fail "nemoclaw $SANDBOX channels list exited $rc"
  elif printf '%s' "$CH" | grep -qi slack; then
    pass "Slack channel listed for $SANDBOX"
  else
    warn "no Slack channel listed for $SANDBOX"
  fi
fi

# 6. Firewall
if ! have ufw; then
  pass "ufw not installed"
else
  UFW="$(ufw status 2>&1)"
  if printf '%s' "$UFW" | grep -qi 'root'; then
    warn "ufw status needs root; rerun this script with sudo to check the firewall"
  elif printf '%s' "$UFW" | grep -qi 'status: active'; then
    warn "ufw is active: allow the Docker bridge subnets to port 8000 or the sandbox cannot reach vLLM"
  else
    pass "ufw inactive"
  fi
fi

# 7. GPU memory
if ! have nvidia-smi; then
  warn "nvidia-smi not found"
else
  MEM="$(nvidia-smi 2>&1 | grep -m 2 -E 'MiB')"
  if [ -n "$MEM" ]; then
    pass "nvidia-smi memory:"
    printf '%s\n' "$MEM" | indent
  else
    warn "nvidia-smi shows no MiB line (GB10 unified memory may report N/A)"
  fi
fi

echo "== preflight: $PASS PASS, $WARN WARN, $FAIL FAIL =="
[ "$FAIL" -eq 0 ]
