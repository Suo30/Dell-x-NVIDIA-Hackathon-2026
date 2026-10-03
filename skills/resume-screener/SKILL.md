---
name: resume-screener
description: Hiring managers in #hiring who already have a JD and applicant resumes. Score fit the same way as the Streamlit recruiting assistant. Do not draft a new JD.
---
# Resume screener

Same pipeline as Streamlit: finished JD + resumes -> rubric -> scores.
Do not rewrite the JD. Do not invent scores.

1. Save the JD to /tmp/jd.txt exactly as given.
2. Save uploaded resumes (or pasted text as NAME.txt) into /tmp/applicants/.
3. Ask once if needed: "Were the applicants told their public GitHub/LinkedIn may be reviewed?"
4. Run:

```
python3 /sandbox/.openclaw/workspace/repo/tools/screen_resumes.py \
  --title "JOB TITLE FROM THE JD" \
  --jd-file /tmp/jd.txt \
  --resumes /tmp/applicants
```

Add `--consent-confirmed` only if the manager said yes. Never add `--discover`.

5. Paste the JSON `slack` field into the channel. End with the tool notice.
