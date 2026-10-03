# Handoff C: employer pipeline

Paste this file as the first message of a fresh Claude Code chat. Also read `docs/PLAN_MVP_COMPLETION.md`
(team plan and locked decisions), `AGENTS.md` (binding coding rules), `MASTER_CONTEXT.md` sections 2, 6.1,
6.3, 6.4, 8 and 9, `tools/_profile.py` (the validation style to copy), `tools/_llm.py` and
`skills/role-architect/SKILL.md`.

## 0. Your outcome

A hiring manager's conversation becomes a draft role (public JD plus private context), stored and shown.
Approving it publishes job `internal:{role_id}`, which students match against and D's `match_candidates`
shortlists. One shared validator keeps every role valid.

You own: `tools/_role.py`, `tools/draft_role.py`, `tools/show_role.py`, `tools/approve_role.py`,
`tests/test_role.py` and `tests/test_employer_tools.py`. `match_candidates.py` moved to D. Your
`approve_role` row format is what it reads.

## 1. Setup

```bash
git fetch && git checkout -b c-employer origin/main
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements-dev.txt   # macOS: .venv/bin/python
cp .env.example .env            # MOCK_LLM=1 until step 6
bash scripts/check_local.sh
```

## 2. Rules that bite here

- Model output is the only external boundary. Clean it once, in `_role.py`, with a comment naming the
  boundary.
- After cleaning, a role is trusted: `_role.validate` raises `ValueError(f"{source}: {field} {problem}")`,
  exactly like `_profile.validate`.
- Caller rule for `_llm.chat_json`: if `"error" in out`, return it unchanged. If a key you need is missing,
  return `{"error": "model output missing <key>"}`.
- Use `import _llm`, then `_llm.chat_json(...)`, with `max_tokens=4000`. `try/finally` on every connection.

---

## Step 1. `tools/_role.py` (15 min, PR first, B depends on it)

```python
"""Role validation and model-output cleaning (MASTER_CONTEXT 6.3). Owner: C.

    validate(role: {"public", "private"}, source: str) -> None
        Raises ValueError(f"{source}: {field} {problem}") on the first problem.
    clean_requirements(raw, source) -> (requirements, dropped)
        Model boundary: resolves aliases, enforces level 1-3 and must|nice,
        dedupes skills, keeps evidence_text if present. dropped = [{"skill", "reason"}].
    clean_public(raw, source) -> dict
        Model boundary: coerces sponsorship and clearance; raises ValueError if unusable.
"""
```

The rules.

**`validate`**:
- `public` has `title`, `description`, `location`, `sponsorship`, `clearance` and `pay`:
  - `title` and `description` are non-empty strings.
  - `location` is a string or None.
  - `sponsorship` is a bool or None.
  - `clearance` is in `{"none","us_person","clearance"}`.
  - `pay` is a string or None.
- `private` has `requirements`, `seniority`, `team_context` and `timeline`. The last three are strings or
  None.
- `requirements` is a non-empty list. Each item has:
  - `skill_id` known to `_taxonomy` and unique across the list.
  - `level` that is an int from 1 to 3 (`type(x) is int`, as in `_profile`).
  - `importance` that is `must` or `nice`.
  - `why`, a non-empty string.

**`clean_requirements(raw, source)`**:
- If `raw` is not a list, raise `ValueError(f"{source}: requirements must be a list")`.
- For each item:
  - It must be a dict with a string `skill_id`. Otherwise `dropped.append({"skill": repr(item)[:60],
    "reason": "malformed"})`.
  - `skill_id = _taxonomy.resolve(item["skill_id"])`. `None` means dropped with reason `not in taxonomy`.
  - `level`: an int, or a digit string turned into an int. Outside 1 to 3, it is dropped with reason
    `level <x>`.
  - `importance`: lowercased. Not `must` or `nice` means dropped with reason `importance <x>`.
  - `why`: `str(item.get("why") or "").strip()`, or `_taxonomy.name_of(skill_id)` if empty.
  - Keep `evidence_text` if it is a non-empty string (B's job rows need it).
- Dedupe by `skill_id`: keep `must` over `nice`, then the higher level, and join the two `why` texts with
  `"; "`.
- Return in first-seen order.

**`clean_public(raw, source)`**:
- `sponsorship`: `True` / `False` / `None` pass through. The strings `"yes"`/`"true"` and `"no"`/`"false"`
  are mapped. Anything else becomes `None`, because unknown never flags.
- `clearance`: lowercased, with spaces turned into `_`. Not in the set means `"none"`; comment this as the
  model boundary.
- `pay`: a stripped string or None.
- `title` and `description` must be non-empty after strip, or `ValueError`.

**`tests/test_role.py`**:
- `test_validate_accepts_fixture_role`: the PUBLIC and PRIVATE dicts at the top of
  `tests/test_screen_resumes.py`.
- `test_validate_rejects`, parametrized: a bad clearance, `level` 4, `level` "2", `importance` "required",
  a duplicate skill, empty requirements and an unknown `skill_id`. Each checks the field named in the message.
- `test_clean_resolves_alias_and_drops_unknown`: "React Native" becomes `react-native`; "COBOL" is dropped
  with reason `not in taxonomy`.
- `test_clean_dedupes_must_over_nice`.
- `test_clean_public_coerces`.

## Step 2. `tools/draft_role.py` (35 min)

Contract: `draft_role.py --company "X" --conversation-file PATH [--paid]` returns
`{"role_id", "status": "draft", "company", "public", "private", "dropped_skills"}`.

1. Read the conversation file (UTF-8). If it is empty, raise `ValueError`.
2. The system prompt (keep it tight; the model is a 35B MoE running locally):
   ```
   You turn a hiring manager's conversation into one job description for a university career office.
   Return only JSON:
   {"public": {"title": str, "description": str, "location": str or null,
               "sponsorship": true|false|null, "clearance": "none"|"us_person"|"clearance",
               "pay": str or null},
    "private": {"requirements": [{"skill_id": str, "level": 1|2|3, "importance": "must"|"nice",
                                  "why": str}],
                "seniority": str or null, "team_context": str or null, "timeline": str or null}}
   Rules:
   - description: 80 to 150 words, plain language, what the person will build and own. No team size,
     no timeline, nothing from team_context.
   - location: "City, ST (onsite|hybrid|remote)" when known.
   - sponsorship: true if they said they can sponsor visas, false if they cannot, null if not discussed.
   - clearance: "us_person" if US citizenship or export control is required, "clearance" if a security
     clearance is required, otherwise "none".
   - pay: as stated, like "35-45 USD/hour" or "90000-110000 USD/year"; null if not stated.
   - requirements: 3 to 8 items. skill_id only from the list below. At most 4 "must" (cannot do the job
     without it); the rest "nice". level: 1 = course or small project, 2 = used in a job or substantial
     project, 3 = designed, led or owned it. why: one short phrase tied to the conversation.
   - seniority: one of co-op, intern, new grad, experienced.
   Skills:
   {taxonomy}
   ```
   The user message is `f"COMPANY: {company}\n\nCONVERSATION:\n{text}"`.
3. The mock must match `tests/fixtures/conversation.txt`:
   - `public`: title "Mobile App Engineer (Co-op)", a 2-sentence description, "Boston, MA (hybrid)",
     sponsorship true, clearance "none", pay "35-45 USD/hour".
   - `private.requirements`: `react-native` 2 must, `mysql` 2 must, `python` 1 nice, `git` 1 nice.
   - seniority "co-op", team_context "2 engineers, no designer", timeline "start Jan 2027".
4. Then:
   - If `"error" in out`, return it.
   - Missing `public` or `private` means `{"error": "model output missing public|private"}`.
   - `public = _role.clean_public(...)` and `requirements, dropped = _role.clean_requirements(...)`.
   - Empty requirements returns `{"error": "model found no taxonomy skills; ask the manager what the person
     will build", "dropped_skills": dropped}`.
   - Build `private` (the three text fields: model boundary, a string or None), then
     `_role.validate({"public": public, "private": private}, "draft")`.
5. Insert:
   - `role_id = _db.next_id(conn, "roles", "r")`.
   - `INSERT INTO roles (id, company, paid, status, public_json, private_json, created)`, with status
     `'draft'` and `paid = int(args.paid)`.

## Step 3. `tools/show_role.py` (10 min)

1. `SELECT * FROM roles WHERE id = ?`. An unknown id raises `ValueError(f"role {id} not found")`.
2. Return `{"role_id", "company", "paid": bool, "status", "public", "private", "job_id"}`. `job_id` is
   `f"internal:{id}"` if the status is `approved`, else None.

## Step 4. `tools/approve_role.py` (25 min)

Contract: `approve_role.py --role ID [--edits-file PATH]` returns
`{"role_id", "job_id": "internal:ID", "status": "approved", "public", "private"}`.

1. Load the role (unknown raises `ValueError`).
2. Edits: a JSON object with only the keys `public` and/or `private`; anything else raises `ValueError`.
   - `public.update(edits["public"])` and `private.update(edits["private"])`.
   - If `requirements` is in the private edits, it replaces the whole list. Run it through
     `_role.clean_requirements`; any dropped entry raises `ValueError`, because a person typed it and should
     see the problem.
   - Then `_role.validate(...)`.
3. Save:
   - `UPDATE roles SET status='approved', public_json=?, private_json=?`.
   - Approving an approved role again is allowed: edits re-apply and the job is rewritten.
4. Publish the internal job. **D's `match_candidates` and B's `match_jobs` read these exact columns.**
   ```sql
   INSERT OR REPLACE INTO jobs (id, source, company, title, url, location, description, role_id,
     requirements_json, sponsorship, clearance, pay, paid, first_seen, notified)
   VALUES ('internal:'||?, 'internal', ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
   ```
   - `requirements_json` is the role's requirements, each with `evidence_text = why` (6.4).
   - `sponsorship` is `None` or `int(bool)`. `paid` comes from the role row.
   - On a re-approve, keep the original `first_seen`: read it before replacing.
5. On a re-approve, `DELETE FROM matches WHERE job_id = ?` (the scores are stale).

## Step 5. `tests/test_employer_tools.py` (25 min)

Use `tmp_db` and `mock_llm`, plus `seed_db` to load candidates where needed.

- `test_draft_mock_creates_r001_draft`.
- `test_draft_drops_unknown_skill_and_reports_it`: monkeypatch `_llm.chat_json`.
- `test_draft_no_skills_returns_error`.
- `test_draft_model_error_passes_through`.
- `test_show_unknown_raises`.
- `test_show_job_id_only_when_approved`.
- `test_approve_publishes_internal_job`:
  - The jobs row has `source='internal'`, `role_id`, `sponsorship` 1 and `pay` "35-45 USD/hour".
  - Every requirement has `evidence_text`.
  - `_match.evaluate` accepts the row converted to a job dict, the same conversion `match_jobs` does.
- `test_approve_edits_merge_and_replace_requirements`.
- `test_approve_bad_edit_key_raises`.
- `test_reapprove_keeps_first_seen_and_clears_matches`.
- `test_connected_story`: seed candidates, draft, approve, then run `match_jobs` for `c001`. The output
  contains `internal:r001`.

## Step 6. Live prompt tuning (25 min, tunnel open, `MOCK_LLM=0`)

Build five conversation files in `work/` (gitignored):

- The three `data/requests/*.txt`, each with one invented manager answer line appended.
- `tests/fixtures/conversation.txt`.
- The locked demo exchange from plan section 5, steps 1 and 2.

Run each with `time python tools/draft_role.py --company Acme --conversation-file work/<f>.txt`.

Acceptance:

- **The demo exchange must give `react-native` and `mysql` as `must` at level 2, sponsorship true, and pay
  "35-45 USD/hour".** The c002 hero beat depends on `mysql`. If the model picks `sql` or `postgresql`, tighten
  the prompt: "use the most specific skill the manager named".
- test-rig: mechanical and controls skills (`solidworks`, `plc`, `labview`, `arduino`, `embedded-c`).
- dashboard: data skills (`sql`, `data-visualization`, `tableau`, `pandas`).
- The description contains no team size or timeline.
- Each call takes under 60 seconds.

Commit the prompt changes. Post the demo exchange's output in team chat so D can check the shortlist.

## Step 7. Screening outside applicants on an approved role (15 min)

1. With recruit deps installed (`pip install -r requirements-recruit.txt`), approve the demo role.
2. Write 3 short synthetic `.txt` resumes into `work/applicants/` (one strong, one partial, one with no
   React Native or MySQL). Optionally add PDFs from `python scripts/generate_edge_case_resumes.py`; it takes no
   arguments and writes to `../Test Resume/Edge Cases/`, outside the repo.
3. Run:
   ```bash
   python tools/screen_resumes.py --role r001 --resumes work/applicants tests/fixtures/resume.txt
   ```
4. Check that `rubric_source` is `role`, and that the criteria titles are the role's skill names.
5. Send A the output and anything the role-architect steps 8 and 9 need to change.

## Step 8. PRs

1. `_role.py` and its tests, as early as possible (B and D need it).
2. `draft_role` and `show_role` (G1).
3. `approve_role` and the employer tests (before G2).
4. Prompt tuning.

`bash scripts/check_local.sh` passes before each. Send A two README lines about the employer flow.

## Done checklist

- [ ] `_role.py` validates and cleans; B's `extract_reqs` uses `clean_requirements`
- [ ] `draft_role`, `show_role` and `approve_role` meet their contracts; smoke `OK`
- [ ] The approved role is visible to `match_jobs` (the connected-story test)
- [ ] The demo exchange yields React Native and MySQL as must at level 2, live, in under 60 seconds
- [ ] `screen_resumes --role` works on the approved role
