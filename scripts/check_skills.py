"""Validate every skills/*/SKILL.md for OpenClaw. Stdlib only.

Checks: frontmatter present, name == directory name and ^[a-z0-9-]+$,
description one line and under 160 chars, body non-empty, no em dashes,
no Slack token patterns. Exit 1 on any failure.
Usage: python3 scripts/check_skills.py
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
NAME_RE = re.compile(r"^[a-z0-9-]+$")
TOKEN_RE = re.compile(r"xox[a-z]-|xapp-\d")
EM_DASH = chr(0x2014)
MAX_DESC = 160


def parse_frontmatter(text):
    """Return (fields, extra_lines, body) or None if there is no frontmatter."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for end in range(1, len(lines)):
        if lines[end].strip() == "---":
            break
    else:
        return None
    fields, extra = {}, []
    for line in lines[1:end]:
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if m:
            fields[m.group(1)] = m.group(2).strip()
        elif line.strip():
            extra.append(line)
    return fields, extra, "\n".join(lines[end + 1:])


def check(path):
    errors = []
    text = path.read_text(encoding="utf-8")
    dirname = path.parent.name

    for i, line in enumerate(text.splitlines(), 1):
        if EM_DASH in line:
            errors.append(f"line {i}: em dash")
        if TOKEN_RE.search(line):
            errors.append(f"line {i}: looks like a Slack token (value not printed)")

    parsed = parse_frontmatter(text)
    if parsed is None:
        errors.append("no frontmatter (file must start with --- ... ---)")
        return errors
    fields, extra, body = parsed

    # Boundary: SKILL.md is hand-written input, missing keys are reported below
    name =fields.get("name", "").strip("\"'")
    if not name:
        errors.append("frontmatter: missing name")
    elif not NAME_RE.match(name):
        errors.append(f"frontmatter: name {name!r} must match ^[a-z0-9-]+$")
    elif name != dirname:
        errors.append(f"frontmatter: name {name!r} != directory {dirname!r}")

    desc = fields.get("description", "").strip("\"'")
    if not desc:
        errors.append("frontmatter: missing description")
    elif desc in (">", "|", ">-", "|-") or extra:
        errors.append("frontmatter: description must be a single line")
    elif len(desc) >= MAX_DESC:
        errors.append(f"frontmatter: description is {len(desc)} chars, must be under {MAX_DESC}")

    if not body.strip():
        errors.append("body is empty")
    return errors


def main():
    paths = sorted((REPO / "skills").glob("*/SKILL.md"))
    if not paths:
        print(f"FAIL  no skills/*/SKILL.md under {REPO}")
        return 1
    failed = 0
    for p in paths:
        rel = p.relative_to(REPO).as_posix()
        errors = check(p)
        if errors:
            failed += 1
            for e in errors:
                print(f"FAIL  {rel}: {e}")
        else:
            print(f"PASS  {rel}")
    print(f"== check_skills: {len(paths) - failed} PASS, {failed} FAIL ==")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
