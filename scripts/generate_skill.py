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
import html
import re
import sys
import textwrap
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"

LEARN_HOSTS = {"learn.microsoft.com", "docs.microsoft.com"}
USER_AGENT = "azure-agent-skills/0.1 (+https://github.com/dragosruiu/azure-agent-skills)"
FETCH_TIMEOUT = 20  # seconds

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
{fetched_appendix}"""


def fetch_learn_page(url: str) -> str:
    """Fetch a Learn page and return a stripped-down text excerpt.

    Returns "" on any error (network, HTTP, encoding) — the generator
    always succeeds even if fetching fails."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            ctype = resp.headers.get("Content-Type", "")
            if "html" not in ctype.lower():
                return ""
            raw = resp.read(2_000_000)  # 2 MB cap
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        print(f"  warn: fetch failed for {url}: {e}", file=sys.stderr)
        return ""

    text = raw.decode("utf-8", errors="replace")
    return summarize_learn_html(text)


def summarize_learn_html(text: str) -> str:
    """Extract the page title, h2/h3 headings, and code blocks from raw HTML.

    Intentionally minimal; the goal is to give a human author a quick
    skim of the page structure, not to mirror its content."""
    title_m = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    title = html.unescape(title_m.group(1).strip()) if title_m else ""

    headings: list[str] = []
    for m in re.finditer(r"<h([23])[^>]*>(.*?)</h\1>", text, re.I | re.S):
        h = re.sub(r"<[^>]+>", "", m.group(2))
        h = html.unescape(h).strip()
        if h:
            headings.append(f"{'  ' if m.group(1) == '3' else ''}- {h}")

    code_snippets: list[str] = []
    for m in re.finditer(
        r"<code[^>]*class=\"[^\"]*lang-(?P<lang>[a-z0-9]+)[^\"]*\"[^>]*>(?P<body>.*?)</code>",
        text,
        re.I | re.S,
    ):
        body = re.sub(r"<[^>]+>", "", m.group("body"))
        body = html.unescape(body).strip()
        if 20 < len(body) < 1500:
            code_snippets.append(f"```{m.group('lang')}\n{body}\n```")
        if len(code_snippets) >= 3:
            break

    parts: list[str] = []
    if title:
        parts.append(f"**Page title:** {title}")
    if headings:
        parts.append("**Headings:**\n" + "\n".join(headings[:30]))
    if code_snippets:
        parts.append("**First few code blocks:**\n\n" + "\n\n".join(code_snippets))
    return "\n\n".join(parts)


def build_fetched_appendix(sources: list[str]) -> str:
    """Build an appendix block with fetched-page summaries, one per source."""
    chunks: list[str] = []
    for url in sources:
        print(f"  fetching {url}", file=sys.stderr)
        body = fetch_learn_page(url)
        if not body:
            continue
        chunks.append(f"### {url}\n\n{body}")
    if not chunks:
        return ""
    return (
        "\n\n<!--\n"
        "Generator-fetched excerpts from the source URLs above. Use these\n"
        "to fill in the body sections, then DELETE this comment block.\n"
        "Do not ship the skill with this appendix in place.\n"
        "-->\n\n"
        "## Generator notes (delete before merge)\n\n"
        + "\n\n".join(chunks)
    )


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


def render(
    name: str, services: list[str], sources: list[str], fetch: bool
) -> str:
    today = dt.date.today().isoformat()
    services_yaml = "\n".join(f"  - {s}" for s in services) or "  - TODO"
    sources_yaml = "\n".join(f"  - {s}" for s in sources)
    references_md = "\n".join(f"- [{s}]({s})" for s in sources)
    fetched_appendix = build_fetched_appendix(sources) if fetch else ""
    return SKILL_TEMPLATE.format(
        name=name,
        title=title_from_name(name),
        today=today,
        services_yaml=services_yaml,
        sources_yaml=sources_yaml,
        references_md=references_md,
        fetched_appendix=("\n\n" + fetched_appendix) if fetched_appendix else "",
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
    p.add_argument(
        "--fetch",
        action="store_true",
        help="fetch each --source URL and append page-structure notes "
        "(headings, code blocks) inside an HTML comment block to help "
        "the human author. Network access required.",
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
    skill_md.write_text(
        render(name, args.service, sources, fetch=args.fetch), encoding="utf-8"
    )

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
