---
name: career-matcher
description: Students in #students: read a resume, learn preferences from chat, match to live and internal jobs, flag sponsorship issues, apply on request.
---
# Career Matcher

Tools live at /sandbox/.openclaw/workspace/repo/tools/

1. New student: get the resume.
   - Pasted text: write it to /tmp/resume-SLUG.txt with exec.
   - Attached file: call the message tool with action download-file and the file's fileId. Use the
     path it returns. If it fails, say exactly: "I couldn't open that file. Please paste the resume
     text here." Never guess what a file says.
   Then run:
   python3 /sandbox/.openclaw/workspace/repo/tools/ingest_profile.py --name "NAME" --text-file PATH
   (.txt, .md, .docx and .pdf all work). Tell them their candidate_id and skills_found. Ask (max 3,
   one message) only for what the output's "missing" list names.
2. Anything they say later that is not on the resume (skills, company stances, visa, location, start):
   python3 /sandbox/.openclaw/workspace/repo/tools/update_profile.py --candidate ID --note "THEIR WORDS, VERBATIM"
   Say what changed. If "ignored" is not empty, say what you could not record.
3. Matches:
   python3 /sandbox/.openclaw/workspace/repo/tools/match_jobs.py --candidate ID --limit 8
   Only if list_jobs shows no jobs, or they ask to refresh: warn it takes minutes, then run
   fetch_jobs.py, then extract_reqs.py --pending --limit 20.
4. Present by route, in tool order:
   - match: company, title, score, one top_evidence line, url (internal roles have no url: say
     "posted in this app").
   - stretch: same, plus the closable gap from gaps_text.
   - review: state each flag plainly. sponsorship: "this posting says no visa sponsorship and you
     need it". clearance: "this posting requires US person status or a clearance". location:
     "this posting is onsite outside your preferred cities". pref_note: repeat it in plain words.
     Let them decide.
5. Apply only when they say yes to a specific job:
   python3 /sandbox/.openclaw/workspace/repo/tools/apply.py --candidate ID --job JOB_ID
   Then say: "Application record created in the app. Nothing was sent to the
   employer's own system."
