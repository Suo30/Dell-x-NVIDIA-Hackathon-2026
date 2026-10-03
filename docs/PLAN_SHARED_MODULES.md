# Plan: shared modules and seed data

Scope: `tools/_db.py`, `tools/_taxonomy.py` + `data/skills.json`, `tools/_llm.py`, `tools/_match.py`,
and seed data (`gen_candidates.py`, `seed_db.py`, candidate files, demo requests).

Goal: every piece is testable on a laptop with no box, and `_llm` is also testable against the box
through the SSH tunnel. Nothing here needs the agent, Slack or the sandbox.

Owners follow MASTER_CONTEXT section 5. Contract additions are listed in section 8 and must be
copied into MASTER_CONTEXT by PR.

---

## 0. Rules for all modules

- Read settings at call time: `_config.DB_PATH`, never `from _config import DB_PATH`. Tests swap
  `_config` values with `monkeypatch`, and an early import would freeze the real path.
- Pass `encoding="utf-8"` to every `open` / `read_text` / `write_text`. Windows defaults to cp1252.
- Errors follow AGENTS.md: `RuntimeError` for broken team data or internal contracts, `ValueError` for
  bad user input. The message names the file, id or field.
- Close sqlite connections when done. Windows cannot delete an open DB file, so pytest temp cleanup fails.
- Floating-point comparisons go through `tools/aux_math.py` (AGENTS.md requires it; it does not exist yet).

---

## 1. Test setup (A, 15 min, do first)

Files:
- `tests/conftest.py`: puts `tools/` and `scripts/` on `sys.path`. Fixtures:
  - `tmp_db`: monkeypatches `_config.DB_PATH` to `tmp_path / "t.db"`.
  - `mock_llm`: monkeypatches `_config.MOCK = True`.
- `pytest.ini`: registers the `live` marker and sets `addopts = -m "not live"`, so a plain run never
  needs the box.
- `tools/aux_math.py`: `EPS = 1e-6`, `ge(a, b)`, `lt(a, b)`, `eq(a, b)`.

Run (Git Bash or PowerShell):
```sh
pip install -r requirements-dev.txt
python -m pytest -q
```

---

## 2. `_db` (D, 20 min)

API:
- `connect() -> sqlite3.Connection`: create the parent dir of `DB_PATH`, `sqlite3.connect(str(path), timeout=10)`,
  `row_factory = sqlite3.Row`, `executescript(schema.sql)`.
- `now() -> str`: `datetime.now(timezone.utc).isoformat(timespec="seconds")`.
- `next_id(conn, table, prefix) -> str`: highest numeric suffix among ids with that prefix, plus 1,
  zero-padded to 3 (`c031`, `r001`). `table` must be `candidates` or `roles`, else `RuntimeError`.
  Used by `ingest_profile` (`c`) and `draft_role` (`r`) so ids stay consistent.

Tests, `tests/test_db.py`:
| Case | Expect |
|---|---|
| `connect()` on a new path | file exists, exactly the 5 tables |
| `connect()` twice, insert between | no error, row still there |
| `now()` | parses with `datetime.fromisoformat`, tz is UTC |
| `next_id` on empty table | `c001` |
| after inserting `c001`, `c007` | `c008` |
| `r` prefix on roles | independent of candidates |
| `next_id(conn, "jobs", "j")` | `RuntimeError` |

Laptop check (Git Bash):
```sh
DB_PATH=work/try.db python -c "import sys; sys.path.insert(0,'tools'); import _db; c=_db.connect(); print([r[0] for r in c.execute(\"select name from sqlite_master where type='table' order by 1\")])"
```
Expect `['applications', 'candidates', 'jobs', 'matches', 'roles']`.
PowerShell: run `$env:DB_PATH="work/try.db"` first, then the same `python -c ...`.

---

## 3. `skills.json` + `_taxonomy` (D, 45 min)

Data rules for `data/skills.json`:
- 40 to 60 entries. Categories: `backend`, `frontend`, `mobile`, `data`, `cloud-devops`, `mechanical`, `soft`.
- `id`: lowercase `[a-z0-9-]+` (`react-native`, `cpp`, `csharp`, `nodejs`).
- `aliases`: lowercase. No alias may equal another skill's id, name or alias after normalizing.
- Must cover every skill in the SKILLS line of `tests/fixtures/resume.txt` (Python, MySQL, SolidWorks,
  MATLAB, React Native, Git), plus Docker (smoke test note) and what `tests/fixtures/conversation.txt`
  implies (mobile app, MySQL).
- Punctuation names need explicit aliases: C++ (`c plus plus`), C# (`c sharp`), Node.js (`node`, `node.js`),
  .NET (`dotnet`), CI/CD (`ci cd`, `continuous integration`).

API:
- `_norm(s)`: lowercase, `-` and `_` become spaces, collapse whitespace, strip. No other punctuation is
  removed, so `c++`, `c#` and `c` stay distinct.
- `load()`: `functools.lru_cache`. On first load, validate the required keys (`id`, `name`, `category`, `aliases`),
  the id regex, the category enum, and that no normalized key collides across skills. On any violation,
  raise `RuntimeError` naming both ids and the colliding key.
- `resolve(name) -> str | None`: `None` is a valid answer (the model named a skill we do not track); callers drop it.
- `name_of(skill_id) -> str`: unknown id raises `RuntimeError` (ids only come from our own data).
- `prompt_block() -> str`: one line per skill, grouped by category: `mysql: MySQL (my sql, mariadb)`.

Tests, `tests/test_taxonomy.py`:
| Case | Expect |
|---|---|
| load real file | 40 to 60 entries, every category used |
| `resolve("MySQL")`, `"  mysql "`, `"MariaDB"` | `mysql` |
| `resolve("React-Native")`, `"react_native"`, `"React Native"` | `react-native` |
| `resolve("C++")` vs `resolve("C#")` | different ids |
| `resolve("Cobol for goats")` | `None` |
| every item in the resume fixture SKILLS line | resolves (catches data holes) |
| `name_of(id)` for every id | returns its name |
| `name_of("nope")` | `RuntimeError` |
| `prompt_block()` | `len(load())` lines, contains every id, under ~4000 chars |
| bad file in tmp (two skills share alias `js`), `DATA_DIR` monkeypatched, `load.cache_clear()` | `RuntimeError` naming both ids |

Laptop check:
```sh
python -c "import sys; sys.path.insert(0,'tools'); import _taxonomy as t; print(len(t.load())); print([t.resolve(x) for x in ['MySQL','mariadb','React Native','Node.js','C++','nonsense']])"
python -c "import sys; sys.path.insert(0,'tools'); import _taxonomy as t; print(t.prompt_block())"
```

---

## 4. `_llm` (C, 45 min)

Public API unchanged: `chat_json(system, user, *, mock, max_tokens=2048) -> dict`.

Internals, split so they can be tested without a model:
- `_post(messages, max_tokens) -> (content, finish_reason)`: `urllib.request` POST to
  `{LLM_BASE_URL}/chat/completions`. Body: `model`, `messages`, `temperature: 0`, `max_tokens`,
  `chat_template_kwargs: {"enable_thinking": false}`. Timeout 180 s.
- `_extract(text) -> dict`: drop everything up to the last `</think>`, strip ``` fences, slice from the
  first `{` to the last `}`, `json.loads`. Not a dict raises `ValueError`.

`chat_json` flow:
1. `MOCK`: return `copy.deepcopy(mock)`.
2. Network error or HTTP error: `{"error": "model unreachable at <url>: <reason>"}`.
3. `finish_reason == "length"`: `{"error": "model output truncated at max_tokens=N"}`. No retry; it would truncate again.
4. `_extract` fails: retry once, with the bad reply appended as an assistant turn plus a user turn
   `"Your last reply was not valid JSON. Return only the JSON object."`
5. Still failing: `{"error": "invalid JSON after retry: <first 200 chars>"}`.

Caller rule (B, C, D): check `"error" in out` first and return that error. The model is an external
boundary, so callers then validate the keys they need and return `{"error": "model output missing <key>"}`.

Self-check entry point: `python tools/_llm.py` (a `__main__` wrapped in `_cli.run`) sends one small
extraction (a fixed resume line plus `_taxonomy.prompt_block()` once it exists) and prints
`{"ok", "seconds", "base_url", "model", "result"}`.

Tests, `tests/test_llm.py` (no network). `_extract` cases:
| Input | Expect |
|---|---|
| `{"a": 1}` | dict |
| fenced ```` ```json ... ``` ```` | dict |
| `<think>...</think>{"a":1}` | dict |
| prose before and after the object | dict |
| nested braces | dict |
| `[1, 2]` | `ValueError` |
| `""`, `{bad` | `ValueError` |

Fake server cases: an `http.server.HTTPServer` on port 0 in a thread, serving a scripted queue of
replies and recording each request body. Monkeypatch `_config.LLM_BASE_URL` to it.
| Script | Expect |
|---|---|
| good reply | dict; 1 request; body has `model`, `temperature: 0`, `enable_thinking: false` |
| bad, then good | dict; 2 requests; second contains the retry message |
| bad, bad | `error`; exactly 2 requests |
| HTTP 500 | `error`, no exception |
| `finish_reason: "length"` | `error` mentioning `max_tokens`; 1 request |
| URL pointing at a closed port | `error` |
| `MOCK` on | returns the mock; mutating the result does not change the original |

Live check from the laptop:
```sh
# terminal 1, leave open
ssh -L 8000:127.0.0.1:8000 dell@172.20.65.171

# terminal 2
curl -s http://127.0.0.1:8000/v1/models
python tools/_llm.py                       # expect "ok": true; note "seconds"
LLM_LIVE=1 python -m pytest -m live -q     # PowerShell: $env:LLM_LIVE="1"; python -m pytest -m live -q
```
`tests/test_llm_live.py` (marked `live`): runs a real extraction on `tests/fixtures/resume.txt` with
`prompt_block()` in the system prompt. It asserts that the result is a dict with a `skills` list and that
every returned id resolves through `_taxonomy`. That proves the prompt keeps the model inside the
taxonomy. The printed time tells B the per-job cost of `extract_reqs`.

Optional, decide with curl first: if vLLM accepts `"response_format": {"type": "json_object"}` (HTTP 200
and a JSON body), add it to `_post`. If it returns 400, leave it out.

---

## 5. `_match` (B, 60 min)

Contract additions (section 8):
- The job dict passed to `evaluate` gets `"id"` (used in error messages).
- `evaluate` returns `{"score", "route", "eager", "detail"}`. `detail` follows 6.5.
- New helper `top_evidence(detail, n=2) -> list[str]`: evidence lines of strong must-haves first, then
  strong nice-to-haves. Both `match_jobs` and `match_candidates` use it, so wording matches on both sides.
- New helper `parse_hourly(pay) -> float | None`.

Rules:
- Per requirement: candidate level is that skill's level, or 0 if absent. `strong` if level >= required,
  `partial` if level == required - 1, else `none`. `evidence` is the first evidence text of that skill, or `None`.
  `closable`: partial is True; none + nice is True; none + must is False; strong is False (no gap).
- `score`: `100 * sum(w * credit) / sum(w)`, with must = 2, nice = 1 and strong / partial / none =
  1 / 0.5 / 0, rounded to 1 decimal. Empty requirements raise
  `RuntimeError("job <id> has no requirements; match only extracted jobs")`.
- `flags`, in this fixed order:
  - `sponsorship`: the profile needs sponsorship and `job.sponsorship is False`. `None` (unknown) never flags.
  - `clearance`: `job.clearance` is `us_person` or `clearance` and the profile is not a US person.
  - `location`: the job location is known; it contains neither `remote` nor `hybrid`; none of the
    preferred city names (text before the first comma, case-insensitive) appear in it; and `remote != "any"`.
- `route`: any flag is `review`; `ge(score, 70)` is `match`; `ge(score, 50)` with every gap closable is `stretch`;
  everything else is `hidden`.
- `apply_prefs`: company names compare case-insensitively.
  - `never` gives `excluded`.
  - `only_strong_offer`: a `match` or `stretch` stays as is only if `parse_hourly(pay)` is not None and
    `ge(pay, min_pay)`. Otherwise it becomes `review`, with the note
    `"only_strong_offer: pay not stated"` or `"only_strong_offer: pay 35 below minimum 45"`.
  - `eager` sets `eager: True`.
  - Prefs only demote. `hidden` stays `hidden`.
- `parse_hourly`: take the numbers in the string. For a range, use the lower bound (the conservative choice;
  confirm under Q5). A value over 1000 is treated as annual and divided by 2080. No numbers gives `None`.
- `sort_key(row)`: `(ROUTE_ORDER[route], -score, not eager, not paid)`.
- `gap_text`: `"The evidence did not show MySQL at level 2 (has level 1)"`. Level 0 uses
  `"(no evidence found)"`. One line per non-strong requirement.
- Employer side: a candidate with `never` for the company is `excluded` and never appears in `match_candidates`.

Fixtures (useful to B, C and D):
- `tests/fixtures/profile.json`: Jordan Rivera from `resume.txt` in 6.2 shape (F-1, needs sponsorship, Boston).
- `tests/fixtures/jobs.json`: a list of 6 to 8 jobs in `evaluate` input shape plus `source`, `title`, `url`.
  Entry 0 is the demo role from `conversation.txt` (mobile + MySQL, sponsors, hybrid Boston). Include one
  job with `sponsorship: false`, one onsite in another city, one with `clearance: "us_person"`, and one Acme job with pay.

Tests, `tests/test_match.py` (no DB; monkeypatch `_taxonomy.name_of` until `skills.json` lands):
| Case | Expect |
|---|---|
| all strong | 100.0 |
| must strong, must partial, nice none | 100 × (2 + 1 + 0) / 5 = 60.0 |
| score 70.0, no flags | `match` |
| score 60.0, every gap closable | `stretch` |
| score 60.0, a must-have none | `hidden` |
| score 50.0, closable | `stretch`; 49.9 is `hidden` |
| score 100, sponsorship flag | `review` |
| `job.sponsorship` None, F-1 candidate | no flag |
| each flag on and off | as specified |
| `never` | `excluded` |
| `only_strong_offer`, pay None | `review` + note |
| `only_strong_offer`, pay "35-45 USD/hour", min 30 | unchanged |
| same pay, min 40 | `review` (lower bound 35) |
| `only_strong_offer` on a `hidden` job | stays `hidden` |
| `parse_hourly("120,000 USD/year")` | about 57.7 |
| shuffled rows | sorted by route, score, eager, paid |
| any gap text | never contains "lack"; strong reqs give no gap |
| empty requirements | `RuntimeError` naming the job id |

Laptop check:
```sh
python -c "import sys,json; sys.path.insert(0,'tools'); import _match; j=json.load(open('tests/fixtures/jobs.json',encoding='utf-8'))[0]; p=json.load(open('tests/fixtures/profile.json',encoding='utf-8')); print(json.dumps(_match.evaluate(j,p), indent=2))"
```

---

## 6. Seed data (D, 60 to 75 min)

### 6.1 `tools/_profile.py`
`validate(profile, source) -> None` raises `ValueError("<source>: <field> <problem>")`. It checks:
- every 6.2 key is present
- `remote` and `stance` enums
- levels are 1 to 3
- each `skill_id` is a known id
- bullet ids are unique
- evidence `source` is `resume` or `chat`
- every skill has at least one evidence line

`seed_db` uses it now; `ingest_profile` and `update_profile` use it later. This is the structural
validation layer from AGENTS.md, written once.

### 6.2 Candidate files
- `data/candidates/c001.json` and `c002.json` are the hand-written demo heroes. `gen_candidates.py` writes
  `c003` to `c030` and never touches `c001` or `c002`.
- Deterministic: `random.Random(2026)`, `json.dumps(..., indent=2, sort_keys=True)`. A rerun gives no git diff.
- Required spread (asserted in tests):
  - programs: CS, ME, EE, data science, mechatronics
  - at least 10 F-1 needing sponsorship; at least 5 US persons
  - at least 8 with a skill that has only chat evidence (needed for the paid context-matching demo)
  - at least 6 with `company_prefs`; Acme appears with each stance at least once
  - against the demo role (jobs.json entry 0): at least 5 strong, at least 3 one level short (stretch
    material), at least 2 F-1 candidates who are strong for the `sponsorship: false` job (review material)
  - at least 80% of `skills.json` used by someone
- Evidence is templated and verbatim. A resume line (`"Built a ... with MySQL for ..."`) is also stored in
  `bullets`; a chat line looks like `"I've also used Docker at ..."`.
- CLI: `python scripts/gen_candidates.py [--seed 2026]` prints `{"written": 28, "dir": "..."}`.

### 6.3 `seed_db.py --reset [--with-test-jobs]`
- `--reset` deletes `DB_PATH` first.
- Loads `data/candidates/*.json`, runs `_profile.validate` on each, then `INSERT OR REPLACE` with `synthetic = 1`.
- `--with-test-jobs` loads `tests/fixtures/jobs.json` as `source = "test"` with `requirements_json` already
  filled, so matching is testable before B's fetch and extract exist. `demo_reset.sh` never passes it.
- It does not load snapshots. `fetch_jobs --offline` does that (`demo_reset.sh` already calls it). Fix the docstring.
- Prints `{"db", "candidates": 30, "jobs": n}`.

### 6.4 `data/requests/*.txt`
Three vague manager requests, one paragraph each: a mobile app for an ops team (the demo), a mechatronics
test rig, and a data dashboard.

Tests, `tests/test_seed.py`:
| Case | Expect |
|---|---|
| run gen twice into tmp | byte-identical files |
| all 30 files | pass `_profile.validate`; ids `c001` to `c030` unique |
| `c001`, `c002` hash before and after gen | unchanged |
| the spread in 6.2 | holds |
| `seed_db --reset` | 30 candidate rows; rerun still 30 |
| `profile_json` from the DB | equals the file contents |
| bad file in tmp (level 4) | `ValueError` naming the file and the field |

Integration test, the proof that the demo story works with this data: seed with test jobs, then
`_match.evaluate` every candidate against jobs.json entry 0.
- at least 1 `match`, 1 `stretch`, and 1 `review` with a `sponsorship` flag (on the no-sponsorship job)
- at least one candidate is `match` with all evidence but drops a route when chat-only evidence is removed

Laptop check:
```sh
python scripts/gen_candidates.py
python scripts/seed_db.py --reset --with-test-jobs
python -c "import sqlite3; c=sqlite3.connect('app.db'); print(c.execute('select count(*) from candidates').fetchone()[0], c.execute('select count(*) from jobs').fetchone()[0])"
PY=python bash tests/smoke.sh          # Git Bash; the seed_db line turns OK
```

---

## 7. Order

| Step | Owner | Needs | Done when |
|---|---|---|---|
| 1. Test setup + `aux_math` | A | nothing | `python -m pytest -q` runs |
| 2. `_db` | D | 1 | `test_db` green, laptop check prints 5 tables |
| 3. `skills.json` + `_taxonomy` | D | 1 | `test_taxonomy` green |
| 4. `_llm` | C | 1 | `test_llm` green, `python tools/_llm.py` ok through the tunnel, live test green |
| 5. `_match` + fixtures | B | 1 (stub `name_of` until 3) | `test_match` green |
| 6. `_profile`, gen, seed, requests | D | 2, 3 | `test_seed` green including the integration test |

Steps 2 to 5 run in parallel. Merge order into `main`: 1, then 2 and 3, then 4 and 5, then 6.

Definition of done for the whole set:
- `python -m pytest -q` is all green
- `python tools/_llm.py` returns `"ok": true` through the tunnel, and `pytest -m live` is green
- `smoke.sh` shows `seed_db OK`
- merged to `main`

---

## 8. Contract changes to copy into MASTER_CONTEXT

1. `_db.next_id(conn, table, prefix)` is the only way ids are made (`c###`, `r###`).
2. `evaluate(job, profile)`: `job` gains `id`; the result gains `eager`. New helpers `top_evidence` and `parse_hourly`.
3. `closable` is False for strong requirements. Prefs only demote, never promote `hidden`.
4. `only_strong_offer` compares the lower bound of the pay range to `min_pay` (pending Q5).
5. `never` excludes the candidate from that company's employer shortlist too.
6. `tools/_profile.py` validates 6.2 profiles; `tools/aux_math.py` handles float comparisons.
7. `seed_db` loads candidates only (plus test jobs with `--with-test-jobs`); snapshots are loaded by `fetch_jobs --offline`.
8. `c001` and `c002` are hand-written heroes; `gen_candidates` owns `c003` to `c030`.
9. `_llm` callers check `"error"` first and validate model keys themselves.
