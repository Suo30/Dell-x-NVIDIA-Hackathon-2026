"""Shared skills taxonomy (data/skills.json, MASTER_CONTEXT 6.1). Owner: D.

    load() -> list[dict]
        The raw skills list.
    resolve(name: str) -> str | None
        Case/space-insensitive lookup over id, name and aliases -> skill_id.
    name_of(skill_id: str) -> str
        Display name, for gaps_text ("The evidence did not show MySQL ...").
    prompt_block() -> str
        Compact "id: Name (aliases)" list to paste into extraction prompts so
        the model only emits known skill_ids. Callers drop unknown ids with resolve().

skills.json is validated on first load (ids, categories, no shared keys);
a bad file raises RuntimeError. Tests reset the cache with _index.cache_clear().
"""
import functools
import json
import re

import _config

CATEGORIES = {"backend", "frontend", "mobile", "data", "cloud-devops", "mechanical", "soft"}
_ID_RE = re.compile(r"^[a-z0-9-]+$")


def _norm(s):
    return " ".join(s.lower().replace("-", " ").replace("_", " ").split())


@functools.lru_cache(maxsize=1)
def _index():
    path = _config.DATA_DIR / "skills.json"
    skills = json.loads(path.read_text(encoding="utf-8"))
    by_key, by_id = {}, {}
    for s in skills:
        for field in ("id", "name", "category", "aliases"):
            if field not in s:
                raise RuntimeError(f"{path}: skill {s!r} missing {field!r}")
        if not _ID_RE.match(s["id"]):
            raise RuntimeError(f"{path}: id {s['id']!r} must match {_ID_RE.pattern}")
        if s["category"] not in CATEGORIES:
            raise RuntimeError(f"{path}: {s['id']} has unknown category {s['category']!r}")
        if s["id"] in by_id:
            raise RuntimeError(f"{path}: duplicate id {s['id']!r}")
        by_id[s["id"]] = s
        for key in {_norm(s["id"]), _norm(s["name"]), *(_norm(a) for a in s["aliases"])}:
            if key in by_key and by_key[key] != s["id"]:
                raise RuntimeError(f"{path}: key {key!r} used by both {by_key[key]} and {s['id']}")
            by_key[key] = s["id"]
    return skills, by_key, by_id


def load():
    return _index()[0]


def resolve(name):
    # Model boundary: None means the model named a skill we do not track
    return _index()[1].get(_norm(name))


def name_of(skill_id):
    try:
        return _index()[2][skill_id]["name"]
    except KeyError:
        raise RuntimeError(f"unknown skill id {skill_id!r}") from None


def prompt_block():
    lines = []
    for cat in sorted(CATEGORIES):
        for s in [s for s in load() if s["category"] == cat]:
            line = f"{s['id']}: {s['name']}"
            if s["aliases"]:
                line += f" ({', '.join(s['aliases'])})"
            lines.append(line)
    return "\n".join(lines)
