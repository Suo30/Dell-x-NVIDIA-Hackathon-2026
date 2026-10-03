# Handoff: build the shared modules and seed data

Paste this whole file as the first message of a new Claude Code chat, or tell the chat to read it.
It is self-contained. Do not assume any other conversation.

## 0. Your task

Implement and test four shared modules plus seed data in this repo, all runnable on a Windows laptop
with no GPU box, no Slack and no agent:

1. `tools/_db.py`
2. `tools/_taxonomy.py` and `data/skills.json`
3. `tools/_llm.py`
4. `tools/_match.py`
5. Seed data: `tools/_profile.py`, `scripts/gen_candidates.py`, `scripts/seed_db.py`, `data/candidates/*.json`, `data/requests/*.txt`

Plus a test harness (`tests/conftest.py`, `pytest.ini`, `tools/aux_math.py`) and fixtures.

Work in this order and commit after each step (small commits, branch `a-platform` or a new branch; do not push
unless asked). Never commit `.env`, tokens or `*.db`.

Before writing code, read: `AGENTS.md` (coding rules, binding), `MASTER_CONTEXT.md` sections 4, 6, 7, 8, 9, and the
stub docstrings in `tools/_db.py`, `_taxonomy.py`, `_llm.py`, `_match.py`.

## 1. Project in one paragraph

A two-sided career matching agent (OpenClaw on a Dell GB10 box, local Qwen model, Slack). Students get matched to job
postings; hiring managers get a drafted JD plus a shortlist of candidates. Everything is stdlib Python CLIs in `tools/`
that print one JSON object and exit 0 (`tools/_cli.py` already does this). The model only extracts text into JSON;
code decides scores, routes and flags. Both sides map to one skills taxonomy (`data/skills.json`).
All current tools in `tools/` are stubs returning `{"error": "not implemented: ..."}`; only `_config.py` and `_cli.py` work.

## 2. Environment and rules

- Windows 11, Git Bash and PowerShell, Python 3.10+. Core code is **stdlib only** (no requests, pydantic, numpy).
  Dev-only: pytest and ruff via `pip install -r requirements-dev.txt`.
- `python tools/x.py` puts `tools/` on `sys.path`, so modules import each other as `import _config`.
- Read settings at call time: write `_config.DB_PATH`, never `from _config import DB_PATH`. Tests monkeypatch `_config`.
- Every `open`, `read_text`, `write_text` passes `encoding="utf-8"`.
- Close sqlite connections when done (Windows cannot delete an open DB file).
- AGENTS.md rules that bite here:
  - Comments short, descriptive, minimal.
  - Fail fast: `ValueError` for bad user data, `RuntimeError` for broken internal contracts or team data; message names the file, id or field.
  - No `except Exception: pass`, no silent `continue`.
  - No `.get(key, fallback)`, `getattr(..., None)`, `hasattr` on the team's own dicts/rows. Allowed only at a real boundary (model output, external JSON, optional config) with a comment naming the boundary.
  - Float and datetime comparisons go through `tools/aux_math.py` (create it, see 3.1).
- No em dashes anywhere in the repo's prose or code.
- The model output is an external boundary: `_llm.chat_json` never raises for model trouble, it returns `{"error": ...}`.

## 3. Step 1: test harness (do first)

### 3.1 Files

`tools/aux_math.py`
```python
"""Float comparison helpers. Use these instead of ==, <, >= on floats."""
EPS = 1e-6

def eq(a, b): return abs(a - b) <= EPS
def ge(a, b): return a > b or eq(a, b)
def lt(a, b): return not ge(a, b)
```

`pytest.ini`
```ini
[pytest]
testpaths = tests
addopts = -m "not live"
markers =
    live: needs the real model through the SSH tunnel (set LLM_LIVE=1)
```

`tests/conftest.py`
```python
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "scripts")]

import _config  # noqa: E402


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(_config, "DB_PATH", tmp_path / "t.db")
    return _config.DB_PATH


@pytest.fixture
def mock_llm(monkeypatch):
    monkeypatch.setattr(_config, "MOCK", True)
```

Check: `python -m pytest -q` runs (0 tests collected is fine). Commit.

## 4. Step 2: `_db`

Implement in `tools/_db.py` (keep the existing module docstring, extend with `next_id`):

```python
import sqlite3
from datetime import datetime, timezone

import _config

_ID_TABLES = {"candidates", "roles"}


def connect():
    path = _config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.executescript(_config.SCHEMA_PATH.read_text(encoding="utf-8"))
    return conn


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def next_id(conn, table, prefix):
    if table not in _ID_TABLES:
        raise RuntimeError(f"next_id: table {table!r} is not one of {sorted(_ID_TABLES)}")
    top = 0
    for (rid,) in conn.execute(f"SELECT id FROM {table} WHERE id LIKE ?", (prefix + "%",)):
        top = max(top, int(rid[len(prefix):]))
    return f"{prefix}{top + 1:03d}"
```
(A non-numeric suffix raises `ValueError` from `int`; that is a corrupt id, let it fail loudly.)

`tests/test_db.py`, all using `tmp_db`:
| Case | Expect |
|---|---|
| `connect()` on a path in a missing dir | file exists; tables are exactly `applications, candidates, jobs, matches, roles` |
| `connect()` twice with an insert between | no error; row still present |
| `now()` | `datetime.fromisoformat` parses it; `tzinfo` is UTC |
| `next_id(conn, "candidates", "c")` on empty | `c001` |
| after inserting ids `c001`, `c007` | `c008` |
| `next_id(conn, "roles", "r")` after candidates exist | `r001` |
| `next_id(conn, "jobs", "j")` | `RuntimeError` |

Always `conn.close()` in tests (use a `try/finally` or a yield fixture).

Laptop check (Git Bash):
```sh
DB_PATH=work/try.db python -c "import sys; sys.path.insert(0,'tools'); import _db; c=_db.connect(); print([r[0] for r in c.execute(\"select name from sqlite_master where type='table' order by 1\")])"
```
Expect `['applications', 'candidates', 'jobs', 'matches', 'roles']`. Commit.

## 5. Step 3: `skills.json` and `_taxonomy`

### 5.1 `data/skills.json`

Format (MASTER_CONTEXT 6.1): `[{"id": "mysql", "name": "MySQL", "category": "database", "aliases": ["my sql", "mariadb"]}]`.

Rules:
- 40 to 60 entries.
- `category` is one of: `backend`, `frontend`, `mobile`, `data`, `cloud-devops`, `mechanical`, `soft`. Use every category at least once. (MySQL goes under `data`, not `database`; the example in 6.1 predates this enum, update 6.1 to match.)
- `id` matches `^[a-z0-9-]+$` (`react-native`, `cpp`, `csharp`, `nodejs`, `dotnet`, `ci-cd`).
- `aliases` lowercase, no alias equal to any other skill's id, name or alias after normalizing (3.2).
- Punctuated names need explicit aliases: C++ (`c plus plus`), C# (`c sharp`), Node.js (`node`, `node.js`), .NET (`dotnet`), CI/CD (`ci cd`, `continuous integration`).
- Must cover the SKILLS line of `tests/fixtures/resume.txt` (Python, MySQL, SolidWorks, MATLAB, React Native, Git), plus Docker, and the mobile-app and MySQL needs in `tests/fixtures/conversation.txt`.
- Suggested spread: backend (python, java, nodejs, cpp, csharp, rest-api, sql...), frontend (react, javascript, typescript, html-css...), mobile (react-native, swift, kotlin, flutter), data (mysql, postgresql, pandas, machine-learning, data-visualization...), cloud-devops (docker, kubernetes, aws, git, ci-cd, linux), mechanical (solidworks, matlab, cad, fea, 3d-printing, plc, ros, embedded-c, circuit-design...), soft (communication, leadership, project-management, teamwork).

### 5.2 `tools/_taxonomy.py`

```python
import functools
import json
import re

import _config

CATEGORIES = {"backend", "frontend", "mobile", "data", "cloud-devops", "mechanical", "soft"}
_ID_RE = re.compile(r"^[a-z0-9-]+$")


def _norm(s):
    return " ".join(s.lower().replace("-", " ").replace("_", " ").split())


@functools.lru_cache(maxsize=1)
def _index():
    path = _config.DATA_DIR / "skills.json"
    skills = json.loads(path.read_text(encoding="utf-8"))
    by_key, by_id = {}, {}
    for s in skills:
        for field in ("id", "name", "category", "aliases"):
            if field not in s:
                raise RuntimeError(f"{path}: skill {s!r} missing {field!r}")
        if not _ID_RE.match(s["id"]):
            raise RuntimeError(f"{path}: id {s['id']!r} must match {_ID_RE.pattern}")
        if s["category"] not in CATEGORIES:
            raise RuntimeError(f"{path}: {s['id']} has unknown category {s['category']!r}")
        if s["id"] in by_id:
            raise RuntimeError(f"{path}: duplicate id {s['id']!r}")
        by_id[s["id"]] = s
        for key in {_norm(s["id"]), _norm(s["name"]), *(_norm(a) for a in s["aliases"])}:
            if key in by_key and by_key[key] != s["id"]:
                raise RuntimeError(f"{path}: key {key!r} used by both {by_key[key]} and {s['id']}")
            by_key[key] = s["id"]
    return skills, by_key, by_id
```
Then:
- `load()` returns `_index()[0]`.
- `resolve(name)` returns `_index()[1].get(_norm(name))` (`None` is a valid answer: the model named a skill we do not track; comment that this is the model boundary).
- `name_of(skill_id)` returns `_index()[2][skill_id]["name"]`; wrap `KeyError` into `RuntimeError(f"unknown skill id {skill_id!r}")`.
- `prompt_block()`: one line per skill grouped by category: `mysql: MySQL (my sql, mariadb)`; omit the parentheses when there are no aliases.
- Tests clear the cache with `_taxonomy._index.cache_clear()`.
- `_norm` does not strip other punctuation, so `c++`, `c#` and `c` stay distinct.

`tests/test_taxonomy.py`:
| Case | Expect |
|---|---|
| real file | 40 to 60 entries, every category in `CATEGORIES` used |
| `resolve("MySQL")`, `"  mysql "`, `"MariaDB"` | `mysql` |
| `resolve("React-Native")`, `"react_native"`, `"React Native"` | `react-native` |
| `resolve("C++")` and `resolve("C#")` | two different non-None ids |
| `resolve("Cobol for goats")` | `None` |
| every comma-separated item in the SKILLS line of `tests/fixtures/resume.txt`, plus `Docker` | resolves |
| `name_of(id)` for every id | returns its `name` |
| `name_of("nope")` | `RuntimeError` |
| `prompt_block()` | `len(load())` lines, each id appears, total under 4000 chars |
| tmp `DATA_DIR` with two skills sharing alias `js`, cache cleared | `RuntimeError` naming both ids |
| tmp file with category `"database"` | `RuntimeError` |

Laptop check:
```sh
python -c "import sys; sys.path.insert(0,'tools'); import _taxonomy as t; print(len(t.load())); print([t.resolve(x) for x in ['MySQL','mariadb','React Native','Node.js','C++','nonsense']])"
python -c "import sys; sys.path.insert(0,'tools'); import _taxonomy as t; print(t.prompt_block())"
```
Commit.

## 6. Step 4: `_llm`

Public API unchanged: `chat_json(system, user, *, mock, max_tokens=2048) -> dict`.

Structure:
```python
import copy, json, re, time, urllib.request, urllib.error
import _config

TIMEOUT = 180

def _post(messages, max_tokens):
    body = {"model": _config.LLM_MODEL, "messages": messages, "temperature": 0,
            "max_tokens": max_tokens, "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request(_config.LLM_BASE_URL + "/chat/completions",
        data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    choice = data["choices"][0]  # external boundary: vLLM response
    return choice["message"]["content"], choice["finish_reason"]

def _extract(text):
    text = text.rsplit("</think>", 1)[-1]
    text = re.sub(r"```(?:json)?", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError(f"no JSON object in model output: {text[:200]!r}")
    obj = json.loads(text[start:end + 1])
    if not isinstance(obj, dict):
        raise ValueError("model output is not a JSON object")
    return obj
```

`chat_json` flow:
1. `_config.MOCK`: return `copy.deepcopy(mock)`.
2. `_post`; on `urllib.error.URLError`, `OSError` (includes timeouts, `HTTPError` is a subclass of `URLError`) return `{"error": f"model unreachable at {url}: {reason}"}`.
3. `finish_reason == "length"`: `{"error": f"model output truncated at max_tokens={n}"}`, no retry.
4. `_extract` raises `ValueError` or `json.JSONDecodeError`: retry once with messages extended by the bad reply as an assistant turn and a user turn `"Your last reply was not valid JSON. Return only the JSON object."`.
5. Still failing: `{"error": f"invalid JSON after retry: {content[:200]}"}`.

Self-check: add a `__main__` block, wrapped in `_cli.run`, that sends one small extraction (the resume.txt SKILLS line plus `_taxonomy.prompt_block()` in the system prompt; ask for `{"skills": [{"skill_id", "level"}]}`) and returns `{"ok": bool, "seconds", "base_url", "model", "result"}`. With `MOCK_LLM=1` it should return `ok: true` with the mock. Callers' mock dict shape is theirs; here use `{"skills": []}`.

Caller rule (document in the module docstring): callers check `"error" in out` first and pass it through, then validate the keys they need and return `{"error": "model output missing <key>"}`.

Optional, decide after a curl test through the tunnel: if vLLM accepts `"response_format": {"type": "json_object"}` (HTTP 200) add it to `_post`; if 400, leave it out.

### Tests, `tests/test_llm.py` (no network)

`_extract` cases:
| Input | Expect |
|---|---|
| `{"a": 1}` | `{"a": 1}` |
| fenced with ```json | dict |
| `<think>reasoning with {braces}</think>{"a":1}` | `{"a": 1}` |
| prose before and after the object | dict |
| nested braces `{"a":{"b":2}}` | dict |
| `[1, 2]`, `""`, `{bad` | raises (`ValueError` or `JSONDecodeError`, which subclasses it) |

Fake server fixture (put in the test file):
```python
import json, threading
from http.server import BaseHTTPRequestHandler, HTTPServer

@pytest.fixture
def fake_llm(monkeypatch):
    state = {"replies": [], "requests": []}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers["Content-Length"])
            state["requests"].append(json.loads(self.rfile.read(n)))
            status, content, finish = state["replies"].pop(0)
            payload = json.dumps({"choices": [{"message": {"content": content}, "finish_reason": finish}]}).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        def log_message(self, *a): pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(_config, "LLM_BASE_URL", f"http://127.0.0.1:{srv.server_port}/v1")
    monkeypatch.setattr(_config, "MOCK", False)
    yield state
    srv.shutdown()
    srv.server_close()
```
Replies are `(status, content, finish_reason)` tuples.

| Script | Expect |
|---|---|
| `[(200, '{"a":1}', "stop")]` | `{"a": 1}`; 1 request; body has `model`, `temperature == 0`, `chat_template_kwargs.enable_thinking is False` |
| bad then good | dict; 2 requests; second request's last message contains `valid JSON` |
| bad, bad | has `error`; exactly 2 requests |
| `[(500, "boom", "stop")]` | `error`, no exception |
| `[(200, '{"a":', "length")]` | `error` containing `max_tokens`; 1 request |
| `LLM_BASE_URL` at a closed port (bind a socket, read its port, close it) | `error` |
| MOCK True, then mutate the returned dict | original `mock` unchanged |

### Live check (needs the box; run from laptop)
```sh
# terminal 1, leave open
ssh -L 8000:127.0.0.1:8000 dell@172.20.65.171
# terminal 2
curl -s http://127.0.0.1:8000/v1/models
python tools/_llm.py                      # expect "ok": true, note "seconds"
LLM_LIVE=1 python -m pytest -m live -q    # PowerShell: $env:LLM_LIVE="1"; python -m pytest -m live -q
```
`tests/test_llm_live.py`: `@pytest.mark.live`, skip unless `os.environ.get("LLM_LIVE") == "1"`, calls `chat_json` with the real model on
`tests/fixtures/resume.txt` and `_taxonomy.prompt_block()`; asserts a dict with a `skills` list and that every `skill_id` resolves via `_taxonomy.resolve`.
If the tunnel is not up, report that you could not run the live check; do not claim it passed.
Commit.

## 7. Step 5: `_match`

Pure code, no model. Read MASTER_CONTEXT section 7 first; this section adds decisions.

### 7.1 Contract

- `evaluate(job, profile) -> {"score": float, "route": str, "eager": bool, "detail": dict}`
  - `job`: `{"id", "requirements": [...], "sponsorship": bool|None, "clearance": "none"|"us_person"|"clearance"|None, "location": str|None, "company": str|None, "pay": str|None, "paid": int}`. Requirement shape is 6.4: `{"skill_id", "level", "importance": "must"|"nice", "why"?, "evidence_text"?}`.
  - `profile`: 6.2.
  - `detail`: 6.5: `{"requirements": [{"skill_id", "importance", "required", "candidate_level", "match", "evidence", "closable"}], "flags": [...], "pref_note": str|None, "gaps_text": [...]}`.
  - Route is one of `match | stretch | review | hidden | excluded`.
- Helpers: `score(reqs)`, `flags(job, profile)`, `route(score, reqs, flag_list)`, `apply_prefs(route, job, profile) -> (route, pref_note|None, eager)`, `sort_key(row)`, `gap_text(skill_name, required, candidate_level)`, plus new `top_evidence(detail, n=2) -> list[str]` and `parse_hourly(pay) -> float|None`.

Note: the stub docstring says `apply_prefs -> (route, pref_note|None)`. Change it to also return `eager`, update the docstring, and tell the user this contract change.

### 7.2 Rules

- Per requirement: `candidate_level` = the profile skill's level or 0 if absent. `match` is `strong` if `candidate_level >= required`, `partial` if `candidate_level == required - 1`, else `none`. `evidence` is the first evidence `text` of that profile skill, else `None`. `closable`: partial True; none+nice True; none+must False; strong False.
- Profile skills are our own data: index by `skill_id` with direct access, no `.get` fallback. Absence is checked with `in`.
- `score`: `100 * sum(w * credit) / sum(w)`, must=2, nice=1, strong=1, partial=0.5, none=0, `round(..., 1)`. Empty requirements raise `RuntimeError(f"job {id} has no requirements; match only extracted jobs")`.
- `flags` in fixed order `sponsorship, clearance, location`:
  - `sponsorship`: profile `visa.needs_sponsorship` and `job["sponsorship"] is False`. `None` never flags.
  - `clearance`: job clearance is `us_person` or `clearance` and `visa.us_person` is False.
  - `location`: job location is non-empty; lowercase text contains neither `remote` nor `hybrid`; no preferred city (text before the first comma, lowercased) is a substring of it; and `location.remote != "any"`.
- `route`: flags non-empty gives `review`; else `ge(score, 70)` `match`; else `ge(score, 50)` and every non-strong requirement `closable` gives `stretch`; else `hidden`. Use `aux_math`.
- `apply_prefs`: find the profile's `company_prefs` entry whose company matches `job["company"]` case-insensitively.
  - `never`: return `excluded`.
  - `only_strong_offer`: if route is `match` or `stretch`, keep it only when `parse_hourly(pay)` is not None and `ge(pay, min_pay)`; otherwise `review` with note `"only_strong_offer: pay not stated"` or `"only_strong_offer: pay 35 below minimum 45"` (numbers formatted without trailing `.0`). `min_pay` null with this stance counts as satisfied when pay is known.
  - `eager`: `eager = True`.
  - Prefs only demote; `hidden` and `review` are left alone.
- `parse_hourly(pay)`: `re.findall(r"\d[\d,]*\.?\d*", pay)`, strip commas, take the first number (lower bound of a range, conservative; Q5 in MASTER_CONTEXT may change this). Over 1000 means annual: divide by 2080. No numbers returns `None`. `pay` None returns `None`.
- `sort_key(row)`: `(ROUTE_ORDER[row["route"]], -row["score"], not row["eager"], not row["paid"])`.
- `gap_text(name, required, candidate_level)`: `"The evidence did not show {name} at level {required} (has level {n})"`; level 0 gives `"... (no evidence found)"`. Never the word "lack". `detail.gaps_text` has one line per non-strong requirement, in requirement order, using `_taxonomy.name_of`.
- `top_evidence(detail, n)`: evidence strings of strong must requirements, then strong nice, skipping `None`, first `n`.
- Employer side relies on `excluded` to drop candidates who set `never` for the company.

### 7.3 Fixtures to create

`tests/fixtures/profile.json`: Jordan Rivera from `resume.txt` in 6.2 shape (F-1, needs_sponsorship true, us_person false, preferred Boston, remote `hybrid`, start 2027-01 co-op, skills python 2, mysql 2 (the pipeline bullet), solidworks 3, matlab 2, react-native 1, git 2, each with verbatim evidence from the resume, bullets b1..b3, no company_prefs).

`tests/fixtures/jobs.json`: list of 6 to 8 jobs, each with `id, source: "test", company, title, url` plus the evaluate input fields:
- 0: the demo role from `conversation.txt`: Acme, "Full-Stack Mobile Engineer (Co-op)", Boston hybrid, sponsorship true, requirements react-native 2 must, mysql 2 must, python 1 nice, git 1 nice, pay `35-45 USD/hour`, paid 0.
- 1: same skills but `sponsorship: false`.
- 2: onsite `Austin, TX`.
- 3: `clearance: "us_person"`.
- 4: a mostly mechanical role (solidworks, matlab) that Jordan matches strongly.
- 5: a role needing skills Jordan lacks entirely (hidden).
- 6: a different company, paid 1.

### 7.4 Tests, `tests/test_match.py`

Monkeypatch `_taxonomy.name_of` to `lambda s: s.title()` until `skills.json` exists, or just use the real taxonomy if it is merged.

| Case | Expect |
|---|---|
| all strong | 100.0 |
| must strong, must partial, nice none | `100*(2+1+0)/5` = 60.0 |
| score 70.0, no flags | `match` |
| score 60.0, every gap closable | `stretch` |
| score 60.0, a must none | `hidden` |
| score 50.0 closable | `stretch`; score 49.9 | `hidden` |
| score 100 with a sponsorship flag | `review` |
| `job.sponsorship` None, F-1 candidate | no sponsorship flag |
| each flag on and off (6 cases) | as 7.2 |
| `never` | `excluded` |
| `only_strong_offer`, pay None | `review` + note |
| `only_strong_offer`, pay `35-45 USD/hour`, min 30 | unchanged |
| same pay, min 40 | `review` (lower bound 35) with the "below minimum" note |
| `only_strong_offer` on a `hidden` job | stays `hidden` |
| `eager` | `eager is True`, route unchanged |
| `parse_hourly("120,000 USD/year")` | about 57.69 |
| `parse_hourly("competitive")`, `None` | `None` |
| shuffled rows | sorted by route, score desc, eager, paid |
| every gap line | no "lack"; strong requirements produce none |
| empty requirements | `RuntimeError` containing the job id |
| fixture jobs 0..6 vs Jordan | job 0 is `match` or `stretch`; job 1 is `review` with `sponsorship`; job 2 has `location` flag if Jordan's remote isn't `any`; job 3 has `clearance`; job 5 is `hidden` |

Laptop check:
```sh
python -c "import sys,json; sys.path.insert(0,'tools'); import _match; j=json.load(open('tests/fixtures/jobs.json',encoding='utf-8'))[0]; p=json.load(open('tests/fixtures/profile.json',encoding='utf-8')); print(json.dumps(_match.evaluate(j,p), indent=2))"
```
Commit.

## 8. Step 6: seed data

### 8.1 `tools/_profile.py`

`validate(profile, source)` raises `ValueError(f"{source}: {field} {problem}")`. Checks: all 6.2 keys present; `visa` has `status, needs_sponsorship, us_person`; `location.remote` in `any|remote|hybrid|onsite`; `company_prefs[].stance` in `eager|neutral|only_strong_offer|never`; skill levels in 1..3; `skill_id` known to `_taxonomy`; bullet ids unique; evidence `source` in `resume|chat`; every skill has at least one evidence entry. This is the structural validation layer (AGENTS.md); `ingest_profile` and `update_profile` call it later.

### 8.2 Candidates

- `data/candidates/c001.json`, `c002.json`: hand-written heroes. c001 = Jordan Rivera from `profile.json`. c002 = a strong-by-chat candidate: modest resume but a skill (for example `mysql` level 2) that appears only with `source: "chat"` evidence, and a `company_prefs` entry for Acme with `only_strong_offer`, min_pay 45.
- `scripts/gen_candidates.py [--seed 2026]` writes `c003`..`c030`, never touches `c001` or `c002`. Deterministic: `random.Random(seed)`, `json.dumps(..., indent=2, sort_keys=True, ensure_ascii=False)` plus a trailing newline. Prints `{"written": 28, "dir": "..."}`.
- Names are synthetic and obviously fake; set `school` mostly Northeastern; programs spread across CS, mechanical, electrical, data science, mechatronics.
- Evidence is templated and verbatim: a resume line (`"Built a <thing> using <Skill> for <context>"`) also stored in `bullets` with the same text; a chat line like `"I've also used Docker at my last job"`.
- Required spread over all 30 (asserted in tests):
  - at least 10 F-1 with `needs_sponsorship` true, at least 5 `us_person` true
  - at least 8 with a skill that has only chat evidence
  - at least 6 with `company_prefs`; Acme appears at least once with each of `eager`, `neutral`, `only_strong_offer`, `never`
  - against `tests/fixtures/jobs.json[0]`: at least 5 `match`, at least 3 `stretch`; against `jobs.json[1]` (no sponsorship): at least 2 F-1 candidates with route `review` and the `sponsorship` flag
  - at least 80 percent of `skills.json` used by someone
- Generate so these hold by construction (assign archetypes), then let the tests prove it; adjust the generator, not the assertions.

### 8.3 `scripts/seed_db.py --reset [--with-test-jobs]`

- `--reset` deletes `DB_PATH` first.
- Loads `data/candidates/*.json`, runs `_profile.validate(profile, path.name)`, `INSERT OR REPLACE` into `candidates` with `synthetic=1`, `consent_auto=1`, `updated=_db.now()`.
- `--with-test-jobs` loads `tests/fixtures/jobs.json` into `jobs` with `source="test"`, `requirements_json` filled, `first_seen=_db.now()`. `demo_reset.sh` must not pass it.
- Does not load snapshots (that is `fetch_jobs --offline`'s job; fix the stale docstring).
- Returns `{"db": str(path), "candidates": n, "jobs": m}`. Wrapped in `_cli.run` already.

### 8.4 `data/requests/*.txt`

Three one-paragraph vague manager requests: `ops-app.txt` ("I need someone to build an app for our ops team."), `test-rig.txt` (mechatronics test rig), `dashboard.txt` (data dashboard). Plain text, no company-secret flavor.

### 8.5 Tests, `tests/test_seed.py`

| Case | Expect |
|---|---|
| run gen twice into a tmp dir (add `--out` to the CLI for this, default `data/candidates`) | byte-identical files |
| all 30 files | pass `_profile.validate`; ids `c001`..`c030` unique and match filenames |
| `c001`, `c002` content hash before and after gen | unchanged |
| the spread in 8.2 | all hold |
| `seed_db --reset` into `tmp_db` | 30 candidate rows; second run still 30 |
| `profile_json` in the DB | `json.loads` equals the file |
| tmp candidate file with a level of 4 | `ValueError` naming the file and the field |
| integration: seed with test jobs, evaluate all 30 against `jobs[0]` and `jobs[1]` | at least 1 `match`, 1 `stretch`, at least 1 `review` with a `sponsorship` flag |
| integration: for c002, drop `source == "chat"` evidence (copy the profile) and re-evaluate | score strictly lower than with it |

Laptop check:
```sh
python scripts/gen_candidates.py
python scripts/seed_db.py --reset --with-test-jobs
python -c "import sqlite3; c=sqlite3.connect('app.db'); print(c.execute('select count(*) from candidates').fetchone()[0], c.execute('select count(*) from jobs').fetchone()[0])"
PY=python bash tests/smoke.sh
```
Expect `30 7` (or your fixture job count) and `seed_db` showing `OK` in smoke (other tools still `ERR`, that is fine). Commit.

## 9. Contract changes to report back

After finishing, list these for the user to copy into MASTER_CONTEXT by PR (do not silently edit section 6 to 9 of that file):

1. `_db.next_id(conn, table, prefix)` is the only way ids are made.
2. `skills.json` categories are the 7-value enum in 5.1; 6.1's `database` example is outdated.
3. `evaluate` input job gains `id`; result gains `eager`; `apply_prefs` returns `(route, note, eager)`; new helpers `top_evidence`, `parse_hourly`.
4. `closable` is False for strong requirements; prefs only demote.
5. `only_strong_offer` compares the lower bound of the pay range to `min_pay` (pending Q5).
6. `never` excludes the candidate from that company's employer shortlist too.
7. New modules `tools/_profile.py`, `tools/aux_math.py`.
8. `seed_db` loads candidates and optional test jobs only; snapshots belong to `fetch_jobs --offline`.
9. `c001` and `c002` are hand-written; `gen_candidates` owns `c003`..`c030`.
10. `_llm` callers check `"error"` first and validate model keys themselves.

## 10. Definition of done

- `python -m pytest -q` all green (live tests excluded by default).
- `bash tests/smoke.sh` (with `PY=python` on Windows) shows `seed_db OK`, `FAIL count: 0`.
- `python scripts/check_skills.py` still passes.
- Live: `python tools/_llm.py` returned `"ok": true` through the tunnel and `LLM_LIVE=1 python -m pytest -m live` passed, or the report states plainly that the tunnel was unavailable and the live check was not run.
- Final report lists: files created, tests run with counts, anything skipped, and the section 9 contract changes.
