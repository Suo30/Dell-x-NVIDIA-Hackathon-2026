---
name: role-architect
description: Hiring managers in #hiring: turn a vague role request into a public JD plus private requirements, then shortlist candidates.
---
# Role Architect

Tools live at /sandbox/.openclaw/workspace/repo/tools/

1. Read the request. From seniority, location/remote, sponsorship, pay and timeline,
   ask only the (max 3) most important missing ones, in one message. Skip any the
   manager already answered.
2. Write the whole exchange to a file with exec:
   cat > /tmp/conv-SLUG.txt <<'EOF'
   MANAGER: ...
   AGENT: ...
   MANAGER: ...
   EOF
3. python3 /sandbox/.openclaw/workspace/repo/tools/draft_role.py --company "COMPANY" --conversation-file /tmp/conv-SLUG.txt
   Never add --paid unless the manager says the company is a paying partner.
4. Show the public JD in full. Show the private context as a short list: skill,
   level 1-3, must or nice, why. Ask: approve, or what to change?
   Levels: 1 = used in a course or small project, 2 = used in a job or substantial
   project, 3 = designed, led or owned it.
5. If they want changes, append them to the conversation file and run draft_role again.
6. On approval run:
   python3 /sandbox/.openclaw/workspace/repo/tools/approve_role.py --role ROLE_ID
   then
   python3 /sandbox/.openclaw/workspace/repo/tools/match_candidates.py --role ROLE_ID --limit 5
7. Present the shortlist in tool order. Per candidate: name, score, route,
   top_evidence, gaps_text, flags. End with: "This is a shortlist for your review.
   Nothing is decided." Say the role is now visible to students.
