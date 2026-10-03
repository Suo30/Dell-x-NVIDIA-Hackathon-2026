You are finishing the MVP of a two-sided career matching agent (Dell x NVIDIA hackathon, final sprint, today). Work autonomously and fast. Close as much of the gap as possible at merge-ready quality. Only ask me when you are blocked on something only I can do: box access, Slack, or secrets.

## Read first (this is the spec, in this order)
1. `docs/PLAN_MVP_COMPLETION.md`: state, 12 locked decisions, demo script, definition of done.
2. `AGENTS.md`: binding coding rules.
3. `docs/handoff/C_EMPLOYER.md`, `B_CANDIDATE_JOBS.md`, `D_PROFILES_DATA.md` and `A_PLATFORM.md`. They hold exact specs, prompts, SQL and test lists; implement them as written.
4. `MASTER_CONTEXT.md` sections 4 to 9. Where it conflicts with the plan or handoffs, the plan wins, because it records newer team decisions.

## Environment
- Windows 11. Repo at `C:\Users\ikerj\VSCode\Dell-x-NVIDIA-Hackathon-2026`. Run `.sh` files with Git Bash.
- Python: `C:/Users/ikerj/VSCode/Dell-x-NVIDIA-Hackathon-2026/.venv/Scripts/python`. Export it as `PY` for every bash script. Worktrees have no `.venv` of their own, so always pass `PY`.
- No `gh` CLI. The laptop has internet, and Greenhouse and Lever are reachable.
- The box model is reached through a tunnel that I open. Check it with `curl -s -m 5 http://127.0.0.1:8000/v1/models`. Use `MOCK_LLM=1` whenever it is down.

## Phase 0: base (you, about 15 min)
1. Run `git fetch --all`. For every remote branch, run `git log --stat origin/main..origin/<branch>`. If a teammate already implemented any stub tool, reuse it; do not rewrite it.
2. Create the branch: `git checkout -b sprint/mvp origin/main`, then `git merge origin/skills` (it merges clean). The plan and handoff docs are untracked in the working tree, so commit them first.
3. Install: `$PY -m pip install -r requirements-dev.txt -r requirements-recruit.txt`. Run `bash scripts/check_local.sh` and note the baseline.
4. Build the shared pieces the parallel work depends on, with tests, then commit:
   - `tools/_role.py` and `tests/test_role.py` (C, step 1).
   - `_match.job_from_row(row)` plus a test (D, step 4.3).
   - c002's Acme `min_pay` set to null, and `data/requests/demo-acme-conversation.txt` (D, step 1).

## Phase 1: parallel build (4 subagents, one message, each with `isolation: "worktree"` from `sprint/mvp` HEAD)
Tell each agent to:
- Read `AGENTS.md`, the plan and its handoff file.
- Implement every step of its scope with `MOCK_LLM=1`, skipping live-model steps.
- Write the tests the handoff lists, with `PY` exported to the absolute venv path.
- Loop `bash scripts/check_local.sh` until it is all PASS.
- Commit in small commits, never touch files outside its scope, and report its branch, test counts and anything left undone.

The four agents:
- **Agent C**: `draft_role`, `show_role`, `approve_role` and `tests/test_employer_tools.py` (C steps 2 to 5).
- **Agent B**:
  - `data/companies.json` and `fetch_jobs`. Run it online once and commit the six `data/snapshots/*.json`.
  - The `extract_reqs` fixes (using `_role.clean_requirements`), `list_jobs`, `apply`, and the `match_jobs` fixes (using `_match.job_from_row`).
  - `tests/test_candidate_tools.py` (B steps 1 to 7).
- **Agent D**:
  - `tools/_resume_text.py`, the `ingest_profile` fixes, `match_candidates`, `update_profile`, `scripts/demo_reset.sh`, `scripts/demo_check.py` and `tests/test_profile_tools.py` (D steps 2 to 8, without the live run).
  - Its `match_candidates` tests hand-insert an approved role and its `internal:` job row in the format of C step 4.
- **Agent A-files** (repo files only, never the box):
  - `tests/smoke.sh`: STRICT mode plus the connected-story assert (A step 6).
  - Both `SKILL.md` files and `prompts/system.md` (A step 7). `scripts/check_skills.py` must pass.
  - `infra/slack-files.yaml` and `requirements-sandbox.txt`.
  - A single sandbox name, `career-agent`, across scripts and `docs/BOX_SETUP.md`, marked `TODO(verify)`.
  - The MASTER_CONTEXT contract updates (A step 11), and README Run, Demo, Architecture and Known limits sections (A step 10.4).

While they run, do not edit their files. Review their reports when they finish.

## Phase 2: integrate (you)
1. Merge the agent branches into `sprint/mvp` in this order: C, B, D, A-files. Resolve any conflicts.
2. Require all PASS from `bash scripts/check_local.sh` and every tool `OK` from `STRICT=1 bash tests/smoke.sh`, including the connected-story assert. Fix anything red yourself.
3. Commit.

## Phase 3: live (only if the tunnel is up; otherwise record exactly what is pending)
1. Run `bash scripts/check_local.sh --live`.
2. Tune the C step 6 prompt. The demo conversation must yield `react-native` and `mysql` as `must` at level 2, with sponsorship true and pay "35-45 USD/hour".
3. Run `MOCK_LLM=0 bash scripts/demo_reset.sh --rebuild`. Time it, then do the B step 8 quality check of the extracted jobs.
4. Run `python scripts/demo_check.py` until it is all PASS. Fix prompts, snapshot company choices or data. Never change the `_match` scoring rules, and never hand-edit `matches`.
5. Commit.

## Phase 4: ship
1. Push `sprint/mvp` to origin. Print the GitHub compare URL for a PR into `main`. Do not merge.
2. Write `docs/SPRINT_BOX_STEPS.md`: exact, copy-paste, ordered commands that I run on the box:
   - A step 2: the Slack attachment diagnosis tree and the fix for each cause.
   - A steps 3, 4 and 5.
   - A step 9: deploy waves, including the first `demo_reset.sh` build and `demo_check.py` inside the sandbox.
   - A step 10: rehearsal and recording.
3. Final report: what is done (test counts, smoke result, live yes or no), what is left, and the box steps I must run.

## Rules
- Commit after every green step; never leave `sprint/mvp` red.
- If time runs short, cut from the bottom of this list first:
  1. Tests beyond each tool's core tests.
  2. `update_profile` nuance (keep `company_pref` and `skill`).
  3. `apply`.
  4. A-files docs.
- Never cut `draft_role`, `approve_role`, `match_candidates`, `ingest_profile`, `match_jobs`, `fetch_jobs --offline` or `extract_reqs`.
- No secrets in files or commands. Never commit `.env`, `*.db` or `work/`.
- Do not change frozen contracts beyond what plan section 2 decides.
- Never run interactive ssh or anything on the box.
- Report honestly. If something was not run live, or a test is skipped, say so.
