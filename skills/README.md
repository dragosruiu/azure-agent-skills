# skills/

One directory per skill. Each directory contains a `SKILL.md` (required)
and may contain `references/` and `scripts/` subdirectories.

See [`../docs/skill-format.md`](../docs/skill-format.md) for the full spec
and [`../CONTRIBUTING.md`](../CONTRIBUTING.md) for the contribution
workflow.

## Current skills

| Skill | Description |
| --- | --- |
| [`azure-storage-account`](azure-storage-account/SKILL.md) | Provision Azure Storage accounts with secure defaults. |

## Planned skills

These are stubs / aspirations — not yet written. PRs welcome.

- `azure-key-vault` — Provision Key Vault with RBAC, purge protection, soft delete.
- `azure-storage-private-endpoint` — Wire a private endpoint to a storage account.
- `azure-functions-app` — Function App with managed identity and Application Insights.
- `azure-container-apps` — Container Apps environment + workload-identity pull from ACR.
- `azure-aks-cluster` — AKS with Entra ID, Azure CNI overlay, and Defender.
- `azure-postgresql-flexible` — Flexible Server with private access and Entra auth.
- `azure-monitor-baseline` — Diagnostic settings, alerts, and workspace standards.
- `azure-rbac-least-privilege` — Picking the smallest built-in role for a task.
- `azure-managed-identity` — When to use system- vs user-assigned identities.
- `azure-bicep-baseline` — Repo layout, parameter files, and what-if pipelines.
