# Handoff D: profiles, shortlist, demo data

Paste this file as the first message of a fresh Claude Code chat. Also read `docs/PLAN_MVP_COMPLETION.md`
(team plan, locked decisions, demo script), `AGENTS.md` (binding coding rules), `MASTER_CONTEXT.md`
sections 6.2, 6.5, 7, 8 and 9, and `tools/_profile.py`, `tools/_match.py` and `tools/_llm.py`.

## 0. Your outcome

A student's resume (pasted or a file) becomes a valid profile, and later chat statements update it. A hiring
manager's approved role gets a shortlist of all candidates. The demo DB resets in seconds, and a script proves
every demo beat before anyone records.

You own:
- `data/candidates/c002.json` and the new `data/requests/demo-acme-conversation.txt`.
- `tools/_resume_text.py`, `tools/ingest_profile.py`, `tools/update_profile.py` and
  `tools/match_candidates.py`.
- `scripts/demo_reset.sh` and `scripts/demo_check.py`.
- `tests/test_profile_tools.py`.

## 1. Setup

```bash
git fetch && git checkout -b d-data origin/main
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements-dev.txt   # macOS: .venv/bin/python
cp .env.example .env            # MOCK_LLM=1 until step 8
bash scripts/check_local.sh
```

`ingest_profile.py` already exists from `origin/skills`; you are fixing it.

## 2. Rules that bite here

- Model output is the external boundary. Coerce it with a comment naming the boundary, then
  `_profile.validate` before anything is stored.
- Nothing is dropped silently: anything ignored is listed in the output (`ignored`, `missing`).
- Use `import _llm`, then `_llm.chat_json(..., max_tokens=4000)`. `try/finally` on every connection. Unknown
  ids raise `ValueError`.

---

## Step 1. c002 preference and demo conversation (10 min, PR at once)

1. In `data/candidates/c002.json`, change the Acme entry to
   `{"company": "Acme", "stance": "only_strong_offer", "min_pay": null}`.
   - Why: the demo role pays "35-45 USD/hour", and `parse_hourly` reads 35. With a minimum of 45, c002 (the
     hero whose MySQL skill comes from chat) drops to `review` on the showcase shortlist.
   - c002 is hand-written, and `gen_candidates.py` never touches it.
   - `pytest -q tests/test_seed.py` must stay green: `test_spread_company_prefs` still sees all four Acme
     stances via c023.
2. Add `data/requests/demo-acme-conversation.txt` with the locked exchange from plan section 5:
   ```
   manager: I need someone to build an app for our ops team at Acme.
   agent: Is this a co-op, new grad or experienced hire? Onsite, hybrid or remote? Can you sponsor visas, and what is the pay?
   manager: Co-op starting January, hybrid in Boston, and yes we can sponsor visas. Pay is 35-45 an hour. They'd own the React Native app and its MySQL backend; the team is 2 engineers, no designer.
   ```

## Step 2. `tools/_resume_text.py` (20 min, PR early)

```python
"""Resume file -> plain text. Stdlib, plus pypdf when installed (optional, requirements.txt). Owner: D.

    read(path) -> str
        .txt/.md as UTF-8; .docx via zipfile + word/document.xml; .pdf via pypdf.
        Raises ValueError with a user-facing reason (unsupported type, no text layer, pypdf missing).
"""
```

- **`.txt` and `.md`**: read with `encoding="utf-8-sig"`. On a `UnicodeDecodeError`, re-read as `cp1252`,
  with a comment: "User file boundary".
- **`.docx`**: `zipfile.ZipFile(path).read("word/document.xml")`, parsed with `xml.etree.ElementTree`.
  - Namespace `w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"`.
  - Each `w:p` becomes one line: the `w:t` texts joined.
  - A `BadZipFile` raises `ValueError("not a valid .docx")`.
- **`.pdf`**: `try: from pypdf import PdfReader`. An `ImportError` raises
  `ValueError("PDF needs pypdf (pip install -r requirements.txt); or paste the text")`. Otherwise join
  `page.extract_text()` across pages. If that is empty, raise
  `ValueError("PDF has no text layer (scanned?); paste the text")`.
- **Any other extension**: `ValueError(f"unsupported resume type {suffix}; use .txt .md .docx .pdf")`.
- **Empty result after `strip()`**: `ValueError("resume is empty")`.

These messages reach the student through the agent, so keep them plain. Slack attachments arrive as files
(A, step 2), so this module is what makes uploads usable.

## Step 3. Fix `tools/ingest_profile.py` (30 min)

1. Read the file with `_resume_text.read(args.text_file)`.
2. Prompt changes:
   - Each skill returns `{"skill_id", "level", "source": "resume"|"chat", "evidence": "verbatim line"}`.
   - Rule: "source is chat when the skill appears only in ADDITIONAL NOTES FROM CHAT".
   - Keep "If a fact is not stated, use null".
3. Model boundary coercion, with a comment, tracking a `missing` list:
   - **`visa`**: if not a dict, or `needs_sponsorship` / `us_person` is not a bool, set both to False,
     `status` to None, and add `"visa"` to `missing`.
   - **`location`**: `preferred` that is not a list of strings becomes `[]` (adds `"location"`). `remote`
     outside `{any, remote, hybrid, onsite}` becomes `"any"`.
   - **`availability`**: not a dict becomes `{"start": None, "type": None}` (adds `"availability"`).
   - **Skills**: resolve the id (unknown goes to `dropped_skills`). The level is an int, or a digit string
     made into an int; outside 1 to 3 it is dropped with a reason. `source` outside `{resume, chat}` becomes
     `resume`. An empty evidence string is dropped.
   - **Duplicate `skill_id`s merge**: max level, and all evidence entries combined (unique texts).
     Otherwise `_profile.validate` raises "listed twice" on real model output.
   - **`bullets`**: keep only non-empty strings.
4. Then:
   - `next_id`, then `_profile.validate`.
   - `INSERT` with `synthetic=0`, `consent_auto=1`.
   - Keep `next_id` and `INSERT` in one transaction, in `try/finally`.
5. Output: `{"candidate_id", "skills_found", "profile", "missing", "dropped_skills"}`. The career-matcher
   skill asks the student only about what `missing` lists.
6. Mock: keep the existing one, change `react_native` to `react-native`, and add `"source": "resume"` to each
   skill. Add one chat skill to match the smoke `--notes "I also know Docker"`:
   `{"skill_id": "docker", "level": 1, "source": "chat", "evidence": "I also know Docker"}`.

## Step 4. `tools/match_candidates.py` (25 min; moved from C to you)

Contract: `match_candidates.py --role ID [--limit 10]` returns
`{"role_id", "job_id", "evaluated", "counts", "shortlist": [{"candidate_id", "name", "score", "route",
"flags", "gaps_text", "top_evidence"}]}`.

1. Load the role:
   - Unknown raises `ValueError`.
   - A status other than `approved` raises `ValueError(f"role {id} is {status!r}; approve it first")`.
2. Read the jobs row `internal:{role_id}` that C's `approve_role` wrote. If it is missing, raise
   `RuntimeError` (an approved role without its job breaks the contract).
3. Add `job_from_row(row) -> dict` to `tools/_match.py`, the DB-to-`evaluate` conversion:
   - `sponsorship` 0/1/NULL becomes False/True/None.
   - `requirements` comes from `json.loads`.
   - It carries `id`, `company`, `clearance`, `location`, `pay` and `paid`.
   - Tell B: their `match_jobs` switches to this helper.
4. For every candidate row, `_match.evaluate(job, profile)`, then upsert into `matches` (same SQL as
   `match_jobs`).
5. Shortlist:
   - Leave out `hidden` (never shown to employers as a "no") and `excluded` (the student said never).
   - Sort with `_match.sort_key({"route", "score", "eager", "paid"})` and apply `--limit`.
   - **Do not include `pref_note`**: it reveals a student's private stance.
6. `counts` is the number per route over all evaluated candidates, including hidden and excluded.

## Step 5. `scripts/demo_reset.sh` (15 min)

```bash
#!/usr/bin/env bash
# Reset the DB to the demo start state. Owner: D.
# First run or --rebuild: seed, load snapshots, extract with the LIVE model (minutes), save work/demo_start.db.
# Later runs: copy work/demo_start.db over DB_PATH (seconds). Never saves a mock-extracted DB.
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-python3}"
DB="$("$PY" -c 'import sys; sys.path.insert(0, "tools"); import _config; print(_config.DB_PATH)')"
MOCK="$("$PY" -c 'import sys; sys.path.insert(0, "tools"); import _config; print(int(_config.MOCK))')"
SAVED=work/demo_start.db
mkdir -p work
if [ "${1:-}" = "--rebuild" ] || [ ! -f "$SAVED" ]; then
  "$PY" scripts/seed_db.py --reset
  "$PY" tools/fetch_jobs.py --offline
  "$PY" tools/extract_reqs.py --pending --limit 100
  if [ "$MOCK" = 1 ]; then echo "MOCK_LLM=1: demo DB built but NOT saved"; else cp "$DB" "$SAVED"; fi
else
  cp "$SAVED" "$DB"
fi
"$PY" tools/list_jobs.py --limit 1
echo "demo reset done"
```

- Print the `extract_reqs` output so failures are visible. If `failed` is not empty, the script still saves,
  but echoes the count.
- `work/` is gitignored, so `demo_start.db` is built once per machine: once on the box, through A's wave 2.

## Step 6. `tools/update_profile.py` (35 min)

Contract: `update_profile.py --candidate ID --note "..."` returns
`{"candidate_id", "changes": [...], "ignored": [...]}`.

1. The system prompt:
   ```
   You record what a student just said into their career profile. Return only JSON {"changes": [...]}
   using only these change types:
   {"type": "skill", "skill_id": "<id from the list>", "level": 1|2|3}
   {"type": "company_pref", "company": "Name", "stance": "eager|neutral|only_strong_offer|never",
    "min_pay": number or null}            (min_pay: the hourly USD minimum they named, else null)
   {"type": "visa", "status": str, "needs_sponsorship": bool, "us_person": bool}
   {"type": "location", "preferred": ["City, ST"], "remote": "any|remote|hybrid|onsite"}
   {"type": "availability", "start": "YYYY-MM", "type": "co-op|internship|full-time"}
   {"type": "note"}                       (anything else worth remembering)
   Only record what the student stated. "Only for a really strong offer" is only_strong_offer.
   Levels: 1 = course or small project, 2 = job or substantial project, 3 = designed, led or owned it.
   Current profile: {compact}
   Skills: {taxonomy}
   ```
   - `compact` is a short JSON of the current skills (`id:level`), prefs, visa, location and availability.
   - The user message is the note.
2. Apply each change in code. Model boundary: anything invalid goes to `ignored` with a reason, never stored.
   - **`skill`**: resolve the id and check the level is 1 to 3.
     - Existing skill: append `{"source": "chat", "text": note}` if that text is not already there.
       `level = max(old, new)`; never lower it.
     - New skill: add it with that chat evidence.
     - Record `action` as `added`, `raised` or `evidence_added`.
   - **`company_pref`**: the stance must be valid. `min_pay` is a number or null; if it is a number over
     1000, it is annual, so divide by 2080 (same rule as `parse_hourly`). Replace any entry for the same
     company (case-insensitive), else append.
   - **`visa`**: both flags must be bools.
   - **`location`**: `remote` must be valid and `preferred` a list of strings.
   - **`availability`**: strings or null.
   - **`note`**: append the note text to `notes` if not already present.
3. If no change applied, append the note to `notes` and report `{"type": "note"}`, so the statement is never
   lost.
4. Then `_profile.validate(profile, candidate_id)`, `UPDATE candidates SET profile_json=?, updated=?`, and
   `DELETE FROM matches WHERE candidate_id=?` (the scores are stale).
5. Mock: `{"changes": [{"type": "company_pref", "company": "Acme", "stance": "only_strong_offer",
   "min_pay": None}]}`.

## Step 7. Tests: `tests/test_profile_tools.py` (30 min)

Use `tmp_db` and `mock_llm`; monkeypatch `_llm.chat_json` for crafted replies; call `module.main()` with
`sys.argv` patched.

- `_resume_text`:
  - `test_txt_and_md`.
  - `test_docx_built_in_test`: write a minimal `.docx` with `zipfile` and one `word/document.xml`.
  - `test_pdf_without_pypdf_raises`: monkeypatch `builtins.__import__` or `sys.modules["pypdf"] = None`.
  - `test_empty_raises`.
  - `test_unknown_extension_raises`.
- `ingest_profile`:
  - `test_mock_creates_c031_after_seed`, with `synthetic` 0 and a valid profile.
  - `test_chat_source_kept`: the docker evidence source is `chat`.
  - `test_duplicate_skills_merge`.
  - `test_null_visa_reported_missing`.
  - `test_unknown_skill_dropped_and_reported`.
- `update_profile`:
  - `test_mock_adds_acme_pref`.
  - `test_pref_replaced_case_insensitive`.
  - `test_skill_level_never_lowered`.
  - `test_chat_evidence_appended`.
  - `test_invalid_stance_ignored`.
  - `test_annual_min_pay_converted`.
  - `test_matches_cleared`.
  - `test_unknown_candidate_raises`.
- `match_candidates`:
  - `test_unapproved_role_raises`.
  - `test_shortlist`. Insert an approved role plus its internal job by hand, using the fixture Acme job's
    requirements, until C's tools merge. Then:
    - c002 is `match`.
    - Candidates with `never` for Acme are absent.
    - There is no `hidden` route and no `pref_note` key.
    - `evaluated == 30` and 30 rows are in `matches`.

## Step 8. `scripts/demo_check.py`, the demo gate (30 min, live model)

A stdlib script that proves plan section 5 before anyone records. It prints `PASS`/`FAIL` per beat and exits
with the number of failures.

1. Copy `work/demo_start.db` to `work/demo_check.db`. Set `DB_PATH` to it in the child processes' env, so the
   real demo DB is never touched. Run each tool as a subprocess and parse its JSON.
2. Employer beats:
   - `draft_role.py --company Acme --conversation-file data/requests/demo-acme-conversation.txt`.
   - Requirements include `react-native` and `mysql` as must.
   - `approve_role`, then `match_candidates --limit 10`: c002 is `match`, and one of its `top_evidence` lines
     is c002's chat MySQL evidence.
3. Student beats:
   - `ingest_profile --name "Jordan Rivera" --text-file tests/fixtures/resume.txt`.
   - `update_profile --note "I'd only go to Palantir for a really strong offer, at least 60 an hour"`: a
     Palantir `company_pref` with `min_pay` 60.
   - `match_jobs --limit 8`, which must show:
     - `internal:<role>` is present.
     - At least 1 `stretch`.
     - At least 1 job with a `clearance` flag.
     - At least 2 distinct real companies.
   - `apply` to the internal job gives status `submitted`.
4. Run it on your laptop through the tunnel after G2, then A runs it in the sandbox after wave 2.
   - **If a beat fails, fix the data, not the tools.** Change the `extract_reqs` output via prompt fixes
     (tell B), the snapshot companies (B), or c002.
   - Never hand-edit `matches`.

## Step 9. PRs

1. c002 and the demo conversation (G0 to G1).
2. `_resume_text` (G1).
3. `ingest_profile` fixes (G1).
4. `match_candidates` (G2; needs C's `approve_role` merged, or your hand-built test row).
5. `update_profile` (G2).
6. `demo_reset` and `demo_check` (G2).

`bash scripts/check_local.sh` passes before each. Send A two README lines about profiles and the demo reset.

## Done checklist

- [ ] c002 `min_pay` null, tests green; demo conversation committed
- [ ] `_resume_text` reads `.txt`, `.md`, `.docx` and `.pdf` with clear errors
- [ ] `ingest_profile` keeps chat-sourced evidence, merges duplicates, reports `missing`
- [ ] `update_profile` applies typed changes, reports `ignored`, clears stale matches
- [ ] `match_candidates` hides hidden and excluded, has no `pref_note`, shows c002 as `match`
- [ ] `demo_reset.sh` takes seconds after the first live build
- [ ] `demo_check.py` all PASS on the laptop (tunnel) and in the sandbox
