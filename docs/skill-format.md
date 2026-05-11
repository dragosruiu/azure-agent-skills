# SKILL.md format specification

A skill is a directory under `skills/` containing one required file —
`SKILL.md` — and any optional supporting files.

## File layout

```
skills/<skill-name>/
├── SKILL.md              # Required
├── references/           # Optional: longer-form docs the agent can pull on demand
│   └── *.md
└── scripts/              # Optional: helper scripts referenced by SKILL.md
    └── *.{sh,py,bicep,...}
```

`<skill-name>` MUST be lowercase kebab-case and MUST match the `name:` field
in the frontmatter.

## SKILL.md structure

A `SKILL.md` is a Markdown file with a required YAML frontmatter block
followed by free-form Markdown body content.

### Frontmatter (required)

```yaml
---
name: azure-storage-account                       # required, kebab-case, matches dir
description: >                                    # required, 1–2 sentences
  Provision Azure Storage accounts with secure defaults (TLS 1.2+,
  public access disabled, managed identity, soft delete).
version: 0.1.0                                    # required, semver
azure_services:                                   # required, ARM resource provider/type
  - Microsoft.Storage/storageAccounts
tags:                                             # optional
  - storage
  - security-baseline
sources:                                          # required, at least one learn.microsoft.com URL
  - https://learn.microsoft.com/azure/storage/common/storage-account-overview
  - https://learn.microsoft.com/azure/storage/common/storage-account-create
validated_with:                                   # optional but recommended
  az_cli: ">=2.60.0"
  api_version: "2023-05-01"
last_reviewed: 2026-05-11                         # required, ISO date of last human review
---
```

### Body sections

The body is free-form Markdown but SHOULD include the following sections,
in this order, when applicable:

1. **`# <Human-readable title>`** — first heading.
2. **`## When to use this skill`** — bullet list of trigger situations.
3. **`## When NOT to use this skill`** — explicit non-goals.
4. **`## Prerequisites`** — required tooling, permissions, subscriptions.
5. **`## Secure defaults`** — non-negotiable settings the agent must apply.
6. **`## Recipe`** — runnable commands (Azure CLI, Bicep, Terraform, SDK).
7. **`## Common failures`** — error → cause → fix table.
8. **`## References`** — links matching the `sources:` frontmatter.

## Length guidance

A `SKILL.md` should be readable in under 2 minutes. Aim for **150–600
lines**. If you need more, factor long content into `references/*.md` and
link to it from the body.

## Validation

`scripts/validate_skills.py` checks:

- Directory name matches frontmatter `name`.
- All required frontmatter fields are present and well-typed.
- `sources:` URLs are on `learn.microsoft.com` or `docs.microsoft.com`.
- `last_reviewed` is within the last 12 months (warning, not error).
- Body contains at least one `## Secure defaults` heading.

Run it before opening a PR:

```bash
python scripts/validate_skills.py
```

## Versioning

Bump `version:` whenever the *guidance* changes meaningfully. Typo fixes
don't require a bump; changing a recommended SDK version, API version, or
default setting does.
