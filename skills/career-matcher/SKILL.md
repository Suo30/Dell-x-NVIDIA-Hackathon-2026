---
name: career-matcher
description: Students in #students: read a resume, learn preferences from chat, match to live and internal jobs, flag sponsorship issues, apply on request.
---
# Career Matcher

Tools live at /sandbox/.openclaw/workspace/repo/tools/

1. New student: get resume text (pasted, or an uploaded file). Write pasted text to
   /tmp/resume-SLUG.txt, then run:
   python3 /sandbox/.openclaw/workspace/repo/tools/ingest_profile.py --name "NAME" --text-file PATH
   Tell them their candidate_id and how many skills were found. Ask (max 3, one
   message) for what is missing: location, remote, visa or sponsorship, start date,
   companies they care about.
2. Anything they say later that is not on the resume (skills, stances, constraints):
   python3 /sandbox/.openclaw/workspace/repo/tools/update_profile.py --candidate ID --note "THEIR WORDS, VERBATIM"
   Say what changed.
3. Matches:
   python3 /sandbox/.openclaw/workspace/repo/tools/match_jobs.py --candidate ID --limit 5
   Run fetch_jobs.py, then extract_reqs.py --pending --limit 20, only if jobs are
   empty or they ask to refresh. Both are slow, so warn them first.
4. Present by route, in tool order:
   - match: company, title, score, one evidence line, url
   - stretch: same, plus the closable gap and what would close it
   - review: state the flag plainly (for example "this posting says no sponsorship
     and you need it on F-1"). Let them decide.
5. Apply only when they say yes to a specific job:
   python3 /sandbox/.openclaw/workspace/repo/tools/apply.py --candidate ID --job JOB_ID
   Then say: "Application record created in the app. Nothing was sent to the
   employer's own system."
