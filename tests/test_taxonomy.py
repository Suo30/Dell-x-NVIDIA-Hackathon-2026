import json

import pytest

import _config
import _taxonomy
from conftest import ROOT


@pytest.fixture(autouse=True)
def clear_cache():
    _taxonomy._index.cache_clear()
    yield
    _taxonomy._index.cache_clear()


def _write_skills(tmp_path, monkeypatch, skills):
    (tmp_path / "skills.json").write_text(json.dumps(skills), encoding="utf-8")
    monkeypatch.setattr(_config, "DATA_DIR", tmp_path)


def test_real_file_size_and_categories():
    skills = _taxonomy.load()
    assert 40 <= len(skills) <= 60
    assert {s["category"] for s in skills} == _taxonomy.CATEGORIES


def test_aliases_lowercase():
    for s in _taxonomy.load():
        for a in s["aliases"]:
            assert a == a.lower(), s["id"]


@pytest.mark.parametrize("name", ["MySQL", "  mysql ", "MariaDB"])
def test_resolve_mysql(name):
    assert _taxonomy.resolve(name) == "mysql"


@pytest.mark.parametrize("name", ["React-Native", "react_native", "React Native"])
def test_resolve_react_native(name):
    assert _taxonomy.resolve(name) == "react-native"


def test_punctuated_names_distinct():
    cpp, cs = _taxonomy.resolve("C++"), _taxonomy.resolve("C#")
    assert cpp is not None and cs is not None and cpp != cs


@pytest.mark.parametrize("name,sid", [("Node.js", "nodejs"), (".NET", "dotnet"), ("CI/CD", "ci-cd"),
                                      ("continuous integration", "ci-cd"), ("c plus plus", "cpp")])
def test_resolve_punctuated_aliases(name, sid):
    assert _taxonomy.resolve(name) == sid


def test_resolve_unknown():
    assert _taxonomy.resolve("Cobol for goats") is None


def test_resume_skills_line_resolves():
    lines = (ROOT / "tests" / "fixtures" / "resume.txt").read_text(encoding="utf-8").splitlines()
    skills_line = lines[lines.index("SKILLS") + 1]
    names = [n.strip() for n in skills_line.split(",")] + ["Docker"]
    unresolved = [n for n in names if _taxonomy.resolve(n) is None]
    assert unresolved == []


def test_name_of_every_id():
    for s in _taxonomy.load():
        assert _taxonomy.name_of(s["id"]) == s["name"]


def test_name_of_unknown():
    with pytest.raises(RuntimeError, match="nope"):
        _taxonomy.name_of("nope")


def test_prompt_block():
    block = _taxonomy.prompt_block()
    lines = block.splitlines()
    assert len(lines) == len(_taxonomy.load())
    ids = {line.split(":", 1)[0] for line in lines}
    assert ids == {s["id"] for s in _taxonomy.load()}
    assert len(block) < 4000
    assert "mysql: MySQL (my sql, mariadb)" in lines
    assert "react-native: React Native" in lines


def test_shared_alias_rejected(tmp_path, monkeypatch):
    _write_skills(tmp_path, monkeypatch, [
        {"id": "javascript", "name": "JavaScript", "category": "frontend", "aliases": ["js"]},
        {"id": "json", "name": "JSON", "category": "data", "aliases": ["js"]},
    ])
    with pytest.raises(RuntimeError) as e:
        _taxonomy.load()
    assert "javascript" in str(e.value) and "json" in str(e.value)


def test_unknown_category_rejected(tmp_path, monkeypatch):
    _write_skills(tmp_path, monkeypatch, [
        {"id": "mysql", "name": "MySQL", "category": "database", "aliases": []},
    ])
    with pytest.raises(RuntimeError, match="database"):
        _taxonomy.load()


def test_bad_id_rejected(tmp_path, monkeypatch):
    _write_skills(tmp_path, monkeypatch, [
        {"id": "C++", "name": "C++", "category": "backend", "aliases": []},
    ])
    with pytest.raises(RuntimeError, match="must match"):
        _taxonomy.load()
