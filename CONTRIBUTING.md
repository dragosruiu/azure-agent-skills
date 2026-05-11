# Contributing to azure-agent-skills

Thanks for your interest. Skills in this repo are short, opinionated, and
human-reviewed. Quality matters more than quantity — one accurate skill is
worth ten vague ones.

## Adding a new skill

1. **Pick a focused scope.** A skill should answer a single question well
   ("How do I provision an Azure Storage account securely?"), not ten
   ("How do I do everything with storage?").
2. **Create the directory:** `skills/<kebab-case-name>/SKILL.md`.
3. **Follow the format spec:** see [`docs/skill-format.md`](docs/skill-format.md).
4. **Cite Microsoft Learn.** Every non-obvious claim should be backed by a
   `learn.microsoft.com` URL listed under `sources:` in the frontmatter.
5. **Run the validator:** `python scripts/validate_skills.py`.
6. **Open a PR.** Include in the description:
   - The agent workflow you used the skill for.
   - Which Microsoft Learn pages you drew from.
   - Any safety/security defaults you encoded and why.

## What makes a good skill

- **Secure by default.** Prefer managed identity over keys. Disable public
  network access where possible. Pin TLS to 1.2+. Use private endpoints
  when applicable.
- **Versioned guidance.** Note the API version, SDK version, or `az` CLI
  version your guidance was validated against.
- **Concrete, not aspirational.** Give the agent runnable commands, not
  paragraphs of prose.
- **Failure-aware.** Include the most common deployment failures and how
  to recognize them.

## What to avoid

- Marketing language. Skills are for agents, not customers.
- Copying Microsoft Learn pages verbatim. Cite and summarize; don't mirror.
- Unsourced security claims. If you can't link it to a Microsoft Learn page
  or an Azure SRP/ARM schema, it doesn't belong.
- Bundling unrelated services into one skill.

## Generating drafts

`scripts/generate_skill.py` can produce a starting draft from one or more
Learn URLs. Drafts always require human review before being merged — the
generator is a productivity tool, not an authority.

## Code of conduct

Be kind, be precise, be honest about what you don't know.
