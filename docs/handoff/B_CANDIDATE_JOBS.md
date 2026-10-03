# Handoff B: candidate job pipeline

Paste this file as the first message of a fresh Claude Code chat. Also read `docs/PLAN_MVP_COMPLETION.md`
(team plan and locked decisions), `AGENTS.md` (binding coding rules), `MASTER_CONTEXT.md` sections 6.4, 7, 8,
9 and 10, and the docstrings of `tools/_db.py`, `tools/_taxonomy.py`, `tools/_llm.py` and `tools/_match.py`.

## 0. Your outcome

Real early-career postings from six companies are in committed snapshots. `fetch_jobs --offline` loads them,
and `extract_reqs` turns each into taxonomy requirements plus sponsorship, clearance and hourly pay.
`list_jobs`, `apply` and `match_jobs` give the student flow what the demo needs. Each tool has unit tests.

You own: `data/companies.json`, `data/snapshots/*.json`, `tools/fetch_jobs.py`, `tools/extract_reqs.py`,
`tools/list_jobs.py`, `tools/apply.py`, `tools/match_jobs.py` and `tests/test_candidate_tools.py`.

## 1. Setup

```bash
git fetch && git checkout -b b-candidate origin/main     # after A merged origin/skills (G0)
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements-dev.txt   # macOS: .venv/bin/python
cp .env.example .env            # MOCK_LLM=1 until step 8
bash scripts/check_local.sh     # must be all PASS before you start
```

`extract_reqs.py` and `match_jobs.py` already exist from `origin/skills`. You are fixing them, not rewriting
them. Until your snapshots land, use the fixture jobs: `python scripts/seed_db.py --reset --with-test-jobs`.

## 2. Rules that bite here

- ATS JSON and model output are external boundaries. Normalize them, with a comment that names the boundary.
  Everything after normalization is trusted.
- No silent `continue`. Anything dropped or failed is reported in the tool output (`failed`,
  `dropped_skills`).
- Use `import _llm` and call `_llm.chat_json(...)`. Do not use `from _llm import chat_json`, or tests cannot
  monkeypatch it.
- Close connections in `try/finally`. Bad user input (an unknown candidate or job id) raises `ValueError`.

---

## Step 1. `data/companies.json` (5 min)

These were checked live on 2026-10-03; each has US early-career postings:

```json
[
  {"company": "Formlabs",  "source": "greenhouse", "slug": "formlabs"},
  {"company": "Datadog",   "source": "greenhouse", "slug": "datadog"},
  {"company": "Waymo",     "source": "greenhouse", "slug": "waymo"},
  {"company": "Robinhood", "source": "greenhouse", "slug": "robinhood"},
  {"company": "Figma",     "source": "greenhouse", "slug": "figma"},
  {"company": "Palantir",  "source": "lever",      "slug": "palantir"}
]
```

Why these:
- **Formlabs** (Somerville, MA): mechanical, hardware and test interns, a good fit for Jordan (c001).
- **Datadog**: a Boston software intern.
- **Palantir**: US-government internships that require US person status, which gives the demo's real
  `clearance` flag.

## Step 2. `tools/fetch_jobs.py` (35 min)

Contract: `fetch_jobs.py [--source greenhouse|lever|workday|all] [--offline] [--per-company 5]`, which returns
`{"new": [{"id","company","title","url"}], "total": n, "failed": [{"company","error"}]}`.

Module constants (tests monkeypatch them):

```python
SNAPSHOT_DIR = _config.DATA_DIR / "snapshots"
COMPANIES = _config.DATA_DIR / "companies.json"
GREENHOUSE = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
LEVER = "https://api.lever.co/v0/postings/{slug}?mode=json"
EARLY = re.compile(r"\b(intern|internship|co-?op|new grad(uate)?)\b", re.I)
US = re.compile(r",\s*[A-Z]{2}\b|United States|\bUSA\b|\bUS\b|Remote|\bD\.C\.")   # case-sensitive on purpose
```

The `\b` matters: without it, "intern" matches "International" and "Internal".

Functions:

1. `_get_json(url)`: `urllib.request` with a `User-Agent` header and a 20-second timeout. Raises on HTTP or
   network errors.
2. `_html_to_text(html_str)`:
   - Run `html.unescape` first: Greenhouse `content` is HTML-escaped HTML.
   - Then an `html.parser.HTMLParser` subclass collects the text data. It emits `"\n"` on `p`, `br`, `li`,
     `div` and `h1` to `h6`.
   - Collapse 3 or more newlines to 2 and strip.
3. `_normalize_greenhouse(company, slug, raw)`, the ATS boundary. Returns
   `{"id": f"greenhouse:{slug}:{raw['id']}", "source": "greenhouse", "company", "title": raw["title"],
   "url": raw["absolute_url"], "location": raw["location"]["name"], "description": _html_to_text(raw["content"])}`.
4. `_normalize_lever(company, slug, raw)` returns the same shape:
   - `id` is `f"lever:{slug}:{raw['id']}"`, `title` is `raw["text"]` and `url` is `raw["hostedUrl"]`.
   - `location` is `raw["categories"].get("location")`; comment that this is the ATS boundary, since the
     field can be missing.
   - `description` is `raw["descriptionPlain"]`, then for each list in `raw["lists"]` its `text` plus
     `_html_to_text(content)`, then `raw.get("additionalPlain") or ""`.
5. `_select(jobs, per_company)`:
   - Keep jobs where `EARLY.search(title)` and `US.search(location or "")`.
   - Deduplicate by title. Palantir posts the same internship once per city. Prefer the location that
     contains `", MA"` or `"Boston"`, else the first one.
   - Sort by id and keep the first `per_company`.
6. `_fetch_company(entry, per_company)`:
   - Greenhouse: `_get_json(...)["jobs"]`. Lever: the list itself.
   - Normalize, select, then write `SNAPSHOT_DIR / f"{source}-{slug}.json"`
     (`json.dumps(jobs, indent=1, ensure_ascii=False, sort_keys=True)`, `newline="\n"`) and return the jobs.
   - `workday` raises `ValueError("workday is not configured (out of MVP scope)")`.
7. `_load_snapshots(source)`: read `SNAPSHOT_DIR/*.json`, keeping files whose name starts with `source + "-"`
   (or all of them for `all`). Each job must have the 7 keys. A missing key is a `RuntimeError` naming the
   file, because snapshots are our own files.
8. `_insert(conn, jobs)`:
   ```sql
   INSERT OR IGNORE INTO jobs (id, source, company, title, url, location, description, first_seen)
   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
   ```
   A job is new when `cursor.rowcount == 1`.
9. `main()`:
   - **Offline**: load the snapshots.
   - **Online**: for each company in `COMPANIES` matching `--source`, wrap `_fetch_company` in
     `try/except (urllib.error.URLError, OSError, KeyError, ValueError)`. Failures go to `failed` with the
     company and `str(e)`; the other companies still run. Comment: "External boundary: one ATS failing must
     not stop the others".
   - Insert, commit, then
     `total = SELECT COUNT(*) FROM jobs WHERE source IN ('greenhouse','lever')`.

Then run it online once on your laptop:

```bash
python tools/fetch_jobs.py --source all
```

Expect about 25 to 30 jobs. Commit all six `data/snapshots/*.json`, and check one by eye: the description is
readable text with no `&lt;` or tags. Run `python tools/fetch_jobs.py --offline` twice; the second run has
`new: []`.

## Step 3. Fix `tools/extract_reqs.py` (30 min)

Keep the existing structure and change the following.

1. `import _llm`, then call `_llm.chat_json(..., max_tokens=4000)`. Do not use 3072: thinking tokens count
   (MASTER_CONTEXT section 4).
2. Select only non-internal jobs (internal ones are copied from the approved role), oldest first:
   ```sql
   SELECT id, title, company, description FROM jobs
   WHERE source != 'internal' [AND requirements_json IS NULL]
   ORDER BY first_seen, id LIMIT ?
   ```
3. The user message is the title, the company and `description[:6000]`.
4. Extend the prompt's return shape:
   ```
   {"requirements": [{"skill_id": "...", "level": 1, "importance": "must|nice",
                      "why": "short reason", "evidence_text": "verbatim line from the posting"}],
    "sponsorship": true | false | null,
    "clearance": "none" | "us_person" | "clearance",
    "pay": {"min": number, "max": number or null, "period": "hour|week|month|year"} or null}
   ```
   Add these prompt rules:
   - `sponsorship` is false only if the posting says it will not sponsor visas or requires work
     authorization without sponsorship. It is true if it says it sponsors, and null if it says nothing.
   - `clearance` is `clearance` if a security clearance is required (or must be obtainable). It is
     `us_person` if US citizenship, US person status or export control (ITAR/EAR) is required. Otherwise
     `none`.
   - `pay` is the stated pay in USD with its period, or null if not stated. Never guess.
   - `importance` is `must` for required or "minimum" qualifications and `nice` for preferred ones.
     Include soft skills only when stated.
5. Requirements go through `_role.clean_requirements(raw, source=job_id)` (C, step 1). It resolves aliases,
   checks that the level is an int from 1 to 3 and that importance is `must|nice`, dedupes skills, keeps
   `evidence_text`, and returns `(requirements, dropped)`.
   - Until C's PR merges, put an identical private `_clean_requirements` in your file and switch when
     `_role.py` lands.
   - `dropped` goes to `dropped_skills[job_id]` in the output.
6. Model boundary for the other fields:
   - `sponsorship` must be `True`, `False` or `None`; anything else becomes `None`.
   - `clearance` outside `{"none","us_person","clearance"}` becomes `"none"`.
   - `pay` goes through `_hourly_text`.
7. Add `_hourly_text(pay) -> str | None`:
   ```python
   PER_HOUR = {"hour": 1, "week": 40, "month": 2080 / 12, "year": 2080}
   # Model boundary: pay may be malformed; unparseable pay is unknown, never zero
   ```
   - It returns `None` unless `pay` is a dict with a numeric `min` and a `period` in `PER_HOUR`.
   - Otherwise `lo = min / PER_HOUR[period]`. If `max` is a number, the result is
     `f"{lo:.0f}-{max/PER_HOUR[period]:.0f} USD/hour"`, else `f"{lo:.0f} USD/hour"`.
   - Check: Formlabs `$1,575-$1,950` per week gives `"39-49 USD/hour"`; Palantir `$10,000/month` gives
     `"58 USD/hour"`.
8. A model `error` goes to `failed` with `{"job_id", "error"}`. Zero requirements after cleaning also goes to
   `failed`, with `"error": "no taxonomy skills found"`, and stores `requirements_json = "[]"` so `--pending`
   does not retry it forever.
9. Update:
   ```sql
   UPDATE jobs SET requirements_json=?, sponsorship=?, clearance=?, pay=? WHERE id=?
   ```
   `sponsorship` is stored as `None` or `int(bool)`. Commit after each job, so a crash midway keeps the work.
10. Output: `{"processed": n, "failed": [...], "dropped_skills": {job_id: [...]}}`.
11. Update the mock (`_MOCK`) to include `"sponsorship": None`, `"clearance": "none"` and
    `"pay": {"min": 30, "max": 40, "period": "hour"}`.

## Step 4. `tools/list_jobs.py` (10 min)

```sql
SELECT id, source, company, title, url, location, pay,
       requirements_json IS NOT NULL AS extracted
FROM jobs [WHERE source = ?] ORDER BY first_seen DESC, id LIMIT ?
```

Return `{"jobs": [...], "total": count matching the filter}`, with `extracted` as a bool.

## Step 5. `tools/apply.py` (10 min)

1. The candidate must exist (`ValueError(f"candidate {id} not found")`), and so must the job.
2. `INSERT OR IGNORE INTO applications (job_id, candidate_id, status, created) VALUES (?, ?, 'submitted', ?)`.
3. If `rowcount == 0`, read the existing row and return it with `"already_applied": true`.
4. Return `{"application": {"job_id", "candidate_id", "status", "created"}, "already_applied": bool}`.
5. Docstring: it never contacts an external ATS.

## Step 6. Fix `tools/match_jobs.py` (10 min)

1. `try/finally` around the connection. An unknown candidate raises `ValueError` instead of returning an
   error dict.
2. Still upsert every evaluated route (including `hidden`) into `matches`, but leave `hidden` and `excluded`
   out of the returned list, so `--limit` is not spent on non-matches.
3. Keep `category_scores` and `pref_note`. Add `"source"` (so the agent can say "posted in this app" for
   `internal`) and `"pay"`.
4. Remove the silent `continue` on empty requirements. Filter in SQL instead:
   `WHERE requirements_json IS NOT NULL AND requirements_json != '[]'`.
5. When D's PR adds `_match.job_from_row(row)` (the DB row to `evaluate` job dict conversion, used by
   `match_candidates` too), replace your inline conversion with it, so both sides convert identically.

## Step 7. Tests: `tests/test_candidate_tools.py` (25 min)

Use the `tmp_db` and `mock_llm` fixtures. Call `module.main()` with `monkeypatch.setattr(sys, "argv", [...])`.
Monkeypatch `fetch_jobs.SNAPSHOT_DIR` and `fetch_jobs.COMPANIES` to `tmp_path`, and `_llm.chat_json` for
crafted model replies.

- `test_html_to_text_unescapes_and_strips`: `&lt;p&gt;A &amp;amp; B&lt;/p&gt;&lt;li&gt;x&lt;/li&gt;` gives
  `"A & B\nx"`.
- `test_select_filters_us_early_career`:
  - Kept: "Mechanical Engineering Intern" at "Somerville, MA" and "Software Engineering Intern" at
    "Boston, Massachusetts, USA".
  - Dropped: "Internal Tools Engineer" and "International Sales Lead" (not early career), and
    "Software Engineer Intern" at "Paris, France".
- `test_select_dedupes_title_prefers_ma`: the same title in "New York, NY" and "Boston, MA" keeps Boston.
- `test_normalize_lever_joins_lists`.
- `test_fetch_offline_reports_new_once`: the first run gives `len(new) == 2` and the second `new == []`.
- `test_fetch_online_failure_is_reported`: monkeypatch `_get_json` to raise `urllib.error.URLError`. The
  company appears in `failed` and the other company is still inserted.
- `test_hourly_text`: covers hour, week (Formlabs), month (Palantir), year, `max` null, a bad period and
  `None`.
- `test_extract_sets_columns`: a crafted reply with `clearance: "us_person"`, weekly pay and an unknown
  skill. The DB row has those columns, and the unknown skill is in `dropped_skills`.
- `test_extract_skips_internal`: insert an `internal:r001` row with requirements; it is unchanged after
  `extract_reqs` without `--pending`.
- `test_extract_model_error_goes_to_failed`.
- `test_list_jobs_source_filter`.
- `test_apply_twice_reports_already_applied`.
- `test_apply_unknown_job_raises`.
- `test_match_jobs_hides_hidden`: seed with `--with-test-jobs`. For c001, `test:cloudline:6` is `hidden`.
  It is not in the output, but it is in `matches`.

## Step 8. Live run and quality pass (20 min, tunnel open, `MOCK_LLM=0`)

```bash
python scripts/seed_db.py --reset
python tools/fetch_jobs.py --offline
time python tools/extract_reqs.py --pending --limit 40
python tools/list_jobs.py --limit 40
```

Check by eye:
- Every job has 3 to 10 requirements.
- Formlabs mechanical interns map to `solidworks`, `cad`, `3d-printing` or `matlab`.
- Palantir US-government postings have `clearance` `us_person` or `clearance`.
- Pay reads as plausible hourly numbers.

Post the timing in team chat; D and A use it to size the demo prep. Fix the prompt if something is
systematically wrong.

## Step 9. PRs

1. `companies.json`, `fetch_jobs` and snapshots (G1).
2. `list_jobs` and `apply` (G1).
3. The `extract_reqs` and `match_jobs` fixes (G2).
4. Tests can ride with each PR.

`bash scripts/check_local.sh` passes before each one. Send A two README lines about the job pipeline.

## Done checklist

- [ ] 6 companies, snapshots committed, offline load is idempotent
- [ ] `extract_reqs` writes requirements, `sponsorship`, `clearance` and hourly `pay`; never touches internal jobs
- [ ] `list_jobs`, `apply` and `match_jobs` (hidden dropped) match the contracts
- [ ] `tests/test_candidate_tools.py` green; smoke shows all your tools `OK`
- [ ] Live extraction timed and quality-checked
