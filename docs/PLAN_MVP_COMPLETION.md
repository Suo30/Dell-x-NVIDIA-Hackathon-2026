# Plan: finish the MVP

Snapshot: `main` at `c3c0a6a` (PR #7), read 2026-10-03. MASTER_CONTEXT.md still owns the data contracts.
This file is the team plan: what is done, what is decided, who does what and in which order, and when the MVP
counts as complete. Each person's step-by-step work is in their own handoff file. Paste that file into a fresh
Claude Code chat as the first message.

| Person | Handoff |
|---|---|
| A (Iker), platform, Slack, deploy, demo | [docs/handoff/A_PLATFORM.md](handoff/A_PLATFORM.md) |
| B, candidate job pipeline | [docs/handoff/B_CANDIDATE_JOBS.md](handoff/B_CANDIDATE_JOBS.md) |
| C, employer pipeline | [docs/handoff/C_EMPLOYER.md](handoff/C_EMPLOYER.md) |
| D, profiles, shortlist, demo data | [docs/handoff/D_PROFILES_DATA.md](handoff/D_PROFILES_DATA.md) |

## 1. Where `main` stands (verified by running it)

- `pytest`: 122 passed. The 2 skipped are recruit tests that need `requirements-recruit.txt`; with it
  installed, 24 more pass.
- `tests/smoke.sh`: 0 FAIL, but only `seed_db` is OK. The other tools return `not implemented`, and
  `screen_resumes` needs recruit deps.

| Area | State |
|---|---|
| Shared modules `_config _cli _db _taxonomy _match _profile _llm aux_math` | Done, tested |
| `skills.json` (52), 30 candidates (heroes c001 Jordan, c002 Riley), 3 demo requests, 7 test jobs | Done |
| `seed_db`, `gen_candidates`, `check_local.sh`, `check_skills.py`, `smoke.sh` | Done |
| `screen_resumes.py` + `recruit_assistant/` + Streamlit | Done on laptops; not installed in the sandbox |
| `prompts/system.md`, both SKILL.md | Written; they call tools that are still stubs |
| Infra (Slack manifest, egress YAMLs, `sandbox.env`, deploy and check scripts) | Written; many `TODO(verify)` |
| `ingest_profile`, `extract_reqs`, `match_jobs` | On `origin/skills`, not merged. Merges clean, need fixes |
| `draft_role`, `show_role`, `approve_role`, `match_candidates` | Stubs |
| `fetch_jobs`, `list_jobs`, `apply`, `update_profile` | Stubs |
| `data/companies.json`, `data/snapshots/` | Empty |
| `demo_reset.sh` | Broken (needs `fetch_jobs --offline`) |
| Slack file attachments | Broken: `download-file` returns "File could not be downloaded (not found, too large, or inaccessible)" |
| Tool tests, README run steps, MASTER_CONTEXT Q1 to Q6 | Missing |

## 2. Decisions locked by this plan

Each change goes into MASTER_CONTEXT in A's contract PR (A, step 11).

1. **Demo employer is Acme.** The candidate data was built around Acme: it has every stance for Acme, and test
   job 1 is the Acme ops app. The manager's lines are fixed in section 5, so the drafted role always needs
   React Native and MySQL and states pay.
2. **c002's Acme preference becomes `min_pay: null`** (D). With 45, the stated pay of 35 to 45 parses as 35, so
   the hero would drop to `review` on the very shortlist meant to showcase them.
3. **Jobs come from committed snapshots**:
   - `fetch_jobs --offline` loads them. Live fetch still works but is not on the demo path.
   - Companies (checked live today; each has US early-career postings): Formlabs, Datadog, Waymo, Robinhood
     and Figma on Greenhouse, Palantir on Lever.
   - Up to 5 per company, US locations only, deduplicated by title.
4. **The eligibility flag in the demo is `clearance`, not `sponsorship`.** Out of more than 30 boards checked,
   no US intern posting says it won't sponsor. Palantir's US-government internships do require US person or
   clearance status, so an F-1 student gets a real `clearance` flag. The narration says "eligibility flag".
5. **Pay is stored as hourly text and converted in code** (B, `extract_reqs`):
   - The model returns min, max and period. Code writes `"39-49 USD/hour"`.
   - Real postings quote pay per week (Formlabs), month (Palantir) or year. `parse_hourly` would misread
     $1,575/week as an annual figure (about $0.76/hour).
6. **`extract_reqs` also fills `sponsorship`, `clearance` and `pay`.** It never touches `source='internal'` jobs.
7. **New shared modules**:
   - `tools/_role.py` (C) validates and cleans roles (6.3).
   - `tools/_resume_text.py` (D) reads `.txt`, `.md`, `.docx` (stdlib) and `.pdf` (`pypdf` if installed).
8. **`match_candidates` moves from C to D.** C has the heaviest model work, and D owns the candidate data the
   shortlist must show off.
9. **`match_jobs` drops `hidden` from its output** but still stores it in `matches`. The career-matcher skill
   asks for `--limit 8`.
10. **Employers never see `pref_note`**, because it reveals a student's private stance. `hidden` and
    `excluded` candidates never appear on a shortlist.
11. **Resume input**:
    - Pasted text is the primary demo path.
    - A Slack attachment works when A's fix lands (A, step 2).
    - Every tool that takes a resume accepts a file path, so a downloaded attachment can go straight in.
12. **Internal job rows** (written by `approve_role`):
    - `evidence_text` of each requirement is the role's `why`.
    - `url` is NULL, `source` is `internal`, `id` is `internal:{role_id}`.

### Why Slack attachments fail (A owns the fix, handoff A step 2)

OpenClaw does receive the attachment: the agent gets a `fileId` and calls `message` `download-file`. What
fails is fetching the bytes. OpenClaw downloads them from Slack's private URL on `files.slack.com`, using the
bot token. The NemoClaw sandbox blocks all network egress except allowed hosts, and its Slack policy covers the
messaging API, not `files.slack.com`. That is the most likely cause.

Other causes, in order:
- The token not being injected for that host.
- A token installed without `files:read`.
- The OpenClaw download bug in v2026.9.4 and earlier, fixed in openclaw/openclaw PR #147659.

A's step 2 has a diagnosis that pins down which one in about 15 minutes, plus a fix per cause.

Whatever the cause, the MVP does not depend on it:
- Pasted text is the primary demo path.
- Every resume tool accepts a file path (`.txt`, `.md`, `.docx`, `.pdf` via D's `_resume_text`).
- The skills tell the agent to ask for pasted text in one line when a download fails.

## 3. Dependency graph

```
A1 merge skills ─┬─> B (fixes to extract_reqs, match_jobs)      D (fixes to ingest_profile)
                 │
C1 _role.py ─────┼─> C2 draft_role ─> C3 show_role ─> C4 approve_role ─┐
                 │                                                     ├─> D4 match_candidates
D1 c002 edit ────┘                                                     │
B2 fetch_jobs + snapshots ─> B3 extract_reqs ─> D5 demo_reset ─────────┤
D2 _resume_text ─> D3 ingest_profile, D6 update_profile ───────────────┤
A2 Slack files, A3 inference, A4 sandbox deps (in parallel) ───────────┴─> A9 deploy waves ─> A10 demo
```

Nothing blocks on a person's later steps, only on the merged step named. B and D use the fixture DB
(`seed_db.py --with-test-jobs`) until snapshots land. D uses a hand-inserted approved role in tests until C4
lands.

## 4. Schedule and gates

Times are from kickoff (T0). Gates are checked by A in the team chat.

| Gate | Target | Exit criterion |
|---|---|---|
| G0 | T0+10 | `skills` merged. Everyone on a fresh branch from `main`. Decisions in section 2 acknowledged |
| G1 | T0+40 | Merged: `_role.py`, `_resume_text.py`, `show_role`, `list_jobs`, `apply`, c002 edit, companies + snapshots. A has the Slack file diagnosis result |
| G2 | T0+80 | Every tool `OK` in `STRICT=1 bash tests/smoke.sh`. Live model run of both flows on a laptop through the tunnel |
| G3 | T0+100 | Wave 2 deployed. Full demo story ran once in Slack. D's data check passed |
| G4 | T0+130 | Two rehearsals, video recorded, README done, submitted |

If code stop is 18:00 and kickoff is about 17:00, the order of steps is unchanged. Recording starts at
17:40 with whatever is merged, and the pasted-text path covers resumes.

## 5. Demo script (locked; A narrates, D resets between takes)

0. `bash scripts/demo_reset.sh`, then `/new` in Slack.
1. `#hiring`: `@Career Agent I need someone to build an app for our ops team at Acme.` The agent asks up to 3
   questions.
2. Manager answers verbatim: `Co-op starting January, hybrid in Boston, and yes we can sponsor visas. Pay is
   35-45 an hour. They'd own the React Native app and its MySQL backend; the team is 2 engineers, no
   designer.`
3. The agent shows the public JD and the private requirements. Manager: `Approve it.` The agent approves,
   shortlists and says the role is visible to students.
4. Point at Riley Pangolin (c002): `match`, with MySQL evidence that came from chat, not the resume.
5. `#students`: `@Career Agent here is my resume` plus the pasted text of `tests/fixtures/resume.txt` (or the
   file, if A2 is fixed). Then: `I'd only go to Palantir for a really strong offer, at least 60 an hour.`
6. `@Career Agent show my matches.` Expect real Formlabs, Datadog and Palantir jobs, the internal Acme role, one
   `stretch` with a closable gap, and one `clearance` flag on a Palantir US-government internship.
7. `@Career Agent apply to the Acme role.` The agent replies "Application record created in the app...".
8. Close on the `openshell inference get` screenshot: local only.

## 6. MVP definition of done

- [ ] Every tool in MASTER_CONTEXT section 8 (except stretch `tailor`) returns `OK` in
      `STRICT=1 bash tests/smoke.sh`.
- [ ] `bash scripts/check_local.sh` is all PASS. `check_local.sh --live` is all PASS through the tunnel.
- [ ] Unit tests exist for every new tool (listed in each handoff).
- [ ] `demo_reset.sh` returns the DB to the demo start state in under 5 seconds (after the first prep run).
- [ ] `python scripts/demo_check.py` is all PASS on a laptop (tunnel) and inside the sandbox.
- [ ] The section 5 script runs end to end in Slack on the box, twice in a row.
- [ ] Slack attachments either reach `ingest_profile` / `screen_resumes`, or fail with the documented one-line
      fallback ("I couldn't open the file, please paste the text"), never silently.
- [ ] `screen_resumes` runs in the sandbox (recruit deps installed) with `--role` on the approved Acme role.
- [ ] README has Run, Demo and Architecture sections. MASTER_CONTEXT reflects section 2. Q1 to Q6 are answered.
- [ ] No secrets in git history (`git log -p | grep -E "xox[bap]-"` is empty).

Out of MVP scope (do not start): `tailor.py`, Workday, the `notified` cron scan, LinkedIn fetching via
Jina, and `--discover`.

## 7. Working rules for everyone

- Read `AGENTS.md` first; it is binding:
  - Fail fast. No silent `continue`.
  - `ValueError` for bad user input, `RuntimeError` for broken internal contracts.
  - Fallbacks only at external boundaries (model output, ATS JSON, Slack), with a comment naming the boundary.
  - `aux_math` for float comparisons. Short comments.
- Tools are stdlib only. Import `_llm` as a module (`import _llm`, then `_llm.chat_json(...)`) so tests can
  monkeypatch it.
- Every tool: `main()` returns a dict, the module ends with `_cli.run(main)`, and connections close in
  `try/finally` (Windows cannot delete an open DB).
- One PR per step. `bash scripts/check_local.sh` passes before the PR opens. One merger (Q4). Only A deploys.
- Test style: import the tool module from `tests/`, `monkeypatch.setattr(sys, "argv", [...])`, call
  `module.main()`. Use the `tmp_db` and `mock_llm` fixtures from `tests/conftest.py`.
