# scripts/

Tooling for authoring and validating skills.

## `generate_skill.py`

Drafts a new `skills/<name>/SKILL.md` from one or more
[Microsoft Learn](https://learn.microsoft.com) URLs.

```bash
python scripts/generate_skill.py \
    --name azure-key-vault \
    --service Microsoft.KeyVault/vaults \
    --source https://learn.microsoft.com/azure/key-vault/general/overview \
    --source https://learn.microsoft.com/azure/key-vault/general/security-features
```

The output is a *draft* with stubbed sections. A human MUST review and
fill in the `Secure defaults`, `Recipe`, and `Common failures` sections
before merging. The generator deliberately does not invent secure-default
values — that's the human's job.

## `validate_skills.py`

Lints every `skills/*/SKILL.md`. Run before opening a PR.

```bash
python scripts/validate_skills.py
```

Exits non-zero if any skill has errors. Warnings (e.g. stale
`last_reviewed`) are reported but don't fail the run.

Both scripts are pure-stdlib Python 3.10+ and have no install step.
