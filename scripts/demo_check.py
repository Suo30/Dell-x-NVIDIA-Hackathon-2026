"""Demo gate: replays the plan section 5 story and prints PASS or FAIL per beat. Owner: D.

    python scripts/demo_check.py

Copies work/demo_start.db (built by `bash scripts/demo_reset.sh` with the live model) to
work/demo_check.db and runs every tool against the copy, so the real demo DB is never touched.
Tools always run with the live model (MOCK_LLM=0). Exit code is the number of failed beats.
If a beat fails, fix the data (prompts, snapshots, c002), not the tools; never hand-edit matches.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import aux_math

START = REPO / "work" / "demo_start.db"
CHECK = REPO / "work" / "demo_check.db"
CONVERSATION = "data/requests/demo-acme-conversation.txt"
RESUME = "tests/fixtures/resume.txt"
STUDENT = "Jordan Rivera"
PREF_NOTE = "I'd only go to Palantir for a really strong offer, at least 60 an hour"
TOOL_TIMEOUT = 900


class ToolError(Exception):
    """A tool returned {"error"} or no JSON; the message is shown on the FAIL line."""


def _tool(script, *args):
    env = {**os.environ, "DB_PATH": str(CHECK), "MOCK_LLM": "0"}
    try:
        proc = subprocess.run([sys.executable, script, *args], cwd=REPO, env=env, check=False,
                              capture_output=True, text=True, encoding="utf-8", timeout=TOOL_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise ToolError(f"{script} timed out after {TOOL_TIMEOUT}s") from None
    # Subprocess boundary: a crashed tool prints no JSON
    try:
        out = json.loads(proc.stdout)
    except ValueError:
        raise ToolError(f"{script} printed no JSON (exit {proc.returncode}): {proc.stderr.strip()[-300:]}") from None
    if not isinstance(out, dict):
        raise ToolError(f"{script} printed {type(out).__name__}, expected an object")
    if "error" in out:
        raise ToolError(f"{script}: {out['error']}")
    return out


def _c002_chat_mysql():
    profile = json.loads((REPO / "data" / "candidates" / "c002.json").read_text(encoding="utf-8"))
    for skill in profile["skills"]:
        if skill["skill_id"] == "mysql":
            for ev in skill["evidence"]:
                if ev["source"] == "chat":
                    return ev["text"]
    raise RuntimeError("data/candidates/c002.json has no chat-sourced MySQL evidence; the demo needs it")


# Beats: each takes the shared state, runs one tool and returns one (ok, detail) per check name.

def draft(state):
    out = _tool("tools/draft_role.py", "--company", "Acme", "--conversation-file", CONVERSATION)
    state["draft_role"] = out["role_id"]
    must = sorted(r["skill_id"] for r in out["private"]["requirements"] if r["importance"] == "must")
    return [({"react-native", "mysql"} <= set(must), f"{out['role_id']} must: {', '.join(must) or 'none'}")]


def approve(state):
    role_id = state["draft_role"]
    out = _tool("tools/approve_role.py", "--role", role_id)
    ok = out["status"] == "approved" and out["job_id"] == f"internal:{role_id}"
    if ok:
        state["approve_role"] = out["job_id"]
    return [(ok, f"{role_id} is {out['status']}, job {out['job_id']}")]


def shortlist(state):
    out = _tool("tools/match_candidates.py", "--role", state["draft_role"], "--limit", "10")
    rows = [r for r in out["shortlist"] if r["candidate_id"] == "c002"]
    if not rows:
        detail = f"c002 not in the top 10 (counts {out['counts']})"
        return [(False, detail), (False, detail)]
    row, evidence = rows[0], state["c002_evidence"]
    return [(row["route"] == "match", f"c002 route {row['route']}, score {row['score']}"),
            (evidence in row["top_evidence"], f"top_evidence {row['top_evidence']}")]


def ingest(state):
    out = _tool("tools/ingest_profile.py", "--name", STUDENT, "--text-file", RESUME)
    state["ingest_profile"] = out["candidate_id"]
    detail = f"{out['candidate_id']}, {out['skills_found']} skills, missing {out['missing']}"
    return [(out["skills_found"] > 0, detail)]


def update(state):
    out = _tool("tools/update_profile.py", "--candidate", state["ingest_profile"], "--note", PREF_NOTE)
    ok = any(c["type"] == "company_pref" and c["company"].lower() == "palantir"
             and c["stance"] == "only_strong_offer" and c["min_pay"] is not None
             and aux_math.eq(c["min_pay"], 60) for c in out["changes"])
    return [(ok, f"changes {out['changes']}, ignored {out['ignored']}")]


def student_matches(state):
    out = _tool("tools/match_jobs.py", "--candidate", state["ingest_profile"], "--limit", "8")
    rows = out["matches"]
    ids = [r["job_id"] for r in rows]
    stretch = [r["job_id"] for r in rows if r["route"] == "stretch"]
    clearance = [r["job_id"] for r in rows if "clearance" in r["flags"]]
    real = sorted({r["company"] for r in rows if not r["job_id"].startswith(("internal:", "test:"))})
    if "approve_role" in state:
        internal = (state["approve_role"] in ids, f"{state['approve_role']} in {ids}")
    else:
        internal = (False, "skipped: approve_role failed")
    return [internal,
            (len(stretch) >= 1, f"stretch: {stretch}"),
            (len(clearance) >= 1, f"clearance flag: {clearance}"),
            (len(real) >= 2, f"companies: {real}")]


def apply_internal(state):
    job_id = state["approve_role"]
    out = _tool("tools/apply.py", "--candidate", state["ingest_profile"], "--job", job_id)
    status = out["application"]["status"]
    return [(status == "submitted", f"{job_id} {status}")]


BEATS = [
    (["draft_role: react-native and mysql are must"], [], draft),
    (["approve_role: internal job published"], ["draft_role"], approve),
    (["match_candidates: c002 is match", "match_candidates: c002 shows its chat MySQL evidence"],
     ["approve_role"], shortlist),
    ([f"ingest_profile: {STUDENT} stored"], [], ingest),
    (["update_profile: Palantir only_strong_offer at min_pay 60"], ["ingest_profile"], update),
    (["match_jobs: internal role listed", "match_jobs: at least 1 stretch",
      "match_jobs: at least 1 clearance flag", "match_jobs: at least 2 real companies"],
     ["ingest_profile"], student_matches),
    (["apply: internal job submitted"], ["ingest_profile", "approve_role"], apply_internal),
]


def main():
    if not START.is_file():
        print(f"FAIL  demo start DB: {START.relative_to(REPO).as_posix()} is missing; "
              "run `bash scripts/demo_reset.sh` with the live model first")
        return 1
    shutil.copyfile(START, CHECK)
    state = {"c002_evidence": _c002_chat_mysql()}
    failed = total = 0
    for names, needs, beat in BEATS:
        missing = [n for n in needs if n not in state]
        if missing:
            results = [(False, f"skipped: {missing[0]} failed")] * len(names)
        else:
            try:
                results = beat(state)
            except ToolError as e:
                results = [(False, str(e))] * len(names)
            except (KeyError, TypeError, IndexError, AttributeError) as e:
                # Subprocess JSON boundary: output that breaks a tool contract fails the beat
                results = [(False, f"unexpected tool output: {type(e).__name__}: {e}")] * len(names)
        for name, (ok, detail) in zip(names, results, strict=True):
            print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")
            total += 1
            failed += not ok
    print(f"demo_check: {failed} of {total} failed (DB copy {CHECK.relative_to(REPO).as_posix()})")
    return failed


if __name__ == "__main__":
    sys.exit(main())
