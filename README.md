# azure-agent-skills

Curated, machine-readable **skill files** for AI coding agents that build on Azure.

Each skill packages the authoritative guidance from
[Microsoft Learn](https://learn.microsoft.com/azure/) and the Azure
documentation into a small, focused bundle that an agent can load on demand —
so it can build, deploy, and operate Azure resources correctly and securely
without re-deriving best practices from scratch every session.

## Why this repo exists

Coding agents are good at writing code, but they routinely:

- Hallucinate Azure SDK/CLI syntax that doesn't exist in the version installed.
- Skip the *secure-by-default* knobs (managed identity, private endpoints,
  TLS minimums, soft-delete, RBAC over keys, etc.).
- Pick the wrong service tier or pricing plan for the workload.
- Wire resources together in ways that work in a demo but fail under
  production conditions (region pairs, quotas, throttling, retry policy).

Skills are short, opinionated documents that pin the agent to known-good
patterns and link to the canonical Microsoft Learn pages for deeper reading.

## Repository layout

```
.
├── skills/
│   ├── identity-and-access/    # Auth, RBAC, managed identity, Key Vault
│   ├── compute/                # App Service, Functions, Container Apps
│   ├── data/                   # Storage, Cosmos DB, PostgreSQL
│   ├── networking/             # Private endpoints, Front Door, VNets
│   ├── integration/            # Service Bus, Event Grid, Event Hubs
│   ├── ai-and-ml/              # Azure OpenAI, AI Search
│   ├── observability/          # Monitor, App Insights, diagnostics
│   ├── devops/                 # GitHub Actions OIDC, Azure DevOps
│   ├── infrastructure-as-code/ # Bicep, Terraform AzAPI
│   ├── governance/             # Naming, tagging, Policy
│   └── <category>/<skill-name>/
│       ├── SKILL.md            # Required: agent-facing instructions + frontmatter
│       ├── references/         # Optional: deeper docs the agent can pull in
│       └── scripts/            # Optional: helper scripts (Bicep, az CLI, etc.)
├── docs/
│   └── skill-format.md         # Spec for the SKILL.md format
├── scripts/
│   ├── generate_skill.py       # Generates a skill from MS Learn URLs (--fetch supported)
│   └── validate_skills.py      # Lints SKILL.md frontmatter and structure (recursive)
├── .github/workflows/
│   └── validate.yml            # CI: runs validator on every push and PR
├── CONTRIBUTING.md
├── LICENSE
└── README.md
```

The categories match the verbs an agent uses on a real build:
*"How do I auth this?"* → `identity-and-access`. *"Where do I run my code?"*
→ `compute`. *"How do I expose this?"* → `networking`. And so on.

## Skill format (TL;DR)

A skill is a directory containing a `SKILL.md` file with YAML frontmatter
describing what the skill does and when an agent should load it. See
[`docs/skill-format.md`](docs/skill-format.md) for the full spec.

```markdown
---
name: azure-storage-account
description: Create and configure Azure Storage accounts with secure defaults
  (TLS 1.2+, public access disabled, managed identity, soft delete).
version: 0.1.0
azure_services:
  - Microsoft.Storage/storageAccounts
sources:
  - https://learn.microsoft.com/azure/storage/common/storage-account-overview
---

# Azure Storage Account

Use this skill when the user asks to create, provision, or configure an
Azure Storage account...
```

## Using a skill

The skill files in this repo are framework-agnostic Markdown. They can be
consumed by:

- The **GitHub Copilot CLI** via its extensions/skills mechanism.
- **Claude Code** / Anthropic-style agent skills (drop the directory into
  the agent's skills path).
- Any custom agent that loads Markdown context on demand.

## Generating skills from Microsoft Learn

The `scripts/generate_skill.py` script (work in progress) takes one or more
Microsoft Learn URLs and produces a draft `SKILL.md` you can review and
refine. It does *not* publish skills automatically — every skill in this
repo is human-reviewed for accuracy and security guidance before merging.

## Status

Early scaffold. Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
