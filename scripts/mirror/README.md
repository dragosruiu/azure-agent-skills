# azure-agent-skills

Curated, machine-readable **skill files** for AI coding agents that build on
Azure. Each skill is a small, focused Markdown bundle distilled from
[Microsoft Learn](https://learn.microsoft.com/azure/) and pinned to a
*secure-by-default* posture (managed identity over keys, public access off,
TLS 1.2+, RBAC over connection strings, private endpoints where applicable).

> **This repository is a read-only mirror** of the published skill catalog.
> Authoring, the draft generator, the validator, and CI live upstream at
> <https://github.com/dragosruiu/azure-agent-skills>. Issues and PRs go there.

## Why use these

Coding agents are good at writing code, but on Azure they routinely:

- Hallucinate Azure SDK / `az` CLI syntax that doesn't exist in the version
  installed.
- Skip the secure-by-default knobs (managed identity, private endpoints, TLS
  minimums, soft-delete, RBAC over keys, `disableLocalAuth`, etc.).
- Pick the wrong service tier or pricing plan for the workload.
- Wire resources together in ways that work in a demo but fail under
  production conditions (region pairs, quotas, throttling, retry policy).

Each `SKILL.md` is a short, opinionated document that pins the agent to
known-good patterns and links back to the canonical Microsoft Learn pages
for deeper reading. Every non-obvious claim is sourced.

## Repository layout

```
.
├── skills/
│   ├── README.md                 # Catalog index, grouped by category
│   ├── identity-and-access/      # "How do I auth this without secrets?"
│   ├── compute/                  # "Where do I run my code?"
│   ├── data/                     # "Where do I store my state?"
│   ├── networking/               # "How do I expose / isolate this?"
│   ├── integration/              # "How do services talk to each other?"
│   ├── ai-and-ml/                # "How do I add AI to this app?"
│   ├── observability/            # "How do I see what's happening?"
│   ├── devops/                   # "How do I deploy this from CI?"
│   ├── infrastructure-as-code/   # "How do I declare this declaratively?"
│   ├── governance/               # "What do I name / tag / scope this with?"
│   ├── security/                 # "How do I detect threats / check posture?"
│   └── migration/                # "How do I move workloads into Azure?"
└── docs/
    └── skill-format.md           # SKILL.md frontmatter + body spec
```

The categories match the verbs an agent uses on a real build, not Azure's
product taxonomy. Browse the full catalog in
[`skills/README.md`](skills/README.md).

## What's in a skill

Every skill is a directory `skills/<category>/<skill-name>/` containing:

- `SKILL.md` — required. YAML frontmatter (name, description, version,
  `azure_services`, `sources`, `last_reviewed`) followed by Markdown sections:
  *When to use* / *When NOT to use* / *Prerequisites* / **Secure defaults** /
  *Recipe* (runnable `az` / Bicep / Terraform / SDK snippets) / *Common
  failures* / *References*.
- `references/` — optional longer-form docs the agent can pull on demand.
- `scripts/` — optional helper scripts (Bicep modules, az CLI snippets, etc.)
  that the recipe references.

The full schema is documented in [`docs/skill-format.md`](docs/skill-format.md).

Example frontmatter:

```yaml
---
name: azure-storage-account
description: >
  Provision Azure Storage accounts with secure defaults — TLS 1.2+, public
  access disabled, managed identity, infrastructure encryption, soft delete.
version: 0.1.0
azure_services:
  - Microsoft.Storage/storageAccounts
sources:
  - https://learn.microsoft.com/azure/storage/common/storage-account-overview
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2023-05-01"
last_reviewed: 2026-05-11
---
```

## Using these skills

The skill files are framework-agnostic Markdown — any agent that loads
context on demand can consume them. Common integrations:

### GitHub Copilot CLI / coding agent

Reference the skill content from a `copilot-instructions.md` or load it
directly into the agent's context when working on Azure tasks. Skills are
keyed by the questions an agent asks ("how do I auth this?", "where do I
run my code?") so you can route by intent.

### Claude / Anthropic-style agent skills

Drop the relevant `skills/<category>/<skill-name>/` directory into the
agent's skills path. The frontmatter `description:` field is what the
agent matches against to decide when to load the skill.

### Custom agents

Clone the repo (or vendor specific skill directories), then load the
relevant `SKILL.md` into the model context when the user's request matches
the skill's `## When to use this skill` triggers. The `sources:`
frontmatter list lets you cite back to Microsoft Learn in the agent's
output.

### Cloning

```bash
# Azure DevOps (this mirror)
git clone https://securityassurance@dev.azure.com/securityassurance/TeamCentral/_git/azure-agent-skills

# Upstream (GitHub)
git clone https://github.com/dragosruiu/azure-agent-skills.git
```

## Catalog index

See [`skills/README.md`](skills/README.md) for the full list of skills with
one-line summaries, grouped by category. As of the latest mirror, the
catalog spans 12 categories covering identity, compute, data, networking,
integration, AI/ML, observability, DevOps, IaC, governance, security, and
migration — with new skills added upstream over time.

## Versioning and freshness

- Each skill carries its own semver `version:` — bumped when the *guidance*
  changes (new recommended SDK / API version, new secure default), not on
  typo fixes.
- Each skill carries a `last_reviewed:` ISO date. Anything older than 12
  months is flagged by the upstream validator as potentially stale.
- The `validated_with:` block (when present) records the `az_cli` and
  `api_version` the recipe was last validated against.

## License

[MIT](LICENSE) — same as the upstream repo.
