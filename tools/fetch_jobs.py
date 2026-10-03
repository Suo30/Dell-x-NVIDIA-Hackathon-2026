"""Candidate: pull postings from ATS APIs (section 10) into jobs; snapshot every fetch.

Contract (MASTER_CONTEXT section 8):
    fetch_jobs.py [--source greenhouse|lever|workday|all] [--offline] [--per-company 5]
    -> {"new": [{"id", "company", "title", "url"}], "total": n, "failed": [{"company", "error"}]}

Online: fetches every company in data/companies.json matching --source, keeps up to
--per-company US early-career postings (deduplicated by title) and writes
data/snapshots/{source}-{slug}.json. Offline: loads those snapshots instead.
Jobs are inserted with INSERT OR IGNORE, so a job is "new" only the first time.
Owner: B
"""
import argparse
import html
import json
import re
import urllib.error
import urllib.request
from html.parser import HTMLParser

import _cli
import _config
import _db

SNAPSHOT_DIR = _config.DATA_DIR / "snapshots"
COMPANIES = _config.DATA_DIR / "companies.json"
GREENHOUSE = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
LEVER = "https://api.lever.co/v0/postings/{slug}?mode=json"
EARLY = re.compile(r"\b(intern|internship|co-?op|new grad(uate)?)\b", re.IGNORECASE)
US = re.compile(r",\s*[A-Z]{2}\b|United States|\bUSA\b|\bUS\b|Remote|\bD\.C\.")   # case-sensitive on purpose

JOB_KEYS = ("id", "source", "company", "title", "url", "location", "description")
SOURCES = ("greenhouse", "lever", "workday")
USER_AGENT = "career-agent-hackathon/1.0"
TIMEOUT = 20
BREAK_TAGS = {"p", "br", "li", "div", "h1", "h2", "h3", "h4", "h5", "h6"}


def _get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


class _TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in BREAK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


def _html_to_text(html_str):
    parser = _TextParser()
    parser.feed(html.unescape(html_str))
    parser.close()
    lines = [line.strip() for line in "".join(parser.parts).splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _normalize_greenhouse(company, slug, raw):
    # External boundary: Greenhouse job JSON; a missing key fails this company only
    return {
        "id": f"greenhouse:{slug}:{raw['id']}",
        "source": "greenhouse",
        "company": company,
        "title": raw["title"],
        "url": raw["absolute_url"],
        "location": raw["location"]["name"],
        "description": _html_to_text(raw["content"]),
    }


def _normalize_lever(company, slug, raw):
    parts = [raw["descriptionPlain"]]
    for section in raw["lists"]:
        parts += [section["text"], _html_to_text(section["content"])]
    # External boundary: Lever omits additionalPlain and categories.location on some postings
    parts.append(raw.get("additionalPlain") or "")
    return {
        "id": f"lever:{slug}:{raw['id']}",
        "source": "lever",
        "company": company,
        "title": raw["text"],
        "url": raw["hostedUrl"],
        "location": raw["categories"].get("location"),
        "description": "\n\n".join(p.strip() for p in parts if p.strip()),
    }


def _near_boston(job):
    return ", MA" in job["location"] or "Boston" in job["location"]


def _select(jobs, per_company):
    early_us = [j for j in jobs if EARLY.search(j["title"]) and US.search(j["location"] or "")]
    by_title = {}
    for job in early_us:
        if job["title"] not in by_title or (_near_boston(job) and not _near_boston(by_title[job["title"]])):
            by_title[job["title"]] = job
    return sorted(by_title.values(), key=lambda j: j["id"])[:per_company]


def _fetch_company(entry, per_company):
    company, source, slug = entry["company"], entry["source"], entry["slug"]
    if source == "workday":
        raise ValueError("workday is not configured (out of MVP scope)")
    if source == "greenhouse":
        jobs = [_normalize_greenhouse(company, slug, r) for r in _get_json(GREENHOUSE.format(slug=slug))["jobs"]]
    elif source == "lever":
        jobs = [_normalize_lever(company, slug, r) for r in _get_json(LEVER.format(slug=slug))]
    else:
        raise ValueError(f"{COMPANIES.name}: {company} has unknown source {source!r}, expected one of {SOURCES}")
    jobs = _select(jobs, per_company)
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    (SNAPSHOT_DIR / f"{source}-{slug}.json").write_text(
        json.dumps(jobs, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return jobs


def _load_snapshots(source):
    paths = [p for p in sorted(SNAPSHOT_DIR.glob("*.json")) if source == "all" or p.name.startswith(source + "-")]
    jobs = []
    for path in paths:
        for i, job in enumerate(json.loads(path.read_text(encoding="utf-8"))):
            missing = [k for k in JOB_KEYS if k not in job]
            if missing:
                raise RuntimeError(f"snapshot {path.name}: job [{i}] is missing {missing}")
            jobs.append(job)
    return jobs


def _insert(conn, jobs):
    first_seen = _db.now()
    new = []
    for j in jobs:
        cur = conn.execute(
            "INSERT OR IGNORE INTO jobs (id, source, company, title, url, location, description, first_seen)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (j["id"], j["source"], j["company"], j["title"], j["url"], j["location"], j["description"], first_seen),
        )
        if cur.rowcount == 1:
            new.append({"id": j["id"], "company": j["company"], "title": j["title"], "url": j["url"]})
    return new


def _fetch_online(source, per_company):
    entries = [e for e in json.loads(COMPANIES.read_text(encoding="utf-8")) if source in ("all", e["source"])]
    jobs, failed = [], []
    for entry in entries:
        # External boundary: one ATS failing must not stop the others
        try:
            jobs += _fetch_company(entry, per_company)
        except (urllib.error.URLError, OSError, KeyError, ValueError) as e:
            failed.append({"company": entry["company"], "error": f"{type(e).__name__}: {e}"})
    return jobs, failed


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--source", default="all", choices=[*SOURCES, "all"])
    p.add_argument("--offline", action="store_true", help="read data/snapshots instead of the network")
    p.add_argument("--per-company", type=int, default=5, help="max postings kept per company (online)")
    args = p.parse_args()
    if args.per_company < 1:
        raise ValueError(f"--per-company must be at least 1, got {args.per_company}")

    if args.offline:
        jobs, failed = _load_snapshots(args.source), []
    else:
        jobs, failed = _fetch_online(args.source, args.per_company)

    conn = _db.connect()
    try:
        new = _insert(conn, jobs)
        conn.commit()
        total = conn.execute("SELECT COUNT(*) FROM jobs WHERE source IN ('greenhouse','lever')").fetchone()[0]
    finally:
        conn.close()
    return {"new": new, "total": total, "failed": failed}


if __name__ == "__main__":
    _cli.run(main)
