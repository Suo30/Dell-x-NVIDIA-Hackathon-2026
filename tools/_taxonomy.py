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
"""
import _config


def load():
    raise NotImplementedError("_taxonomy.load (owner: D)")


def resolve(name):
    raise NotImplementedError("_taxonomy.resolve (owner: D)")


def name_of(skill_id):
    raise NotImplementedError("_taxonomy.name_of (owner: D)")


def prompt_block():
    raise NotImplementedError("_taxonomy.prompt_block (owner: D)")
