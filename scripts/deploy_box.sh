#!/usr/bin/env bash
# Deploy the repo, skills and system prompt into the OpenClaw workspace.
# Runs INSIDE the sandbox, from wherever the repo currently is.
# Usage: bash scripts/deploy_box.sh   (override target with WORKSPACE=/path)
set -eu

WORKSPACE="${WORKSPACE:-/sandbox/.openclaw/workspace}"
SRC="$(cd "$(dirname "$0")/.." && pwd -P)"
DEST="$WORKSPACE/repo"
SKILL_NAMES="role-architect career-matcher resume-screener"

die() { echo "deploy_box: ERROR: $*" >&2; exit 1; }

# Required sources
[ -f "$SRC/prompts/system.md" ] || die "missing $SRC/prompts/system.md"
[ -d "$SRC/tools" ] || die "missing $SRC/tools/"
for s in $SKILL_NAMES; do
  [ -f "$SRC/skills/$s/SKILL.md" ] || die "missing $SRC/skills/$s/SKILL.md"
done

mkdir -p "$WORKSPACE" || die "cannot create $WORKSPACE"
[ -w "$WORKSPACE" ] || die "$WORKSPACE is not writable"
mkdir -p "$DEST" "$WORKSPACE/skills"
DEST="$(cd "$DEST" && pwd -P)"

# 1. Repo copy (never .git, .env, sqlite files, caches, venvs)
if [ "$SRC" = "$DEST" ]; then
  REPO_MSG="repo: already running from $DEST, copy skipped"
else
  case "$DEST/" in "$SRC"/*) die "target $DEST is inside the source repo $SRC";; esac
  n=0
  cd "$SRC"
  while IFS= read -r f; do
    f="${f#./}"
    mkdir -p "$DEST/$(dirname "$f")"
    cp -p "$f" "$DEST/$f"
    n=$((n + 1))
  done <<EOF
$(find . \( -name .git -o -name .venv -o -name __pycache__ \) -prune -o \
    -type f ! -name .env ! -name '*.db' ! -name '*.db-*' -print)
EOF
  REPO_MSG="repo: $n files copied $SRC -> $DEST (.env, *.db, .git, __pycache__ excluded)"
fi

# 2. Skills: replace each owned skill dir with a real copy
for s in $SKILL_NAMES; do
  rm -rf "$WORKSPACE/skills/$s"
  mkdir -p "$WORKSPACE/skills/$s"
  cp -RL "$SRC/skills/$s/." "$WORKSPACE/skills/$s/"
  if [ -n "$(find "$WORKSPACE/skills/$s" -type l)" ]; then
    die "symlink found in $WORKSPACE/skills/$s; OpenClaw rejects skill files outside the skills root"
  fi
done

# 3. System prompt -> AGENTS.md (one-time backup of a differing previous file)
AGENTS="$WORKSPACE/AGENTS.md"
BAK_MSG=""
# cmp missing counts as "differs", so the worst case is one extra backup
if [ -f "$AGENTS" ] && ! cmp -s "$AGENTS" "$SRC/prompts/system.md" 2>/dev/null && [ ! -e "$AGENTS.bak" ]; then
  cp -p "$AGENTS" "$AGENTS.bak"
  BAK_MSG=" (previous saved as AGENTS.md.bak)"
fi
cp "$SRC/prompts/system.md" "$AGENTS"

echo "== deploy_box summary =="
echo "$REPO_MSG"
echo "skills: $SKILL_NAMES -> $WORKSPACE/skills/"
echo "prompt: prompts/system.md -> $AGENTS$BAK_MSG"
if [ -f "$DEST/.env" ]; then
  echo ".env: kept existing $DEST/.env"
else
  echo ".env: MISSING. Create $DEST/.env from .env.example and set LLM_BASE_URL to the inference.local route"
fi
if [ -f "$SRC/scripts/seed_db.py" ]; then
  echo "DB not touched. To seed (wipes the DB):"
  echo "  python3 $DEST/scripts/seed_db.py --reset"
fi
echo "Next: send /new in Slack so the agent reloads AGENTS.md and skills."
