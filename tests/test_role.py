import copy

import _role
import pytest

PUBLIC = {
    "title": "Ops App Engineer (Co-op)",
    "description": "Build an internal app for the ops team.",
    "location": "Boston, MA (hybrid)",
    "sponsorship": True,
    "clearance": "none",
    "pay": None,
}
PRIVATE = {
    "requirements": [
        {"skill_id": "python", "level": 2, "importance": "must", "why": "backend"},
        {"skill_id": "mysql", "level": 2, "importance": "must", "why": "data layer"},
        {"skill_id": "react", "level": 1, "importance": "nice", "why": "simple UI"},
    ],
    "seniority": "co-op",
    "team_context": "2 engineers",
    "timeline": "Jan 2027",
}


def _role_with(path, value):
    role = copy.deepcopy({"public": PUBLIC, "private": PRIVATE})
    obj = role
    for key in path[:-1]:
        obj = obj[key]
    obj[path[-1]] = value
    return role


def test_validate_accepts_fixture_role():
    _role.validate({"public": PUBLIC, "private": PRIVATE}, "test")


@pytest.mark.parametrize("path,value,field", [
    (("public", "clearance"), "secret", "public.clearance"),
    (("private", "requirements", 0, "level"), 4, "private.requirements[0].level"),
    (("private", "requirements", 0, "level"), "2", "private.requirements[0].level"),
    (("private", "requirements", 0, "importance"), "required", "private.requirements[0].importance"),
    (("private", "requirements", 1, "skill_id"), "python", "private.requirements[1].skill_id"),
    (("private", "requirements"), [], "private.requirements"),
    (("private", "requirements", 0, "skill_id"), "cobol", "private.requirements[0].skill_id"),
])
def test_validate_rejects(path, value, field):
    with pytest.raises(ValueError, match=r"^test: " + field.replace("[", r"\[").replace("]", r"\]") + " "):
        _role.validate(_role_with(path, value), "test")


def test_clean_resolves_alias_and_drops_unknown():
    raw = [
        {"skill_id": "React Native", "level": 2, "importance": "must", "why": "owns the app"},
        {"skill_id": "COBOL", "level": 2, "importance": "must", "why": "legacy"},
    ]
    reqs, dropped = _role.clean_requirements(raw, "t")
    assert [r["skill_id"] for r in reqs] == ["react-native"]
    assert dropped == [{"skill": "COBOL", "reason": "not in taxonomy"}]


def test_clean_coerces_and_drops_bad_fields():
    raw = [
        {"skill_id": "python", "level": "2", "importance": "MUST", "why": "", "evidence_text": " 2+ yrs "},
        {"skill_id": "git", "level": 5, "importance": "nice", "why": "x"},
        {"skill_id": "mysql", "level": 1, "importance": "required", "why": "x"},
        "not a dict",
    ]
    reqs, dropped = _role.clean_requirements(raw, "t")
    assert reqs == [{"skill_id": "python", "level": 2, "importance": "must", "why": "Python",
                     "evidence_text": "2+ yrs"}]
    assert [d["reason"] for d in dropped] == ["level 5", "importance required", "malformed"]


def test_clean_dedupes_must_over_nice():
    raw = [
        {"skill_id": "mysql", "level": 3, "importance": "nice", "why": "reports"},
        {"skill_id": "python", "level": 1, "importance": "nice", "why": "scripts"},
        {"skill_id": "MySQL", "level": 2, "importance": "must", "why": "owns the data layer"},
    ]
    reqs, dropped = _role.clean_requirements(raw, "t")
    assert dropped == []
    assert [r["skill_id"] for r in reqs] == ["mysql", "python"]
    assert reqs[0] == {"skill_id": "mysql", "level": 2, "importance": "must",
                       "why": "reports; owns the data layer"}


def test_clean_not_a_list_raises():
    with pytest.raises(ValueError, match="requirements must be a list"):
        _role.clean_requirements({"skill_id": "python"}, "t")


def test_clean_public_coerces():
    out = _role.clean_public({"title": " Engineer ", "description": "Builds things.", "location": "",
                              "sponsorship": "Yes", "clearance": "US Person", "pay": " 35-45 USD/hour "}, "t")
    assert out == {"title": "Engineer", "description": "Builds things.", "location": None,
                   "sponsorship": True, "clearance": "us_person", "pay": "35-45 USD/hour"}
    out = _role.clean_public({"title": "E", "description": "D", "sponsorship": "maybe",
                              "clearance": "top secret"}, "t")
    assert out["sponsorship"] is None
    assert out["clearance"] == "none"
    assert out["pay"] is None
    assert _role.clean_public({"title": "E", "description": "D", "sponsorship": "no"}, "t")["sponsorship"] is False


def test_clean_public_requires_title():
    with pytest.raises(ValueError, match="public.title"):
        _role.clean_public({"title": " ", "description": "D"}, "t")
