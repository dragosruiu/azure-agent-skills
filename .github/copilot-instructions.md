# Copilot instructions for azure-agent-skills

This repository is a curated catalog of **agent-facing skill files** for building
on Azure. There is no application to compile and no runtime — the "product" is
the Markdown content itself. Optimize for *content correctness and security
guidance*, not for code velocity.

## What a "skill" is here

A skill is a directory `skills/<category>/<skill-name>/` containing a required
`SKILL.md` file (YAML frontmatter + Markdown body) and optional `references/`
and `scripts/` subdirectories. The full spec lives in
[`docs/skill-format.md`](../docs/skill-format.md).

The directory name MUST equal the frontmatter `name:` field, MUST be lowercase
kebab-case, and the category folder is one of those listed in
[`skills/README.md`](../skills/README.md) (`identity-and-access`, `compute`,
`data`, `networking`, `integration`, `ai-and-ml`, `observability`, `devops`,
`infrastructure-as-code`, `governance`, `security`, `migration`).

## Validate / "build" / test

There is no compiler, package manager, or test framework. The only check is the
linter, which is also what CI runs (see `.github/workflows/validate.yml`):

```bash
python scripts/validate_skills.py          # lint every skills/**/SKILL.md
```

Both scripts target **Python 3.10+ stdlib only** — do not add third-party
dependencies. `validate_skills.py` ships its own minimal YAML frontmatter
parser; if you change frontmatter shape, update the parser in lockstep.

To "test a single skill", just point the validator at the tree and grep its
output for the path, e.g.:

```bash
python scripts/validate_skills.py 2>&1 | grep skills/data/azure-storage-account
```

CI also smoke-tests the generator by drafting a throwaway skill from a Learn
URL and deleting it — keep `generate_skill.py` runnable with no network access
required for the drafting step (it only fetches when `--fetch` is passed).

### Drafting a new skill

```bash
python scripts/generate_skill.py \
    --name azure-key-vault \
    --service Microsoft.KeyVault/vaults \
    --source https://learn.microsoft.com/azure/key-vault/general/overview
```

The generator emits to `skills/<name>/` (flat) — **manually move the resulting
directory into the correct category** (`mv skills/azure-key-vault skills/identity-and-access/`)
before committing. The generator deliberately stubs `Secure defaults`, `Recipe`,
and `Common failures`; a human MUST fill these in.

## Required structure of every SKILL.md

Frontmatter keys enforced by the validator (E2/E3/E4/E5/E6/E8):

- `name` — must equal the directory name; lowercase kebab-case.
- `description` — 1–2 sentences (folded scalar `>` is fine).
- `version` — semver (`major.minor.patch`). Bump when *guidance* changes
  (recommended SDK version, API version, default setting). Typo fixes do not
  bump.
- `azure_services` — list of ARM resource provider/types
  (`Microsoft.Storage/storageAccounts`, not friendly names).
- `sources` — list of URLs; **at least one MUST be on `learn.microsoft.com` or
  `docs.microsoft.com`**. This is enforced.
- `last_reviewed` — ISO date. Older than 365 days produces a warning (W1).
- Optional: `tags`, `validated_with` (`az_cli`, `api_version`).

Body must contain a `## Secure defaults` heading (E7). It SHOULD also include,
in this order: `## When to use this skill`, `## When NOT to use this skill`,
`## Prerequisites`, `## Secure defaults`, `## Recipe`, `## Common failures`,
`## References`. Missing `## Common failures` is W3 (warning, not error).

Aim for **150–600 lines**. Anything longer should be factored into
`references/*.md` and linked from the body. Body shorter than 60 lines triggers
W2.

## Editorial conventions specific to this repo

These are not generic "good writing" tips — they are repo norms enforced in PR
review:

- **Secure by default, no exceptions.** Every recipe must use managed identity
  over keys, disable public network access where the service supports it, pin
  TLS to 1.2+, and prefer RBAC over connection strings / SAS / access keys.
  See `CONTRIBUTING.md` for the full bar.
- **Cite Microsoft Learn for every non-obvious claim.** If a security default
  or behavior cannot be linked to a `learn.microsoft.com` page (or an ARM
  schema), it does not belong in the skill. No unsourced claims.
- **Concrete commands, not prose.** Skills are consumed by agents — give them
  runnable `az` / `bicep` / `terraform` / SDK snippets, not paragraphs.
- **Pin versions.** Use the `validated_with` frontmatter block when you've
  validated against a specific `az_cli` / `api_version`, and reference those
  versions in the body's prerequisites.
- **One service per skill.** Don't bundle. "Provision a Storage account
  securely" is one skill; "Storage account + private endpoint + diagnostic
  settings" is three skills that link to each other.
- **No verbatim copying from Learn.** Cite and summarize.
- **Failure-aware.** `## Common failures` should be a table of
  error → cause → fix for the most common deployment failures.

## Categories are verbs, not taxonomy

The category split mirrors the questions an agent asks during a build
("How do I auth this?" → `identity-and-access`; "Where do I run my code?" →
`compute`). When adding a skill, pick the category that matches the *agent
workflow* it unblocks. If unclear, drop it in the closest fit and call it out
in the PR — the validator does not enforce category names.

## Things that look like code but aren't

- `scripts/` at the repo root holds the validator and generator. **Subfolder**
  `skills/<category>/<skill>/scripts/` is for *helper scripts shipped with a
  skill* (Bicep modules, az CLI snippets, etc.) — different purpose, different
  audience.
- There is no application source tree. PRs that add a `package.json`,
  `pyproject.toml`, build system, or test framework are almost certainly going
  in the wrong direction — discuss in an issue first.
