# MASTER CONTEXT: Two-sided career matching agent (Dell x NVIDIA Hackathon, Boston, Oct 3 2026)

Source of truth for the team. If something here conflicts with chat or memory, this file wins until someone edits it in a PR.

Status at writing: 13:00. Feature freeze 16:00. Code stop and submission 18:00.

---

## 0. Still to confirm (answer in the team chat, then edit this file)

| # | Question | Blocks |
|---|---|---|
| Q1 | Names for Persons B, C, D (section 5) | Nothing, cosmetic |
| Q2 | "30" means 30 candidate profiles, plus about 3 employer requests for the demo? | D's data work |
| Q3 | Workspace path inside the sandbox (where the repo must live on the box) | A, then everyone's deploy |
| Q4 | Who merges PRs into `main` (one person only) | Branch workflow |
| Q5 | Stretch threshold and "closable gap" rule in section 7.4 are proposals. Accept or change | B and C scoring |
| Q6 | Glassdoor dropped (not an ATS, no public jobs API). OK? | B's fetchers |

---

## 1. Rules that constrain the build

- Required stack: NemoClaw + OpenClaw + OpenShell. One agent, built today.
- All inference local on the GB10 box. Model: `nvidia/Qwen3.6-35B-A3B-NVFP4`, OpenAI-compatible API at `http://127.0.0.1:8000/v1` on the box host.
- The agent must talk through a real channel via the OpenClaw connector. **Decision: Slack.** No custom web frontend. Slack already gives chat and file upload, and a frontend would not satisfy the channel requirement.
- The agent must reason and call tools on its own, on a real business workflow.
- Never paste secrets (Slack tokens, NGC key) into chat or commit them. `.env` is gitignored.

---

## 2. The product

**Customer:** a university career / co-op office, which serves two kinds of users through one agent.

**Candidate side (B2C).** A student gives the agent a resume (upload or pasted text) plus anything else in conversation: skills not on the resume, location, remote, sponsorship needs, start date, and company-specific stances ("I'd only go to X for a really strong offer"). The agent pulls real postings from ATS APIs, maps each posting's requirements to a shared skills taxonomy, scores the fit against the student's full profile, flags eligibility issues, and returns matches. A match is a score of 70 or more, or a lower score whose gaps can be closed. Students consent to automatic matching and application.

**Employer side (B2B), the Role Architect.** A hiring manager sends a vague request ("I need someone to build an app"). The agent asks clarifying questions, then writes one structured JD with two layers:
- **Public JD:** title, description, location, sponsorship, clearance, pay (optional). Anyone can apply to it, including people who don't use the app.
- **Private context:** taxonomy-mapped requirements with levels and must/nice importance, plus seniority, team context and timeline. This layer is used only for matching against app users.

The manager approves the JD. The agent then returns a shortlist of candidates with evidence and gaps, and a human reviews it. No resume is needed for this matching, because both sides are matched on full context, not on one page.

**The two sides are one connected story.** An approved role becomes a job that candidates see in their matches, and the matcher compares the role's private context against each candidate's full profile.

**Paid employers:** a `paid` flag on the company, used only as a tie-breaker in sorting. It is not a demo feature and should not lead the pitch.

**Auto-apply in the MVP** means creating an application record inside the app (visible to the employer side). It never submits anything to an external ATS. All candidates are synthetic.

---

## 3. Architecture

```
Slack (#hiring, #students)
        |
   OpenClaw agent (one agent, in NemoClaw sandbox)
        |-- skill: role-architect   (employer flows)
        |-- skill: career-matcher   (candidate flows)
        |
   tools/*.py  (stdlib Python CLIs, JSON on stdout)
        |-- model calls: extraction only (text -> taxonomy-mapped JSON)
        |-- code: scoring, routing, flags, sorting
        |
   SQLite (one DB)          data/skills.json (shared taxonomy)
```

Principles:
1. The model extracts and writes text. Code decides scores, routes and flags.
2. Both sides map to the same `skills.json`. That's what makes context matching precise and checkable.
3. Every tool exits 0 and prints JSON. On failure it prints `{"error": "..."}`.
4. Gaps are worded as "evidence did not show X", never "candidate lacks X". No automatic rejection; humans review.

---

## 4. Repo layout

```
repo/
  MASTER_CONTEXT.md          this file
  README.md                  setup, run, demo steps (written 17:15)
  .env.example               LLM_BASE_URL, LLM_MODEL, DB_PATH, DATA_DIR, MOCK_LLM
  .gitignore                 .env, *.db, __pycache__, work/
  .gitattributes             forces LF on .sh/.py/.md so Windows checkouts run on the box
  db/schema.sql
  skills/
    role-architect/SKILL.md
    career-matcher/SKILL.md
  prompts/
    system.md                agent system prompt
  tools/
    _config.py               reads .env + env vars: REPO, DATA_DIR, DB_PATH, LLM_*, MOCK
    _cli.py                  run(main): catches everything, prints one JSON object, exits 0
    _llm.py                  chat_json(): calls model, strips <think> and fences, parses JSON, 1 retry
    _db.py                   connect(), init from schema.sql
    _taxonomy.py             load skills.json, alias -> skill_id
    _match.py                score(), route(), flags(), sort(). Pure code, no model
    ingest_profile.py        candidate
    update_profile.py        candidate
    fetch_jobs.py            candidate
    extract_reqs.py          candidate
    list_jobs.py             candidate
    match_jobs.py            candidate
    apply.py                 candidate
    draft_role.py            employer
    approve_role.py          employer
    show_role.py             employer
    match_candidates.py      employer
    tailor.py                stretch only
  data/
    skills.json
    companies.json           ATS sources: [{"company","source","slug"}]
    candidates/*.json        synthetic profiles
    requests/*.txt           demo employer requests
    snapshots/*.json         offline copies of fetched jobs
  scripts/
    gen_candidates.py        builds the 30 synthetic profiles
    seed_db.py               init DB, load candidates + snapshots
    demo_reset.sh            reset DB to demo start state
  tests/
    smoke.sh                 runs every tool once with MOCK_LLM=1
    fixtures/                resume.txt, conversation.txt used by smoke.sh
  work/                      gitignored scratch: resumes and conversations the agent writes at runtime
```

Tools import shared modules with `import _llm` and similar. This works because `python tools/x.py` puts `tools/` on the path. Standard library only.

Env vars:
- `LLM_BASE_URL`: `http://127.0.0.1:8000/v1` on the host and through a laptop tunnel. The sandbox value is the `inference.local` route (A confirms the exact URL).
- `LLM_MODEL`: `nvidia/Qwen3.6-35B-A3B-NVFP4`
- `DB_PATH`, `DATA_DIR`
- `MOCK_LLM=1`: returns canned JSON for offline dev and smoke tests

---

## 5. Team and ownership

| Person | Area | Owns |
|---|---|---|
| A (Iker) | Platform and agent | Slack connection, sandbox workspace path and network policy, both SKILL.md files, `prompts/system.md`, `_config.py`, `_cli.py`, `tests/smoke.sh`, deploying to the box, end-to-end runs in Slack, pitch lead |
| B | Candidate pipeline | `_match.py` (shared, first), `fetch_jobs`, `extract_reqs`, `list_jobs`, `match_jobs`, `apply`, `companies.json`, snapshots |
| C | Employer pipeline | `_llm.py` (shared, first), `draft_role`, `approve_role`, `show_role`, `match_candidates` |
| D | Data and profiles | `_db.py` + `schema.sql` (shared, first), `_taxonomy.py` + `skills.json` (shared, first), `ingest_profile`, `update_profile`, `gen_candidates`, `seed_db`, demo requests, `demo_reset.sh` |

OS: 2 Mac, 2 Windows. Everyone develops on their laptop against the box model through an SSH tunnel:

```
ssh -L 8000:127.0.0.1:8000 dell@172.20.65.171
```

This works the same in macOS Terminal and Windows PowerShell. After it connects, `LLM_BASE_URL=http://127.0.0.1:8000/v1` works on your laptop. Use `MOCK_LLM=1` when the box is busy.

Git: one branch per person (`a-platform`, `b-candidate`, `c-employer`, `d-data`). Small PRs, one merger (Q4). Shared modules merge first. Only A pulls `main` onto the box.

---

## 6. Data contracts (frozen at 13:40, change only by PR to this file)

### 6.1 Skills taxonomy: `data/skills.json`

```json
[{"id": "mysql", "name": "MySQL", "category": "database", "aliases": ["my sql", "mariadb"]}]
```

Levels, used everywhere:
- 1: used in a course or small project
- 2: used in a job, internship or substantial project
- 3: designed, led or owned something with it

Target size is 40 to 60 skills across backend, frontend, mobile, data, cloud/devops, mechanical/mechatronics and soft skills.

### 6.2 Candidate profile: `candidates.profile_json`

```json
{
  "id": "c001",
  "name": "Synthetic Name",
  "school": "Northeastern University",
  "program": "MS Mechanical Engineering",
  "visa": {"status": "F-1", "needs_sponsorship": true, "us_person": false},
  "availability": {"start": "2027-01", "type": "co-op"},
  "location": {"preferred": ["Boston, MA"], "remote": "any"},
  "skills": [
    {"skill_id": "python", "level": 2,
     "evidence": [{"source": "resume", "text": "verbatim line"}, {"source": "chat", "text": "what they said"}]}
  ],
  "bullets": [{"id": "b1", "text": "verbatim resume bullet"}],
  "company_prefs": [{"company": "Acme", "stance": "only_strong_offer", "min_pay": 45}],
  "notes": ["free-text facts from chat that don't map to a field"]
}
```

`remote` takes one of `any | remote | hybrid | onsite`. `stance` takes one of `eager | neutral | only_strong_offer | never`. `min_pay` is hourly USD, or null.

### 6.3 Role: `roles.public_json` and `roles.private_json`

```json
{
  "public": {
    "title": "Full-Stack Mobile Engineer (Co-op)",
    "description": "plain-language JD text",
    "location": "Boston, MA (hybrid)",
    "sponsorship": true,
    "clearance": "none",
    "pay": "35-45 USD/hour"
  },
  "private": {
    "requirements": [
      {"skill_id": "mysql", "level": 2, "importance": "must", "why": "owns the data layer"}
    ],
    "seniority": "co-op",
    "team_context": "2 engineers, no designer",
    "timeline": "start Jan 2027"
  }
}
```

`clearance` takes one of `none | us_person | clearance`. `pay` is optional and may be null.

### 6.4 Job requirements: `jobs.requirements_json`

This is the same shape as `private.requirements`, with an added `"evidence_text"` field holding the verbatim JD line. ATS jobs get it from `extract_reqs.py`. Internal jobs copy it from the role.

### 6.5 Match detail: `matches.detail_json`

```json
{
  "requirements": [
    {"skill_id": "mysql", "importance": "must", "required": 2, "candidate_level": 1,
     "match": "partial", "evidence": "verbatim candidate evidence or null", "closable": true}
  ],
  "flags": ["sponsorship"],
  "pref_note": "only_strong_offer: pay not stated",
  "gaps_text": ["The evidence did not show MySQL at level 2 (has level 1)"]
}
```

---

## 7. Logic (B owns `_match.py`. Everything here is pure code)

### 7.1 Per-requirement match
- **strong:** candidate level is at or above the required level
- **partial:** candidate level is exactly one below the required level
- **none:** skill absent, or two or more levels below

### 7.2 Score

Weights are must = 2 and nice = 1. Credit is strong = 1, partial = 0.5 and none = 0.

score = 100 × Σ(weight × credit) / Σ weight

### 7.3 Flags (kept separate from the score)
- `sponsorship`: the candidate needs sponsorship and the job says no
- `clearance`: the job requires `us_person` or `clearance` and the candidate is not a US person
- `location`: the job is onsite somewhere outside the preferred locations and the candidate's remote preference is not `any`

### 7.4 Routes (PROPOSAL, see Q5)
- **match:** score of 70 or more and no flags
- **stretch:** score from 50 to 69, with every gap closable. A gap is closable when it is partial, or when it is a nice-to-have marked none. A must-have marked none is never closable.
- **review:** any flag. Shown with the flag; a human decides.
- **hidden:** everything else. Never shown to employers as a "no".

### 7.5 Company preferences (candidate side)
- `never`: the job is excluded.
- `only_strong_offer`: shown only if the pay is known and at or above `min_pay`. Otherwise it routes to review with a `pref_note`.
- `eager`: sorted first within the same route.

### 7.6 Sort order
Route (match, then stretch, then review), then score descending, then `eager`, then `paid`.

---

## 8. Tool contracts

All tools take CLI args and print one JSON object to stdout.

**Candidate side**
```
ingest_profile.py --name "X" --text-file PATH [--notes "..."]
    -> {"candidate_id", "skills_found", "profile"}
update_profile.py --candidate ID --note "I'd only work at Acme for a great offer"
    -> {"candidate_id", "changes": [...]}
fetch_jobs.py [--source greenhouse|lever|workday|all] [--offline]
    -> {"new": [{"id", "company", "title", "url"}]}
extract_reqs.py [--pending] [--limit 20]
    -> {"processed": n, "failed": [...]}
list_jobs.py [--limit 10] [--source internal]
    -> {"jobs": [...]}
match_jobs.py --candidate ID [--limit 5]
    -> {"matches": [{"job_id", "company", "title", "url", "score", "route", "flags", "gaps_text", "top_evidence"}]}
apply.py --candidate ID --job ID
    -> {"application": {"job_id", "candidate_id", "status": "submitted"}}
```

**Employer side**
```
draft_role.py --company "X" --conversation-file PATH [--paid]
    -> {"role_id", "status": "draft", "public", "private"}
approve_role.py --role ID [--edits-file PATH]
    -> {"role_id", "job_id": "internal:ID", "status": "approved"}
show_role.py --role ID
    -> {"role_id", "public", "private", "status"}
match_candidates.py --role ID [--limit 10]
    -> {"shortlist": [{"candidate_id", "name", "score", "route", "flags", "gaps_text", "top_evidence"}]}
```

Clarifying questions live in the `role-architect` skill instructions, not in a tool. The agent asks up to 3 questions (seniority, location/remote, sponsorship, pay, timeline), writes the whole exchange to a file, then calls `draft_role.py`.

Job IDs follow the pattern `{source}:{company}:{native_id}`. Internal roles use `internal:{role_id}`.

---

## 9. Database: `db/schema.sql`

```sql
CREATE TABLE IF NOT EXISTS candidates (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, profile_json TEXT NOT NULL,
  consent_auto INTEGER NOT NULL DEFAULT 1, synthetic INTEGER NOT NULL DEFAULT 1,
  updated TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS roles (
  id TEXT PRIMARY KEY, company TEXT NOT NULL, paid INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL, public_json TEXT NOT NULL, private_json TEXT NOT NULL,
  created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, source TEXT NOT NULL, company TEXT, title TEXT, url TEXT,
  location TEXT, description TEXT, role_id TEXT, requirements_json TEXT,
  sponsorship INTEGER, clearance TEXT, pay TEXT, paid INTEGER NOT NULL DEFAULT 0,
  first_seen TEXT NOT NULL, notified INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS matches (
  job_id TEXT, candidate_id TEXT, score REAL, route TEXT, detail_json TEXT,
  created TEXT, PRIMARY KEY (job_id, candidate_id));
CREATE TABLE IF NOT EXISTS applications (
  job_id TEXT, candidate_id TEXT, status TEXT, created TEXT,
  PRIMARY KEY (job_id, candidate_id));
```

Use `INSERT OR IGNORE` for jobs. New jobs are detected by diffing IDs.

---

## 10. Job sources

| Source | Endpoint | Status |
|---|---|---|
| Greenhouse | `GET https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true` | MVP. Descriptions are HTML-escaped |
| Lever | `GET https://api.lever.co/v0/postings/{slug}?mode=json` | MVP |
| Workday | `POST {tenant}.wd{N}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs` | One tenant, only if Greenhouse and Lever work by 14:30. Copy the real request from DevTools |
| Glassdoor, LinkedIn, Indeed, Handshake | none | Out |

Cap extraction at about 10 jobs per company so model time stays bounded. Save every fetch to `data/snapshots/` for the offline demo.

---

## 11. Platform (A)

1. **Add Slack first, before copying anything into the sandbox.** Adding a channel rebuilds the sandbox, and it's unknown whether files survive. Slack needs a bot token and an app token (socket mode). If Slack isn't replying by 13:50, switch to Telegram and keep going.
2. Confirm the sandbox workspace path (Q3), whether `python3` exists in the sandbox, and the `inference.local` URL.
3. Network allowlist: `boards-api.greenhouse.io`, `api.lever.co`, the chosen Workday host, plus whatever Slack needs. Watch blocked requests in `openshell term`.
4. Test whether a Slack file upload reaches the agent as a readable file. If not, the MVP uses pasted resume text, and that's fine for the demo.
5. Slack channels: `#hiring` (employer persona) and `#students` (candidate persona). Both skill descriptions say which channel and phrasing they handle. Check whether the agent can see the channel name; if not, the skills route on message content.

---

## 12. Roadmap

| Time | Gate | A | B | C | D |
|---|---|---|---|---|---|
| 13:00-13:40 | Contracts merged to `main`, `_llm.py` returns JSON from the box model | Slack app and connector, workspace path, allowlist | Repo skeleton pushed, `_match.py` with fixtures | `_llm.py` (think/fence stripping, retry, mock) | `schema.sql`, `_db.py`, `skills.json` v1, `_taxonomy.py` |
| 13:40-15:00 | Each side works once from the terminal | Both SKILL.md files, system prompt, agent calls one real tool from Slack, file upload test | `fetch_jobs` (GH + Lever), `extract_reqs`, `match_jobs`, `list_jobs` | `draft_role`, `approve_role`, `show_role`, `match_candidates` | `gen_candidates` (30), `ingest_profile`, `update_profile`, `seed_db`, 3 demo requests |
| 15:00 | **Checkpoint: each side end to end in Slack.** If one side fails, cut Workday and the stretch work and everyone helps | | | | |
| 15:00-16:00 | Connected flow: approved role shows up in a student's matches | Deploy, run the full story in Slack, fix prompts | `apply`, snapshots, offline mode, Workday if green | Shortlist wording and evidence quality | 2 hand-written "hero" candidates for the demo, `demo_reset.sh` |
| **16:00** | **Feature freeze** | | | | |
| 16:00-16:30 | Two full rehearsals on the box | Drives | Watches logs | Times the run | Resets the DB between runs |
| 16:30-17:15 | Video recorded (2 takes, keep the best) | Narrates | Screen recording | Backup recording | Fixes any data that looks wrong on screen |
| 17:15-17:45 | Submitted on BuilderBase | Submission | README run steps | README architecture | Repo cleanup, no secrets in history |
| 17:45-18:00 | Buffer | | | | |

Cut order if behind: tailoring, then the cron scan, then Workday, then file upload (fall back to pasted text), then `update_profile` nuance.

---

## 13. Demo script (3 min, recorded)

1. **0:00-0:20, problem.** Career offices can't hand-match hundreds of students to hundreds of roles. Resumes miss most of a person, and student data shouldn't go to a cloud API.
2. **0:20-1:10, `#hiring`.** A manager types "I need someone to build an app for our ops team." The agent asks 2 or 3 questions and drafts the JD (public plus private context). The manager approves.
3. **1:10-1:50, shortlist.** The agent ranks the 30 candidates with evidence and gaps, and a human reviews it. Point at one candidate who ranks high because of something they said in chat that isn't on their resume.
4. **1:50-2:40, `#students`.** A student pastes or uploads a resume and adds "I'd only go to Acme for a strong offer." The agent returns real Greenhouse/Lever matches plus the new internal role, one stretch match with a closable gap, and one sponsorship flag that would have wasted an F-1 student's application.
5. **2:40-3:00, close.** Everything ran on this box. Both sides match on full context through one taxonomy.

---

## 14. Risks

| Risk | Mitigation |
|---|---|
| Slack setup stalls | Telegram fallback at 13:50 |
| Sandbox rebuild wipes files | Add the channel before deploying code; the repo is the source of truth |
| Model returns bad JSON or `<think>` text | `_llm.py` strips, retries once, then returns `{"error"}`; keep prompts small |
| Allowlist silently blocks job APIs | Test from inside the sandbox early; `--offline` reads snapshots |
| One box, four people | Laptops use the tunnel; only A deploys; `MOCK_LLM=1` when the box is busy |
| Memory pressure | Watch `nvidia-smi` and `docker stats`; no second model |
| Live demo fails | Recorded video is the submission; snapshots make the run reproducible |
