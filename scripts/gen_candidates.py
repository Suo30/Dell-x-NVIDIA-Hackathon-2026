"""Build the 28 synthetic profiles c003..c030 into data/candidates/*.json (no model needed).
Owner: D

c001 and c002 are hand-written and never touched. Output is deterministic for a
given --seed. Archetypes are assigned by slot so the demo spread holds by construction:
mobile-strong (match the Acme demo role), mobile-stretch, mechanical, data, cloud,
frontend and embedded.
"""
import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import _cli
import _config
import _taxonomy

FIRST_ID = 3
LAST_ID = 30

# name, core {skill_id: level}, extras pool, extras per candidate, programs
ARCHETYPES = {
    "mobile-strong": ({"react-native": 2, "mysql": 2, "python": 2, "git": 2},
                      ["swift", "kotlin", "flutter", "javascript", "typescript", "nodejs", "rest-api"], 2,
                      ["BS Computer Science", "MS Computer Science"]),
    "mobile-stretch": ({"react-native": 1, "mysql": 1, "python": 1, "git": 1},
                       ["html-css", "java", "cpp", "sql", "linux"], 1,
                       ["MS Mechatronics", "BS Data Science", "BS Computer Science"]),
    "mechanical": ({"solidworks": 2, "matlab": 2},
                   ["cad", "fea", "gdt", "3d-printing", "simulink", "labview", "arduino", "excel"], 3,
                   ["MS Mechanical Engineering", "BS Mechanical Engineering"]),
    "data": ({"python": 2, "sql": 2},
             ["pandas", "postgresql", "mongodb", "machine-learning", "data-visualization", "excel",
              "tableau", "r", "mysql"], 3,
             ["MS Data Science", "BS Data Science"]),
    "cloud": ({"linux": 2, "git": 2},
              ["docker", "kubernetes", "aws", "azure", "ci-cd", "go", "java", "nodejs", "csharp",
               "dotnet", "rest-api", "cpp"], 3,
              ["MS Computer Science", "BS Computer Engineering"]),
    "frontend": ({"javascript": 2, "html-css": 2},
                 ["react", "typescript", "angular", "nodejs", "flutter", "data-visualization"], 3,
                 ["BS Computer Science"]),
    "embedded": ({"cpp": 2, "embedded-c": 2},
                 ["circuit-design", "plc", "ros", "arduino", "labview", "matlab"], 3,
                 ["MS Electrical and Computer Engineering", "BS Mechatronics"]),
}
SLOTS = (["mobile-strong"] * 6 + ["mobile-stretch"] * 5 + ["mechanical"] * 4 + ["data"] * 5
         + ["cloud"] * 4 + ["frontend"] * 2 + ["embedded"] * 2)
SOFT = ["communication", "leadership", "project-management", "teamwork", "technical-writing"]
CHAT_ONLY = ["docker", "aws", "tableau", "kubernetes", "excel", "ci-cd"]

# slot index -> company_prefs
PREFS = {
    1: [{"company": "Acme", "stance": "eager", "min_pay": None}],
    10: [{"company": "Acme", "stance": "never", "min_pay": None}],
    11: [{"company": "Acme", "stance": "never", "min_pay": None},
         {"company": "Granite Robotics", "stance": "eager", "min_pay": None}],
    15: [{"company": "Acme", "stance": "neutral", "min_pay": None},
         {"company": "Harbor Analytics", "stance": "only_strong_offer", "min_pay": 50}],
    20: [{"company": "Acme", "stance": "only_strong_offer", "min_pay": 30}],
    25: [{"company": "Northwind Defense", "stance": "never", "min_pay": None}],
}

FIRST = ["Avery", "Blair", "Casey", "Dakota", "Emerson", "Finley", "Harper", "Indigo", "Jules",
         "Kai", "Lane", "Marlowe", "Noor", "Oakley", "Parker", "Quinn", "Reese", "Sage", "Tatum",
         "Umber", "Vale", "Wren", "Yael", "Zion"]
LAST = ["Quokka", "Narwhal", "Axolotl", "Capybara", "Okapi", "Tapir", "Wombat", "Ocelot",
        "Platypus", "Marmot", "Kinkajou", "Numbat", "Tamarin", "Gecko", "Puffin", "Heron"]
CITIES = ["Boston, MA", "Boston, MA", "Boston, MA", "New York, NY", "Providence, RI", "Seattle, WA"]
REMOTE = ["any", "hybrid", "hybrid", "remote", "onsite"]
THINGS = ["inventory tracker", "sensor dashboard", "scheduling tool", "test harness", "data pipeline",
          "maintenance log", "prototype rig", "reporting service"]
CONTEXTS = ["a campus lab", "a student club", "a co-op team", "a capstone project", "a hackathon team",
            "a research group"]
CHAT_LINES = ["I've also used {name} at my last job",
              "I picked up {name} on a side project last summer",
              "I didn't put it on my resume, but I use {name} every week at my part-time job"]
VISAS = [{"status": "F-1", "needs_sponsorship": True, "us_person": False},
         {"status": "US citizen", "needs_sponsorship": False, "us_person": True},
         {"status": "F-1", "needs_sponsorship": True, "us_person": False},
         {"status": "Permanent resident", "needs_sponsorship": False, "us_person": True},
         {"status": "US citizen", "needs_sponsorship": False, "us_person": True}]


def _resume_line(rng, name, level):
    thing, context = rng.choice(THINGS), rng.choice(CONTEXTS)
    if level == 1:
        return f"Used {name} in a course project on a {thing}"
    if level == 3:
        return f"Led the design of a {thing} using {name} for {context}"
    return f"Built a {thing} using {name} for {context}"


def build(slot, rng, names):
    cid = f"c{FIRST_ID + slot:03d}"
    archetype = SLOTS[slot]
    core, pool, n_extra, programs = ARCHETYPES[archetype]
    nth = SLOTS[:slot].count(archetype)

    levels = dict(core)
    if archetype in ("mobile-strong", "mechanical") and rng.random() < 0.4:
        levels[next(iter(core))] = 3
    for j in range(n_extra):
        extra = pool[(nth * n_extra + j) % len(pool)]
        if extra not in levels:
            levels[extra] = rng.choice([1, 1, 2])
    levels[SOFT[slot % len(SOFT)]] = rng.choice([1, 2])

    skills, bullets = [], []
    for sid, level in levels.items():
        text = _resume_line(rng, _taxonomy.name_of(sid), level)
        bullets.append({"id": f"b{len(bullets) + 1}", "text": text})
        skills.append({"skill_id": sid, "level": level, "evidence": [{"source": "resume", "text": text}]})

    if slot % 3 == 0:
        sid = next(s for s in CHAT_ONLY if s not in levels)
        line = rng.choice(CHAT_LINES).format(name=_taxonomy.name_of(sid))
        skills.append({"skill_id": sid, "level": rng.choice([1, 2]),
                       "evidence": [{"source": "chat", "text": line}]})

    school = "Northeastern University" if slot % 6 else rng.choice(
        ["Wentworth Institute of Technology", "UMass Boston"])
    return {
        "id": cid,
        "name": names[slot],
        "school": school,
        "program": programs[nth % len(programs)],
        "visa": dict(VISAS[slot % len(VISAS)]),
        "availability": {"start": rng.choice(["2027-01", "2027-01", "2026-07", "2027-05"]),
                         "type": rng.choice(["co-op", "co-op", "internship", "full-time"])},
        "location": {"preferred": [rng.choice(CITIES)], "remote": rng.choice(REMOTE)},
        "skills": skills,
        "bullets": bullets,
        "company_prefs": [dict(p) for p in PREFS[slot]] if slot in PREFS else [],
        "notes": [],
    }


def generate(out_dir, seed):
    rng = random.Random(seed)
    count = LAST_ID - FIRST_ID + 1
    if len(SLOTS) != count:
        raise RuntimeError(f"gen_candidates: {len(SLOTS)} archetype slots for {count} candidates")
    names = [f"{f} {last}" for f, last in rng.sample([(f, la) for f in FIRST for la in LAST], count)]
    out_dir.mkdir(parents=True, exist_ok=True)
    for slot in range(count):
        profile = build(slot, rng, names)
        text = json.dumps(profile, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        (out_dir / f"{profile['id']}.json").write_text(text, encoding="utf-8", newline="\n")
    return count


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--seed", type=int, default=2026)
    p.add_argument("--out", type=Path, default=None, help="output dir (default DATA_DIR/candidates)")
    args = p.parse_args()
    out_dir = args.out if args.out is not None else _config.DATA_DIR / "candidates"
    return {"written": generate(out_dir, args.seed), "dir": str(out_dir)}


if __name__ == "__main__":
    _cli.run(main)
