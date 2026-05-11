#!/usr/bin/env python3
"""
validate_skills.py — Lint every SKILL.md under skills/.

Checks (errors fail the run, warnings are reported):
  E1  SKILL.md must exist for every directory under skills/.
  E2  Frontmatter must be valid YAML and contain required keys.
  E3  Frontmatter `name` must equal the directory name.
  E4  `name` must be lowercase kebab-case.
  E5  `version` must be valid semver (major.minor.patch).
  E6  At least one `sources:` URL on learn.microsoft.com or docs.microsoft.com.
  E7  Body must include a "## Secure defaults" heading.
  E8  `last_reviewed` must be a valid ISO date.

  W1  `last_reviewed` older than 365 days.
  W2  Body shorter than 60 lines (probably under-specified).
  W3  No `## Common failures` section.

This script has no third-party dependencies — it ships its own minimal
YAML frontmatter parser so it works on a clean Python install.
"""

from __future__ import annotations

import datetime as dt
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"
LEARN_HOSTS = {"learn.microsoft.com", "docs.microsoft.com"}
REQUIRED_KEYS = {
    "name",
    "description",
    "version",
    "azure_services",
    "sources",
    "last_reviewed",
}
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.\-]+)?$")
KEBAB_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def err(self, code: str, path: Path, msg: str) -> None:
        self.errors.append(f"{code} {path.relative_to(REPO_ROOT)}: {msg}")

    def warn(self, code: str, path: Path, msg: str) -> None:
        self.warnings.append(f"{code} {path.relative_to(REPO_ROOT)}: {msg}")


def split_frontmatter(text: str) -> tuple[str | None, str]:
    """Return (frontmatter_text, body). frontmatter_text is None if missing."""
    if not (text.startswith("---\n") or text.startswith("---\r\n")):
        return None, text
    m = re.search(r"\n---\s*\n", text)
    if not m:
        return None, text
    fm = text[4 : m.start()]
    body = text[m.end() :]
    return fm, body


def parse_minimal_yaml(text: str) -> dict:
    """
    Minimal YAML parser supporting the subset we use in SKILL.md frontmatter:
      - top-level scalar:    key: value
      - top-level scalar with folded block:  key: > / key: |  + indented lines
      - top-level list of scalars:    key:\\n  - item\\n  - item
      - top-level mapping of scalars: key:\\n  subkey: value
    """
    out: dict = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        if not raw.strip() or raw.lstrip().startswith("#"):
            i += 1
            continue
        if raw.startswith(" "):
            raise ValueError(f"unexpected indentation: {raw!r}")
        if ":" not in raw:
            raise ValueError(f"expected 'key: value' on line: {raw!r}")
        key, _, rest = raw.partition(":")
        key = key.strip()
        rest = rest.strip()

        if rest in (">", "|"):
            i += 1
            collected = []
            while i < len(lines) and (lines[i].startswith(" ") or not lines[i].strip()):
                collected.append(lines[i].strip())
                i += 1
            out[key] = " ".join(s for s in collected if s)
            continue

        if rest == "":
            i += 1
            child_lines = []
            while i < len(lines) and (lines[i].startswith(" ") or not lines[i].strip()):
                child_lines.append(lines[i])
                i += 1
            if not child_lines:
                out[key] = None
                continue
            stripped = [ln for ln in child_lines if ln.strip()]
            if stripped and stripped[0].lstrip().startswith("- "):
                items = []
                for ln in stripped:
                    s = ln.strip()
                    if not s.startswith("- "):
                        raise ValueError(f"mixed list/mapping under {key!r}")
                    items.append(s[2:].strip())
                out[key] = items
            else:
                sub: dict = {}
                for ln in stripped:
                    s = ln.strip()
                    if ":" not in s:
                        raise ValueError(f"expected mapping under {key!r}")
                    k2, _, v2 = s.partition(":")
                    sub[k2.strip()] = _scalar(v2.strip())
                out[key] = sub
            continue

        out[key] = _scalar(rest)
        i += 1
    return out


def _scalar(raw: str):
    if raw == "" or raw.lower() == "null" or raw == "~":
        return None
    if raw.lower() == "true":
        return True
    if raw.lower() == "false":
        return False
    if (raw.startswith('"') and raw.endswith('"')) or (
        raw.startswith("'") and raw.endswith("'")
    ):
        return raw[1:-1]
    return raw


def validate_skill(skill_dir: Path, report: Report) -> None:
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        report.err("E1", skill_dir, "missing SKILL.md")
        return

    text = skill_md.read_text(encoding="utf-8")
    fm_text, body = split_frontmatter(text)
    if fm_text is None:
        report.err("E2", skill_md, "missing YAML frontmatter")
        return

    try:
        fm = parse_minimal_yaml(fm_text)
    except ValueError as e:
        report.err("E2", skill_md, f"invalid frontmatter: {e}")
        return

    missing = REQUIRED_KEYS - set(fm)
    if missing:
        report.err(
            "E2",
            skill_md,
            f"missing required keys: {', '.join(sorted(missing))}",
        )

    name = fm.get("name")
    if name and name != skill_dir.name:
        report.err(
            "E3",
            skill_md,
            f"frontmatter name {name!r} != directory name {skill_dir.name!r}",
        )
    if name and not KEBAB_RE.match(str(name)):
        report.err("E4", skill_md, f"name {name!r} is not lowercase kebab-case")

    version = fm.get("version")
    if version and not SEMVER_RE.match(str(version)):
        report.err("E5", skill_md, f"version {version!r} is not valid semver")

    sources = fm.get("sources") or []
    if not isinstance(sources, list) or not sources:
        report.err("E6", skill_md, "sources: must be a non-empty list")
    else:
        if not any(urlparse(s).netloc in LEARN_HOSTS for s in sources):
            report.err(
                "E6",
                skill_md,
                f"at least one source must be on {sorted(LEARN_HOSTS)}",
            )

    if "## Secure defaults" not in body:
        report.err("E7", skill_md, "body missing '## Secure defaults' section")

    last_reviewed = fm.get("last_reviewed")
    if last_reviewed:
        try:
            date = dt.date.fromisoformat(str(last_reviewed))
            age = (dt.date.today() - date).days
            if age > 365:
                report.warn(
                    "W1",
                    skill_md,
                    f"last_reviewed is {age} days old (>365)",
                )
        except ValueError:
            report.err(
                "E8", skill_md, f"last_reviewed {last_reviewed!r} is not ISO date"
            )

    if body.count("\n") < 60:
        report.warn("W2", skill_md, "body is shorter than 60 lines")

    if "## Common failures" not in body:
        report.warn("W3", skill_md, "no '## Common failures' section")


def main() -> int:
    if not SKILLS_DIR.exists():
        print(f"no skills/ directory at {SKILLS_DIR}", file=sys.stderr)
        return 0

    report = Report()
    # A skill is any directory that contains a SKILL.md. Categories (dirs
    # without SKILL.md) are silently skipped — only their child skills count.
    skill_md_files = sorted(SKILLS_DIR.rglob("SKILL.md"))
    skill_dirs = [p.parent for p in skill_md_files]
    if not skill_dirs:
        print("no skills found")
        return 0

    for d in skill_dirs:
        validate_skill(d, report)

    for w in report.warnings:
        print(f"warning: {w}")
    for e in report.errors:
        print(f"error:   {e}", file=sys.stderr)

    print(
        f"\n{len(skill_dirs)} skill(s) checked - "
        f"{len(report.errors)} error(s), {len(report.warnings)} warning(s)"
    )
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
