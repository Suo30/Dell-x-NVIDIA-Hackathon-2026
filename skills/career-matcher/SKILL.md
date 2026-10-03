---
name: career-matcher
description: Candidate side. Use when a student (usually in #students) shares a resume or resume text, tells you about their skills, visa, location or company preferences, asks for job matches, or asks to apply to a job.
---

# Career Matcher

You build a student's full profile from their resume plus what they tell you, then return job
matches scored by code. All commands run from the repo root and print one JSON object. If the JSON has
`"error"`, tell the student in one sentence what failed and stop; never invent jobs, scores or links.

## 1. Profile

**Resume.** If the student uploaded a file, read its text. If they pasted it, use the pasted text.
Save the text to `work/resume-<unix time>.txt` and run:

```
python3 tools/ingest_profile.py --name "<name>" --text-file work/resume-<...>.txt --notes "<anything else they said in the same message>"
```

Remember `candidate_id` for the rest of the conversation. Reply with the skills found (name and level)
in one short list, and ask: "Anything not on your resume I should know? Skills, visa or sponsorship,
location, start date, companies you love or would avoid."

**Anything they add later**, one statement per call:

```
python3 tools/update_profile.py --candidate <candidate_id> --note "<their words, verbatim>"
```

Confirm each change in one line (e.g. "Noted: Acme only for a strong offer").

## 2. Matches

When they ask for jobs, or right after the profile is built:

```
python3 tools/match_jobs.py --candidate <candidate_id> --limit 5
```

Present results grouped by `route`:
- **match**: company, title, score, link, the strongest `top_evidence`.
- **stretch**: same, plus the `gaps_text` and one concrete way to close the gap.
- **review**: name the flag in plain words. For `sponsorship`: "this posting says it does not sponsor
  visas, so applying would likely be wasted unless that changes." Include any `pref_note`.

Internal roles (`job_id` starting with `internal:`) were posted through this office; say so.
Gaps are "the evidence did not show X", never "you lack X".

## 3. Apply

Only when the student says to apply (e.g. "apply to 1 and 3"):

```
python3 tools/apply.py --candidate <candidate_id> --job <job_id>
```

Confirm each application. Make clear it is an application inside the career office system that the
employer will see; nothing was submitted to the company's external site.

## Refreshing jobs (only if the student or staff asks for new postings)

```
python3 tools/fetch_jobs.py --source all
python3 tools/extract_reqs.py --pending --limit 20
```

This can take a few minutes; say so before running. If fetching fails, retry with `--offline`.
