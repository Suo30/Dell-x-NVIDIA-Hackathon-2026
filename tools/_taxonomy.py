"""Shared skills taxonomy (data/skills.json, MASTER_CONTEXT 6.1). Owner: D.

    load() -> list[dict]
        The raw skills list.
    resolve(name: str) -> str | None
        Case/space-insensitive lookup over id, name and aliases -> skill_id.
    name_of(skill_id: str) -> str
        Display name, for gaps_text ("The evidence did not show MySQL ...").
    category_of(skill_id: str) -> str
        Taxonomy category ("soft_skill", "backend", ...), used to split scores.
    prompt_block() -> str
        Compact "id: Name (aliases)" list to paste into extraction prompts so
        the model only emits known skill_ids. Callers drop unknown ids with resolve().
"""
import json

import _config

_SKILLS = None
_BY_SKILL_ID = None
_ALIAS_INDEX = None


def _normalize(text):
    return " ".join(text.strip().lower().split())


def load():
    global _SKILLS
    if _SKILLS is None:
        path = _config.DATA_DIR / "skills.json"
        _SKILLS = json.loads(path.read_text(encoding="utf-8"))
    return _SKILLS


def _index():
    global _BY_SKILL_ID, _ALIAS_INDEX
    if _BY_SKILL_ID is None:
        by_id = {}
        aliases = {}
        for skill in load():
            by_id[skill["id"]] = skill
            aliases[_normalize(skill["id"])] = skill["id"]
            aliases[_normalize(skill["name"])] = skill["id"]
            for alias in skill["aliases"]:
                aliases[_normalize(alias)] = skill["id"]
        _BY_SKILL_ID = by_id
        _ALIAS_INDEX = aliases
    return _BY_SKILL_ID, _ALIAS_INDEX


def resolve(name):
    _, aliases = _index()
    return aliases.get(_normalize(name))


def name_of(skill_id):
    by_id, _ = _index()
    if skill_id not in by_id:
        raise RuntimeError(f"name_of: unknown skill_id {skill_id!r}, not in data/skills.json")
    return by_id[skill_id]["name"]


def category_of(skill_id):
    by_id, _ = _index()
    if skill_id not in by_id:
        raise RuntimeError(f"category_of: unknown skill_id {skill_id!r}, not in data/skills.json")
    return by_id[skill_id]["category"]


def prompt_block():
    lines = []
    for skill in load():
        alias_text = f" ({', '.join(skill['aliases'])})" if skill["aliases"] else ""
        lines.append(f"{skill['id']}: {skill['name']}{alias_text}")
    return "\n".join(lines)
