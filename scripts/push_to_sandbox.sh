#!/usr/bin/env bash
# Run on the box HOST, from the repo clone (~/career-agent). Copies the committed
# repo into the sandbox workspace. Safe to rerun after every git pull.
set -euo pipefail

SB="${SANDBOX:-career-agent}"
W=/sandbox/.openclaw/workspace
TGZ="$(mktemp /tmp/career-agent-XXXXXX.tgz)"
trap 'rm -f "$TGZ"' EXIT

cd "$(git rev-parse --show-toplevel)"

echo "branch: $(git rev-parse --abbrev-ref HEAD)   commit: $(git rev-parse --short HEAD)"
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "WARN: uncommitted changes on the box. Only committed files are shipped."
fi

# Pack committed files only (no .git, no .env, no *.db)
git archive --format=tar.gz -o "$TGZ" HEAD
echo "packed $(du -h "$TGZ" | cut -f1)"

# Upload one file
openshell sandbox upload "$SB" "$TGZ" /sandbox/
REMOTE="/sandbox/$(basename "$TGZ")"

# Unpack inside the sandbox
nemoclaw "$SB" exec -- sh -c "
  set -e
  mkdir -p $W/repo $W/skills
  tar -xzf $REMOTE -C $W/repo
  rm -rf $W/skills/role-architect $W/skills/career-matcher
  cp -r $W/repo/skills/role-architect $W/repo/skills/career-matcher $W/skills/
  cp $W/repo/prompts/system.md $W/AGENTS.md
  rm -f $REMOTE
  python3 -m pip install -q -r $W/repo/requirements-recruit.txt || echo 'WARN: pip install failed; screen_resumes.py will return an error until it works'
  [ -f $W/repo/.env ] || echo 'NOTE: no .env in sandbox repo yet, create it once'
  ls $W/repo $W/skills
"
echo "done. Send /new in Slack to start a session with the new skills and prompt."