# Handoff A (Iker): platform, Slack, deploy, demo

Paste this file as the first message of a fresh Claude Code chat. Also read `docs/PLAN_MVP_COMPLETION.md`
(team plan and locked decisions), `AGENTS.md` (binding coding rules), `MASTER_CONTEXT.md` sections 1 to 5, 8
and 11, and `docs/BOX_SETUP.md`.

## 0. Your outcome

The agent runs the full demo script (plan section 5) in Slack on the box, twice in a row. Slack attachments
either reach the tools or fail with a clear one-line fallback. Everything is deployed from `main`, the video
is recorded, and the submission is in.

You own `prompts/system.md`, both `SKILL.md` files, `tests/smoke.sh`, `scripts/push_to_sandbox.sh`,
`scripts/box_preflight.sh`, `scripts/sandbox_check.sh`, `infra/*`, `docs/BOX_SETUP.md`, `README.md` and the
MASTER_CONTEXT contract updates.

Box access: `ssh dell@172.20.65.171`. Below, "host" means the box shell and `<sb>` means the sandbox name
(confirm it in step 5; `push_to_sandbox.sh` defaults to `career-agent`, BOX_SETUP says `my-assistant`).

---

## Step 1. Merge `origin/skills` (5 min, G0)

1. On GitHub, open the PR `skills -> main`. It merges with no conflicts. With mocks, smoke shows
   `ingest_profile`, `extract_reqs` and `match_jobs` as `OK`.
2. Merge it. Post in team chat: "main has skills. Everyone: `git fetch && git checkout -b <your-branch>
   origin/main`. Do not branch from `merge-b2b-sneha`, it is behind."
3. Post the 12 locked decisions (plan section 2) and ask each owner to acknowledge theirs.

## Step 2. Slack attachments: diagnose and fix (30 min, result due at G1)

### What is happening

Your agent called `message` with `action: download-file` and got
`{"ok": false, "error": "File could not be downloaded (not found, too large, or inaccessible)."}`.
So OpenClaw did receive the attachment: the placeholder carried a `fileId`. What failed is fetching the
bytes. OpenClaw downloads them from Slack's private URL (`url_private_download`, host `files.slack.com`) with
the bot token as a Bearer header. It saves them to its media store (limit 20 MB, `channels.slack.mediaMaxMb`),
and then the agent can use the saved path. A resume is far below 20 MB, so "too large" is out.

Candidate causes, most likely first:

1. **Egress blocked.** The NemoClaw sandbox denies all network egress by default. The Slack policy that
   onboarding adds covers the messaging endpoints (Slack API, socket mode); NemoClaw's docs list
   `api.slack.com` and `hooks.slack.com`. File bytes come from `files.slack.com`, which is a different host.
   A blocked request looks exactly like this generic error.
2. **The token does not reach `files.slack.com`.** NemoClaw keeps the real Slack token outside the sandbox and
   injects it at the OpenShell boundary (see NVIDIA/NemoClaw issue #10602 about credential binding). If
   injection only happens for the Slack API hosts, the download is sent without a valid token. Slack then
   answers with its sign-in page or an error (same symptom as openclaw/openclaw issue #12336).
3. **Missing `files:read` scope.** The manifest has it, but if the app was installed before the scope was
   added, the installed token does not.
4. **OpenClaw bug.** In OpenClaw v2026.9.4 and earlier, the Slack adapter did not list `download-file` as an
   allowed read action for official plugin installs. That is fixed in openclaw/openclaw PR #147659, merged
   2026-09-14.

### Diagnosis (do these in order, stop at the first that explains it)

1. **Watch egress.** On the host, keep `openshell term` open. In `#students`, upload
   `tests/fixtures/resume.txt` with `@Career Agent here is my resume, read it`.
   - A denied request to `files.slack.com` means cause 1. Fix A.
   - An allowed request that returns HTML or 302 to a login page means cause 2. Fix B.
2. **Check the scope (host).** Read the token without echoing it:
   ```sh
   printf 'Bot token: '; read -rs T; echo
   curl -s -D - -o /dev/null -H "Authorization: Bearer $T" https://slack.com/api/auth.test | grep -i x-oauth-scopes
   ```
   If `files:read` is missing, it's cause 3. Fix C.
3. **Prove the Slack side works outside the sandbox (host).** Get the file id from the agent's placeholder,
   or from the file's "Copy link" URL (`.../F0123ABC/...`). Then:
   ```sh
   curl -s -H "Authorization: Bearer $T" "https://slack.com/api/files.info?file=F0123ABC" | python3 -c 'import json,sys; f=json.load(sys.stdin)["file"]; print(f["url_private_download"])'
   curl -s -H "Authorization: Bearer $T" -o /tmp/probe.txt "<that url>" && head -3 /tmp/probe.txt
   unset T
   ```
   - If this prints the resume, Slack is fine and the problem is inside the sandbox (causes 1, 2 or 4).
   - If it fails with `file_not_found` or `missing_scope`, fix the Slack app first.
4. **Check the OpenClaw version.** `nemoclaw <sb> exec -- openclaw --version`. If it is 2026.9.4 or older and
   steps 1 to 3 are clean, it's cause 4. Fix D.

### Fixes

- **Fix A (egress).** Create `infra/slack-files.yaml`, in the same format as `infra/job-boards.yaml`:
  ```yaml
  # Slack attachment downloads (url_private_download). Binary path: copy it from `openshell term`.
  preset:
    name: slack-files
    description: "Slack private file downloads for attachments"
  network_policies:
    slack-files:
      name: slack-files
      endpoints:
        - host: files.slack.com
          port: 443
          protocol: rest
          enforcement: enforce
          rules:
            - allow: { method: GET, path: "/**" }
      binaries:
        - { path: REPLACE_WITH_BINARY_FROM_OPENSHELL_TERM }
  ```
  Then run `nemoclaw <sb> policy-add --from-file infra/slack-files.yaml` and retest. The binary is the
  OpenClaw gateway process (likely a `node` path), not `python3`. Add the check for this policy to
  `push_to_sandbox.sh` step 4, next to job-boards.
- **Fix B (credential).** Check `openshell policy get --full <sb>` for how the Slack token is bound to hosts,
  and add `files.slack.com` to the same binding. If you cannot find how within 15 minutes, stop and use the
  fallback. Never put the token in a file or the sandbox env.
- **Fix C (scope).** In the Slack app settings, open "OAuth & Permissions", confirm `files:read`, then
  "Reinstall to Workspace". If Slack issues a new bot token, the sandbox needs it via onboarding. Do this
  before deploying code (a channel change rebuilds the sandbox, BOX_SETUP (j)).
- **Fix D (OpenClaw version).** Do not upgrade OpenClaw on demo day; it rebuilds the sandbox. Use the
  fallback and say in the README that file upload needs OpenClaw newer than 2026.9.4.

### Fallback (always shipped, whatever the cause)

- Pasted resume text is the primary demo path.
- The skills (step 7) tell the agent:
  - Try `download-file`.
  - On success, pass the saved path to the tool. D's `_resume_text` reads `.txt`, `.md`, `.docx` and `.pdf`.
  - On failure, say exactly one line: "I couldn't open that file. Please paste the resume text here." Never
    guess file contents.
- Record the result in `docs/BOX_SETUP.md` (h) step 5: root cause, fix applied, and whether upload is in the
  demo.

Done when: either a Slack-uploaded `resume.txt` produces a `candidate_id` through `ingest_profile`, or the
cause is documented and the fallback line is what the agent says.

## Step 3. Inference route from inside the sandbox (10 min)

```sh
nemoclaw <sb> exec -- sh -c 'cd /sandbox/.openclaw/workspace/repo && python3 tools/_llm.py'
```

- It must print `"ok": true` with `base_url` equal to the value in `infra/sandbox.env`
  (`https://inference.local/v1`).
- If it fails, try `http://inference.local/v1`, then the URL `openshell inference get` shows. Commit the
  working value to `infra/sandbox.env`.
- Note the `seconds` value. Extraction calls take about that long each, and B and D size their demo prep on it.

## Step 4. Sandbox Python deps for files and screening (15 min)

`screen_resumes.py` needs `fastapi pydantic python-docx pypdf`. `ingest_profile` uses `pypdf` for PDFs.
Streamlit and uvicorn are not needed in the sandbox.

1. Create `requirements-sandbox.txt` with exactly those four packages, versions pinned to what
   `requirements-recruit.txt` resolves on a laptop (`pip freeze | grep -iE "fastapi|pydantic|python-docx|pypdf"`).
2. Allow PyPI. NemoClaw ships a `pypi` preset; `nemoclaw <sb> policy-add --help` shows the preset syntax.
   Then:
   ```sh
   nemoclaw <sb> exec -- python3 -m pip install --user -r /sandbox/.openclaw/workspace/repo/requirements-sandbox.txt
   ```
3. If pip or PyPI is unavailable, install offline from wheels:
   - On the host, use a Python whose `X.Y` version matches the sandbox `python3 --version` (both aarch64):
     `python3 -m pip download --only-binary=:all: -d wheels -r requirements-sandbox.txt`.
   - `openshell sandbox upload <sb> wheels /sandbox/`
   - `nemoclaw <sb> exec -- python3 -m pip install --user --no-index --find-links /sandbox/wheels -r .../requirements-sandbox.txt`
4. Verify with `nemoclaw <sb> exec -- python3 -c "import fastapi, pydantic, docx, pypdf; print('ok')"`.
5. Update `docs/BOX_SETUP.md` (e) to use `requirements-sandbox.txt`.

## Step 5. Fix names and doc drift (10 min)

1. Find the real sandbox name: `openshell sandbox list` (or `nemoclaw list`).
2. Make the default identical in `scripts/push_to_sandbox.sh` (`SANDBOX`), `scripts/box_preflight.sh`
   (`SANDBOX`) and every command in `docs/BOX_SETUP.md`.
3. In BOX_SETUP, turn each `TODO(verify)` you have now verified into the confirmed value. Leave the rest
   marked.

## Step 6. Make smoke a real gate (15 min)

Edit `tests/smoke.sh`:

1. Add `STRICT=1` mode: `ERR` counts as a failure. Exception: `screen_resumes` when
   `"$PY" -c "import fastapi, pydantic, docx"` fails (deps missing on that laptop).
2. Order and checks:
   - Order: `seed_db`, `fetch_jobs --offline`, `extract_reqs --pending --limit 3`, `list_jobs --limit 3`,
     `ingest_profile`, `update_profile`, `draft_role`, `show_role`, `approve_role`.
   - Then `list_jobs --source internal`: assert `internal:$ROLE` is present.
   - Then `match_candidates`, `match_jobs`: assert `internal:$ROLE` is in `matches` (the connected story).
   - Then `apply` and `screen_resumes --role $ROLE`.
3. For the asserts, add an `expect NAME PYTHON_EXPR` helper that evaluates against `$OUT`, e.g.
   `expect connected 'any(m["job_id"].startswith("internal:") for m in o["matches"])'`.
4. `scripts/check_local.sh` runs `STRICT=1 bash tests/smoke.sh` once all tools are merged (after G2). Until
   then it keeps the plain run.

## Step 7. Skills and system prompt (20 min, then tune during step 9)

`python3 scripts/check_skills.py` must pass: description under 160 characters, no em dashes.

`skills/career-matcher/SKILL.md`, replace steps 1 to 4 with:

```
1. New student: get the resume.
   - Pasted text: write it to /tmp/resume-SLUG.txt with exec.
   - Attached file: call the message tool with action download-file and the file's fileId. Use the
     path it returns. If it fails, say exactly: "I couldn't open that file. Please paste the resume
     text here." Never guess what a file says.
   Then run:
   python3 /sandbox/.openclaw/workspace/repo/tools/ingest_profile.py --name "NAME" --text-file PATH
   (.txt, .md, .docx and .pdf all work). Tell them their candidate_id and skills_found. Ask (max 3,
   one message) only for what the output's "missing" list names.
2. Anything they say later that is not on the resume (skills, company stances, visa, location, start):
   python3 /sandbox/.openclaw/workspace/repo/tools/update_profile.py --candidate ID --note "THEIR WORDS, VERBATIM"
   Say what changed. If "ignored" is not empty, say what you could not record.
3. Matches:
   python3 /sandbox/.openclaw/workspace/repo/tools/match_jobs.py --candidate ID --limit 8
   Only if list_jobs shows no jobs, or they ask to refresh: warn it takes minutes, then run
   fetch_jobs.py, then extract_reqs.py --pending --limit 20.
4. Present by route, in tool order:
   - match: company, title, score, one top_evidence line, url (internal roles have no url: say
     "posted in this app").
   - stretch: same, plus the closable gap from gaps_text.
   - review: state each flag plainly. sponsorship: "this posting says no visa sponsorship and you
     need it". clearance: "this posting requires US person status or a clearance". location:
     "this posting is onsite outside your preferred cities". pref_note: repeat it in plain words.
     Let them decide.
```

Keep step 5 (apply) as it is.

`skills/role-architect/SKILL.md`:

- Step 1: always ask for pay if it is missing. Students' "only for a strong offer" stances depend on it.
- Step 5, append: "Each draft_role run creates a new role_id. Always use the role_id from the latest output."
- Step 8, replace the file sentence with: "For attached resumes, call message download-file for each fileId
  and copy each returned path into /tmp/applicants-ROLE_ID/ with exec. If a download fails, ask for that
  resume as pasted text and save it as NAME.txt. Never guess file contents."

`prompts/system.md`, add:

```
9. Attachments: use the message tool's download-file action, then pass the saved path to a tool.
   If the download fails, ask for pasted text in one line. Never describe a file you could not open.
```

## Step 8. Live job-board egress (optional, 10 min)

The demo uses snapshots. Only if time allows:

1. Run `nemoclaw <sb> exec -- sh -c 'cd .../repo && python3 tools/fetch_jobs.py --source greenhouse'`
   with `openshell term` open.
2. Fix the `binaries` path in `infra/job-boards.yaml`.
3. Add the Greenhouse and Lever hosts if B added companies on other hosts (they are all
   `boards-api.greenhouse.io` and `api.lever.co`).

## Step 9. Deploy waves (each about 10 min)

Wave 1 after G1, wave 2 after G2, wave 3 final (after any prompt fix). Each wave:

1. Host: `git pull` on `main`, then `bash scripts/push_to_sandbox.sh`.
2. `nemoclaw <sb> exec -- sh -c 'cd /sandbox/.openclaw/workspace/repo && bash scripts/sandbox_check.sh'`.
3. Wave 2 only, first time: `bash scripts/demo_reset.sh` inside the sandbox. It runs live extraction once
   (minutes) and saves `work/demo_start.db`.
4. Slack: `/new`, then BOX_SETUP (h) ladder steps 1 to 5.
5. Wave 2 and 3: run the whole demo script (plan section 5) and note every place the agent deviates.
   - Fix it in the SKILL.md or system prompt text, not in tools, unless a tool output is wrong. If a tool
     output is wrong, tell its owner with the exact command and output.

## Step 10. Demo, video, README, submission

1. Two rehearsals on the box. D runs `demo_reset.sh` between them; C times each beat.
2. Record two takes of the 3-minute script and keep the best. Backup: record the same tool calls from the
   sandbox terminal while narrating the Slack lines.
3. Screenshot `openshell inference get` (local route only).
4. `README.md`, replacing "Full run and demo steps get written here":
   - **Run (laptop)**: venv, `check_local.sh`, tunnel.
   - **Run (box)**: `push_to_sandbox.sh`, `demo_reset.sh`, `/new`.
   - **Demo**: the plan section 5 script.
   - **Architecture**: the MASTER_CONTEXT section 3 diagram plus one paragraph per side.
   - **Known limits**: Slack file upload status from step 2.
   B, C and D send you two lines each about their tools.
5. `git log -p | grep -E "xox[bap]-|xapp-"` must be empty. Then submit.

## Step 11. Contract PR to MASTER_CONTEXT (15 min, any time after G1)

One PR that records plan section 2:

- Section 0: answers to Q1 (names), Q3 (workspace path), Q4 (merger), Q5 (lower bound kept), Q6 (Glassdoor
  dropped).
- Section 4: `_role.py`, `_resume_text.py`, `requirements-sandbox.txt`, `infra/slack-files.yaml`.
- Section 5: `match_candidates` owner is D.
- Section 6.4: `extract_reqs` also writes `sponsorship`, `clearance` and hourly `pay`.
- Section 8, extra output keys:
  - `fetch_jobs`: `failed`.
  - `extract_reqs`: `dropped_skills`.
  - `ingest_profile`: `missing`.
  - `update_profile`: `ignored`.
  - `draft_role`: `dropped_skills`.
  - `apply`: `already_applied`.
  - `match_jobs`: drops `hidden`.
  - `match_candidates`: drops `hidden` and `excluded`, no `pref_note`.
- Section 13: the locked demo script.

## Done checklist

- [ ] `skills` merged, everyone on fresh branches
- [ ] Slack attachment cause found and fixed, or documented with the fallback in the skills
- [ ] `_llm.py` self-check OK inside the sandbox; `sandbox.env` correct
- [ ] Recruit deps importable in the sandbox; `screen_resumes --role` OK there
- [ ] Sandbox name consistent across scripts and docs
- [ ] `STRICT=1 bash tests/smoke.sh` OK with the connected-story assert
- [ ] Skills and system prompt updated, `check_skills.py` passes
- [ ] Demo script ran twice in Slack; video recorded; README and MASTER_CONTEXT updated; submitted
