#!/usr/bin/env python3
"""
generate_skill.py — Draft a SKILL.md from one or more Microsoft Learn URLs.

This is a *productivity tool*, not an authority. Every skill in
azure-agent-skills/ is human-reviewed before being merged.

Usage:
    python scripts/generate_skill.py \
        --name azure-key-vault \
        --service Microsoft.KeyVault/vaults \
        --source https://learn.microsoft.com/azure/key-vault/general/overview \
        --source https://learn.microsoft.com/azure/key-vault/general/security-features

What it does:
    1. Validates the supplied --source URLs.
    2. Emits a draft skills/<name>/SKILL.md with frontmatter pre-filled and
       body sections stubbed out (When to use, Secure defaults, Recipe,
       Common failures, References).
    3. Refuses to overwrite an existing SKILL.md unless --force is passed.

Limitations (intentional):
    - Does NOT publish, commit, or open PRs.
    - Output is a *draft*. The "Secure defaults" and "Common failures"
      sections must be filled in by a human who has actually validated the
      guidance against the current Azure CLI / API version.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
import textwrap
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"

LEARN_HOSTS = {"learn.microsoft.com", "docs.microsoft.com"}

SKILL_TEMPLATE = """\
---
name: {name}
description: >
  TODO — one or two sentences describing what this skill does and what
  secure defaults it enforces.
version: 0.1.0
azure_services:
{services_yaml}
tags:
  - TODO
sources:
{sources_yaml}
validated_with:
  az_cli: ">=2.60.0"
  api_version: "TODO"
last_reviewed: {today}
---

# {title}

## When to use this skill

- TODO

## When NOT to use this skill

- TODO

## Prerequisites

- Azure CLI `>= 2.60.0` (`az --version`).
- Logged in: `az login`.
- Subscription selected: `az account set --subscription <id>`.

## Secure defaults

> Fill this in from the Microsoft Learn security baseline pages for this
> service. Do not ship a skill without this section.

| Setting | Value | Why |
| --- | --- | --- |
| TODO | TODO | TODO |

## Recipe — Azure CLI

```bash
# TODO
```

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| TODO | TODO | TODO |

## References

{references_md}
"""


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def validate_source(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise SystemExit(f"--source must be http(s): {url}")
    if parsed.netloc not in LEARN_HOSTS:
        raise SystemExit(
            f"--source must be on {sorted(LEARN_HOSTS)}; got {parsed.netloc}"
        )
    return url


def title_from_name(name: str) -> str:
    return " ".join(part.capitalize() for part in name.split("-"))


def render(name: str, services: list[str], sources: list[str]) -> str:
    today = dt.date.today().isoformat()
    services_yaml = "\n".join(f"  - {s}" for s in services) or "  - TODO"
    sources_yaml = "\n".join(f"  - {s}" for s in sources)
    references_md = "\n".join(f"- [{s}]({s})" for s in sources)
    return SKILL_TEMPLATE.format(
        name=name,
        title=title_from_name(name),
        today=today,
        services_yaml=services_yaml,
        sources_yaml=sources_yaml,
        references_md=references_md,
    )


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--name", required=True, help="kebab-case skill name")
    p.add_argument(
        "--service",
        action="append",
        default=[],
        metavar="ARM_TYPE",
        help="ARM resource type, e.g. Microsoft.KeyVault/vaults (repeatable)",
    )
    p.add_argument(
        "--source",
        action="append",
        required=True,
        metavar="URL",
        help="learn.microsoft.com URL (repeatable, at least one required)",
    )
    p.add_argument(
        "--force", action="store_true", help="overwrite existing SKILL.md"
    )
    args = p.parse_args()

    name = slugify(args.name)
    if name != args.name:
        print(f"note: normalized --name to {name!r}", file=sys.stderr)

    sources = [validate_source(s) for s in args.source]

    skill_dir = SKILLS_DIR / name
    skill_md = skill_dir / "SKILL.md"
    if skill_md.exists() and not args.force:
        print(
            f"error: {skill_md.relative_to(REPO_ROOT)} already exists "
            "(pass --force to overwrite)",
            file=sys.stderr,
        )
        return 2

    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_md.write_text(render(name, args.service, sources), encoding="utf-8")

    print(f"wrote {skill_md.relative_to(REPO_ROOT)}")
    print(
        textwrap.dedent(
            """\

            Next steps:
              1. Open the file and fill in TODOs.
              2. Validate against current Azure CLI / API versions.
              3. Run: python scripts/validate_skills.py
              4. Commit and open a PR.
            """
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
