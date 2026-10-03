# Evidence-First Recruiting Agent

A local-first hiring decision-support agent for the Dell × NVIDIA AI Hackathon.
It reads 1–20 resumes, researches candidate-provided professional profiles, and
uses a locally served Qwen model to organize job-relevant evidence.

It does **not** automatically reject candidates or make final hiring decisions.
The shortlist ranks demonstrated evidence against this job only. Missing
profiles, parsing errors, unavailable tools, and uncertain evidence always
remain visible and route to human review.

## Current workflow

1. Accept a job name, job description, and 1–20 resumes.
2. Extract PDF, DOCX, or text content, including embedded clickable profile
   links, and cache it locally by SHA-256 hash.
3. Find GitHub and LinkedIn URLs included by the candidate in their resume.
4. With explicit notice/consent, use Agent Reach's Exa search route plus the
   GitHub API to find public professional profiles even when no URL is present.
   Match the public name against resume-stated location, employer, or role.
   Name-only results are not proposed.
5. Require a person to confirm every discovered profile before using it.
6. Retrieve candidate-provided or human-confirmed public profiles.
7. Remove popularity signals and protected/sensitive information.
8. Ask local Qwen to create one role-specific rubric from the JD and reuse it
   for every candidate.
9. Calculate work-history tenure from dated roles, merge overlaps, and compare
   both calculated and explicitly stated experience with numeric job requirements.
10. Score required and preferred rubric criteria separately. Show source coverage
   independently so a missing profile is unknown rather than a qualification gap.
11. Show the top 30% of current evidence scores for human review, including ties.
   Strong generic software experience does not satisfy an AI-specific rubric.

Name-only web matching remains disabled because a name match does not establish
identity. Discovered profiles remain visibly unverified and excluded from
analysis and scoring until a hiring manager confirms the identity.

Full-web discovery uses the locally configured `mcporter` Exa MCP route and sends
the search query (name and corroborating professional hints) to Exa. Raw search
snippets are not persisted.

## Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn recruit_assistant.main:app --reload
```

Interactive API documentation is at http://127.0.0.1:8000/docs.

## Streamlit UI

The UI runs directly against local storage, so the FastAPI server does not need
to be running:

```bash
source .venv/bin/activate
streamlit run streamlit_app.py
```

Open http://localhost:8501, enter the job information, upload 1–20 resumes, and
run professional-evidence research after confirming notice/consent.

## Local Qwen endpoint

The application calls only an OpenAI-compatible endpoint on localhost:

```bash
export LOCAL_LLM_BASE_URL=http://127.0.0.1:8001/v1
export LOCAL_LLM_MODEL=qwen
```

Serve the downloaded Qwen model with the event's local NVIDIA/NIM, vLLM, or
llama.cpp runtime. The app rejects a `LOCAL_LLM_BASE_URL` whose hostname is not
`localhost`, `127.0.0.1`, or `::1`, preventing accidental cloud LLM calls.

## Create a job intake

```bash
curl -X POST http://127.0.0.1:8000/jobs/intake \
  -F "job_name=Senior Backend Engineer" \
  -F "job_description=Build Python APIs; production FastAPI is required." \
  -F "professional_research_consent=true" \
  -F "resumes=@/path/to/resume1.pdf" \
  -F "resumes=@/path/to/resume2.pdf"
```

Supported uploads are `.pdf`, `.docx`, `.doc`, and `.txt`, up to 10 MB each.
Legacy `.doc` files are retained but need conversion before text extraction.
Image-only documents are retained and safely marked as requiring OCR/review.

## Run research

Candidate-provided profile links are used automatically:

```bash
curl -X POST http://127.0.0.1:8000/jobs/JOB_ID/research \
  -H "Content-Type: application/json" \
  -d '{"consent_confirmed": true}'
```

To add a hiring-manager-confirmed profile:

```bash
curl -X POST http://127.0.0.1:8000/jobs/JOB_ID/research \
  -H "Content-Type: application/json" \
  -d '{
    "consent_confirmed": true,
    "candidates": [{
      "resume_id": "RESUME_ID",
      "github_url": "https://github.com/confirmed-user",
      "linkedin_url": "https://linkedin.com/in/confirmed-user",
      "identity_confirmed": true
    }]
  }'
```

Every fetched source records its URL, retrieval timestamp, filtered excerpt,
content hash, retrieval status, and identity basis.

## OpenClaw / NemoClaw tool

The REST API can be registered as an OpenAPI tool. A CLI entry point is also
available for OpenShell:

```bash
python -m recruit_assistant.cli research-job \
  --job-id JOB_ID \
  --consent-confirmed
```

Connect that tool through the event's OpenClaw Slack, Discord, or Telegram
connector. All model inference remains local; GitHub and LinkedIn access are
explicit web-tool calls.

Agent-Reach is an optional capability/diagnostic layer on the GB10:

```bash
pip install \
  "git+https://github.com/Panniantong/Agent-Reach.git@a19a171fa980a0785849596492e0af4db800c82f"
agent-reach doctor
```

This application follows Agent-Reach's zero-configuration routes directly:
the official public GitHub API and Jina Reader for candidate-provided public
LinkedIn pages. LinkedIn content is never persisted unless local Qwen first
filters it to job-relevant, non-sensitive evidence.

## API

- `GET /health` — service health
- `POST /jobs/intake` — job and resume intake
- `GET /jobs` — list intakes
- `GET /jobs/{job_id}` — intake and parsing metadata
- `POST /jobs/{job_id}/research` — consent-gated research and local fit analysis

## Local data

```text
.data/jobs/{job_id}/
  manifest.json
  resumes/{resume_id}.pdf
  extracted/{resume_id}.txt
  research/{run_id}.json
```
