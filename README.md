# Dell x NVIDIA Hackathon 2026: two-sided career matching agent

> One OpenClaw agent on local Qwen that writes structured job descriptions for employers and matches
> students to real ATS postings, through Slack. All inference stays on a Dell GB10 box.

## What the agent does

Built for a university career and co-op office, which serves students and hiring managers through one
agent in Slack. Everything runs in a NemoClaw sandbox on a Dell GB10, with local Qwen
(`nvidia/Qwen3.6-35B-A3B-NVFP4`) served through an OpenAI-compatible API. No student data is sent to a
cloud model.

**Students (`#students`).** A student uploads or pastes a resume and talks to the agent as they would to
an advisor. They can mention skills that aren't on the resume, location and remote preferences, visa
sponsorship needs, start date, and company-specific stances such as "I'd only go to Acme for a really
strong offer." The agent turns all of that into a profile mapped to a shared skills taxonomy. It pulls
real postings from Greenhouse, Lever and Workday, maps each posting's requirements to the same taxonomy,
and returns ranked matches with evidence, closable gaps and eligibility flags. For example, it warns an
F-1 student before they apply to a role that says it won't sponsor. With the student's consent, the
agent records the application in the app.

**Employers (`#hiring`), the Role Architect.** A hiring manager sends a vague request ("I need someone to
build an app for our ops team"). The agent asks up to three clarifying questions (seniority, location,
sponsorship, pay, timeline) and writes one job description in two layers:

- **Public JD:** title, description, location, sponsorship, clearance and optional pay. Anyone can apply.
- **Private context:** requirements mapped to the taxonomy, each with a level (1 to 3) and a must or
  nice importance, plus seniority, team context and timeline. Only used for matching.

When the manager approves the role, the agent ranks every candidate in the app against the private
context and returns a shortlist with evidence and gaps for a person to review. A manager with a finished
JD and a folder of outside applicants' resumes can instead get an evidence-first screening report (see
[Resume screener](#resume-screener-recruit_assistant)).

**One connected market.** An approved role becomes an internal job that appears in students' matches,
and both sides are scored on full context through the same taxonomy, not just on one page of resume.

## How it works

```
Slack (#hiring, #students)
        |
   OpenClaw agent (one agent, NemoClaw sandbox, local Qwen)
        |-- skill: role-architect   (employer flows)
        |-- skill: career-matcher   (candidate flows)
        |-- skill: resume-screener  (finished JD + applicant resumes)
        |
   tools/*.py  (Python CLIs, one JSON object on stdout)
        |-- model: extraction only (text -> taxonomy-mapped JSON)
        |-- code: scoring, routes, flags, sorting
        |
   SQLite (one DB)          data/skills.json (shared taxonomy)
```

Design principles:

1. **The model extracts and writes text. Code decides.** Scores, routes and flags are deterministic and
   testable, so they can be checked.
2. **One taxonomy for both sides.** Profiles, ATS postings and drafted roles all map to `data/skills.json`
   (backend, frontend, mobile, data, cloud/devops, mechanical and soft skills), with three levels:
   1 = used in a course or small project, 2 = used in a job or substantial project, 3 = designed, led or
   owned something with it.
3. **Evidence, not verdicts.** Every skill on a profile carries the verbatim resume line or chat message
   behind it. Gaps read "the evidence did not show X", never "the candidate lacks X". Nobody is rejected
   automatically; a person reviews every shortlist.

Matching logic (`tools/_match.py`, pure code):

- **Per requirement:** strong (at or above the required level), partial (one level below), none.
- **Score:** must = weight 2, nice = weight 1; strong = full credit, partial = half. Score is the weighted
  share out of 100.
- **Flags**, kept apart from the score: `sponsorship` (student needs it, posting says no), `clearance`
  (posting needs US person status or a clearance), `location` (onsite in a city the student didn't pick).
- **Routes:** `match` (score 70+ and no flags), `stretch` (50 to 70 where every gap can be closed),
  `review` (any flag, a person decides), `hidden` (everything else, never shown to an employer as a "no").
- **Company stances** only demote: `never` excludes the company, `only_strong_offer` sends a match to
  review unless the stated pay meets the student's minimum, and `eager` sorts first within its route.

## Slack walkthrough

1. In `#hiring`, a manager writes "I need someone to build an app for our ops team." The agent asks two
   or three questions, drafts the public JD and private context, and the manager approves it.
2. The agent ranks the candidate pool and returns a shortlist with evidence and gaps. Candidates can rank
   high because of something they said in chat that isn't on their resume.
3. In `#students`, a student shares a resume and adds "I'd only go to Acme for a strong offer." The agent
   returns real Greenhouse and Lever matches plus the new internal role, a stretch match with a closable
   gap, and a sponsorship flag that saves an F-1 student a wasted application.
4. The student says "apply to the first one" and the application appears on the employer side.

## Run it in mock mode

Mock mode needs no GPU, no model and no Slack. `MOCK_LLM=1` replaces every model call with canned JSON,
so the whole pipeline runs on a laptop. Job postings come from the saved snapshots in `data/snapshots/`.

Requires Python 3.10+. The core tools use only the standard library.

```bash
git clone https://github.com/Suo30/Dell-x-NVIDIA-Hackathon-2026 && cd Dell-x-NVIDIA-Hackathon-2026
cp .env.example .env                 # PowerShell: Copy-Item .env.example .env
# In .env set MOCK_LLM=1             (or: export MOCK_LLM=1 / PowerShell: $env:MOCK_LLM = "1")
pip install -r requirements.txt      # optional: PDF resume support

# Data: 30 synthetic candidates, then real postings from the offline snapshots
python scripts/seed_db.py --reset
python tools/fetch_jobs.py --offline
python tools/extract_reqs.py --pending --limit 100

# Student side
python tools/ingest_profile.py --name "Test Student" --text-file tests/fixtures/resume.txt
python tools/match_jobs.py --candidate c001 --limit 5

# Employer side
python tools/draft_role.py --company "Acme" --conversation-file data/requests/ops-app.txt
python tools/approve_role.py --role r001
python tools/match_candidates.py --role r001 --limit 10

# The approved role now shows up for students, and they can apply to it
python tools/match_jobs.py --candidate c001
python tools/apply.py --candidate c001 --job internal:r001
```

Each tool prints exactly one JSON object and exits 0; failures come back as `{"error": "..."}`. Run
`python tools/<name>.py --help` for any tool's arguments.

To check everything at once, `bash tests/smoke.sh` runs every tool once in mock mode against a throwaway
database (on Windows, use Git Bash). `bash scripts/check_local.sh` adds the unit tests (with
`pip install -r requirements-dev.txt`).

To use a real model, set `MOCK_LLM=0` and point `LLM_BASE_URL` and `LLM_MODEL` in `.env` at an
OpenAI-compatible endpoint serving Qwen. Settings are read from `.env`, then from environment variables
(`tools/_config.py`).

## Tools

| Side | Tool | What it does |
|---|---|---|
| Student | `ingest_profile.py` | Resume (txt, md, docx, pdf) to a taxonomy-mapped profile with evidence |
| Student | `update_profile.py` | Adds what the student says in chat: skills, stances, visa, location, start date |
| Student | `fetch_jobs.py` | Pulls new postings from ATS APIs, or from snapshots with `--offline` |
| Student | `extract_reqs.py` | Maps each posting's requirements to the taxonomy, with the verbatim JD line |
| Student | `list_jobs.py` / `match_jobs.py` | Lists jobs, ranks a student's matches with routes, flags and gaps |
| Student | `apply.py` | Records an application inside the app |
| Employer | `draft_role.py` | Clarifying conversation to a public JD plus private context |
| Employer | `approve_role.py` / `show_role.py` | Approves a role (it becomes an internal job), shows a role |
| Employer | `match_candidates.py` | Ranks the candidate pool against an approved role |
| Employer | `screen_resumes.py` | Scores outside applicants' resumes against a JD or approved role |

Data contracts, scoring rules and the database schema are documented in
[MASTER_CONTEXT.md](MASTER_CONTEXT.md).

## Resume screener (`recruit_assistant/`)

For people who apply to the public JD without an app profile. A job description plus 1 to 20 resumes
become one role rubric, consent-gated GitHub/LinkedIn evidence and a top-30% shortlist for human review,
all scored by local Qwen. The agent calls it through `tools/screen_resumes.py`. In Slack, a finished JD
plus uploaded resumes uses `--title` and `--jd-file`, so the agent never rewrites the manager's JD.
`--role ID` builds the rubric from an approved role's taxonomy requirements. A FastAPI API and a
Streamlit UI are also available for local use.

```bash
pip install -r requirements-recruit.txt
streamlit run streamlit_app.py                    # UI, http://localhost:8501
uvicorn recruit_assistant.main:app --reload --port 8010   # REST API, http://127.0.0.1:8010/docs
python tools/screen_resumes.py --role r001 --resumes work/applicants/   # after approve_role
python tools/screen_resumes.py --title "Senior Applied AI Scientist" \
  --jd-file /tmp/jd.txt --resumes /tmp/applicants --consent-confirmed   # finished JD + resumes
python -m pytest -q tests/test_workflow.py tests/test_screen_resumes.py
```

Model calls go through the shared `tools/_llm.py` client, so the screener uses the same model, `.env` and
`MOCK_LLM` as the tools. Details in [recruit_assistant/README.md](recruit_assistant/README.md).

## Team

Built by a team of four at the Dell x NVIDIA Hackathon, Boston, October 2026.

| Area | Scope |
|---|---|
| Platform and agent: **Iker Javier Pérez Omar** | Slack channel through the OpenClaw connector, NemoClaw sandbox and network policy, agent system prompt and skills, shared CLI and config layer, deployment to the GB10 box, end-to-end Slack runs, pitch lead |
| Candidate pipeline | ATS fetchers, requirement extraction, matching engine (`_match.py`), job matching and applications |
| Employer pipeline | Model client (`_llm.py`), role drafting, approval and candidate shortlists |
| Data and profiles | Database schema, skills taxonomy, profile ingestion and updates, synthetic candidates, demo data |
