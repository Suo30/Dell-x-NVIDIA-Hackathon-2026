#!/usr/bin/env bash
# Run on the box HOST from the repo clone. Ships the COMMITTED repo into the
# sandbox, installs infra/sandbox.env as .env, checks the job-boards policy.
# Idempotent: rerun after every git pull. Nothing here holds secrets.
set -euo pipefail

SB="${SANDBOX:-career-agent}"
W="${WORKSPACE:-/sandbox/.openclaw/workspace}"
STAGE="${STAGE:-/sandbox}"
cd "$(git rev-parse --show-toplevel)"

# 0. Everything we deploy must be committed on the checked-out branch
for f in infra/sandbox.env infra/job-boards.yaml prompts/system.md \
         skills/role-architect/SKILL.md skills/career-matcher/SKILL.md \
         skills/resume-screener/SKILL.md; do
  git cat-file -e "HEAD:$f" 2>/dev/null || { echo "ERROR: $f is not committed on this branch"; exit 1; }
done
echo "branch: $(git rev-parse --abbrev-ref HEAD)   commit: $(git rev-parse --short HEAD)"
[ -z "$(git status --porcelain --untracked-files=no)" ] || echo "WARN: uncommitted changes are NOT shipped."

# 1. Make the nemoclaw wrapper select the right OpenShell gateway first
nemoclaw "$SB" exec -- true >/dev/null

# 2. Pack and upload one file
TGZ="$(mktemp /tmp/career-agent-XXXXXX.tgz)"
trap 'rm -f "$TGZ"' EXIT
git archive --format=tar.gz -o "$TGZ" HEAD
echo "packed $(du -h "$TGZ" | cut -f1)"
openshell sandbox upload "$SB" "$TGZ" "$STAGE/"
REMOTE="$STAGE/$(basename "$TGZ")"

# 3. Unpack, refresh skills and AGENTS.md, install .env from the repo
nemoclaw "$SB" exec -- sh -c "
  set -e
  mkdir -p $W/repo $W/skills
  tar -xzf $REMOTE -C $W/repo
  rm -f $REMOTE
  rm -rf $W/skills/role-architect $W/skills/career-matcher $W/skills/resume-screener
  cp -r $W/repo/skills/role-architect $W/repo/skills/career-matcher $W/repo/skills/resume-screener $W/skills/
  cp $W/repo/prompts/system.md $W/AGENTS.md
  cp $W/repo/infra/sandbox.env $W/repo/.env
  echo 'installed .env:'; cat $W/repo/.env
"

# 4. Egress policy: re-apply job-boards if it is missing (a rebuild may drop it)
if openshell policy get --full "$SB" 2>/dev/null | grep -q boards-api.greenhouse.io; then
  echo "policy: job-boards present"
else
  echo "policy: job-boards missing, applying"
  nemoclaw "$SB" policy-add --from-file infra/job-boards.yaml \
    || echo "WARN: policy-add failed, run it by hand"
fi

# 5. Informational smoke check (never fails the push)
nemoclaw "$SB" exec -- sh -c "cd $W/repo && python3 tools/list_jobs.py --limit 1 2>&1 | head -c 300" || true
echo
echo "done. Send /new in Slack to load the new skills and prompt."
