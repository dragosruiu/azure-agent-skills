# skills/

Skills are organized by **task category** matching the verbs an agent uses
on a real Azure build. Each category contains one directory per skill,
with a `SKILL.md` (required) and optional `references/` + `scripts/`
subdirectories.

See [`../docs/skill-format.md`](../docs/skill-format.md) for the full spec
and [`../CONTRIBUTING.md`](../CONTRIBUTING.md) for the contribution
workflow.

## Categories

| Category | Answers for the agent |
| --- | --- |
| [`identity-and-access/`](identity-and-access/) | "How do I auth this without secrets?" |
| [`compute/`](compute/) | "Where do I run my code?" |
| [`data/`](data/) | "Where do I store my state?" |
| [`networking/`](networking/) | "How do I expose / isolate this?" |
| [`integration/`](integration/) | "How do services talk to each other?" |
| [`ai-and-ml/`](ai-and-ml/) | "How do I add AI to this app?" |
| [`observability/`](observability/) | "How do I see what's happening?" |
| [`devops/`](devops/) | "How do I deploy this from CI?" |
| [`infrastructure-as-code/`](infrastructure-as-code/) | "How do I declare this declaratively?" |
| [`governance/`](governance/) | "What do I name / tag / scope this with?" |

## Skill index

### identity-and-access
- [`azure-managed-identity`](identity-and-access/azure-managed-identity/SKILL.md) — System vs user-assigned MI; assigning to App Service / Functions / Container Apps; federated credentials for OIDC.
- [`azure-key-vault`](identity-and-access/azure-key-vault/SKILL.md) — Vault with RBAC authorization, purge protection, soft delete, network ACLs.
- [`azure-rbac-least-privilege`](identity-and-access/azure-rbac-least-privilege/SKILL.md) — Picking the smallest built-in role for common data-plane tasks.

### compute
- [`azure-app-service`](compute/azure-app-service/SKILL.md) — Linux Web App with MI, HTTPS-only, Easy Auth, Key Vault references.
- [`azure-functions`](compute/azure-functions/SKILL.md) — Flex Consumption Function App with MI and identity-based AzureWebJobsStorage.
- [`azure-container-apps`](compute/azure-container-apps/SKILL.md) — Container Apps with workload identity for ACR pull, ingress, scale rules.
- [`azure-aks-cluster`](compute/azure-aks-cluster/SKILL.md) — AKS with Entra + Azure RBAC, Azure CNI Overlay, OIDC + Workload Identity, private cluster.

### data
- [`azure-storage-account`](data/azure-storage-account/SKILL.md) — Storage account with TLS 1.2+, no shared key, infra encryption.
- [`azure-cosmos-db`](data/azure-cosmos-db/SKILL.md) — Cosmos DB for NoSQL with `disableLocalAuth`, RBAC data plane, serverless guidance.
- [`azure-postgresql-flexible`](data/azure-postgresql-flexible/SKILL.md) — Flexible Server with private access, Entra auth, zone-redundant HA.
- [`azure-sql-database`](data/azure-sql-database/SKILL.md) — Azure SQL with Entra-only auth, private endpoint, vCore Serverless.
- [`azure-redis-cache`](data/azure-redis-cache/SKILL.md) — Premium tier with Entra auth, TLS-only, private endpoint.

### networking
- [`azure-vnet-baseline`](networking/azure-vnet-baseline/SKILL.md) — Hub-spoke pattern, subnet sizing, delegations, NSG default-deny without breaking AzureLoadBalancer.
- [`azure-private-endpoint`](networking/azure-private-endpoint/SKILL.md) — Generic private endpoint pattern incl. private DNS zone group.
- [`azure-front-door`](networking/azure-front-door/SKILL.md) — Front Door Standard/Premium with WAF, end-to-end HTTPS, managed certs.
- [`azure-application-gateway`](networking/azure-application-gateway/SKILL.md) — App Gateway WAF_v2 with TLS 1.2+, zone-redundant autoscale, custom probes.

### integration
- [`azure-service-bus`](integration/azure-service-bus/SKILL.md) — Premium namespace, Entra-only, queues with DLQ + sessions, RBAC.
- [`azure-event-grid`](integration/azure-event-grid/SKILL.md) — System / custom topics, CloudEvents schema, retry + dead-letter, webhook handshake.
- [`azure-event-hubs`](integration/azure-event-hubs/SKILL.md) — Standard with auto-inflate, Kafka surface, Capture, RBAC, partition planning.

### ai-and-ml
- [`azure-openai-service`](ai-and-ml/azure-openai-service/SKILL.md) — Azure OpenAI with `disableLocalAuth`, MI access, content filter attachment.
- [`azure-ai-search`](ai-and-ml/azure-ai-search/SKILL.md) — AI Search with Entra-only, semantic ranker, integrated vectorization to Azure OpenAI.

### observability
- [`azure-application-insights`](observability/azure-application-insights/SKILL.md) — Workspace-based App Insights with connection-string ingestion.
- [`azure-monitor-diagnostic-settings`](observability/azure-monitor-diagnostic-settings/SKILL.md) — Universal `Microsoft.Insights/diagnosticSettings` pattern.
- [`azure-monitor-alerts`](observability/azure-monitor-alerts/SKILL.md) — Metric, log, activity-log alerts; action groups; dynamic thresholds.

### devops
- [`github-actions-oidc-to-azure`](devops/github-actions-oidc-to-azure/SKILL.md) — Federated identity for GitHub Actions → Azure with no client secrets.
- [`azure-developer-cli`](devops/azure-developer-cli/SKILL.md) — `azd` template structure, environments, hooks, and OIDC pipeline config.

### infrastructure-as-code
- [`bicep-baseline`](infrastructure-as-code/bicep-baseline/SKILL.md) — Bicep repo layout, parameter files, what-if pipelines, scopes.
- [`azure-verified-modules`](infrastructure-as-code/azure-verified-modules/SKILL.md) — Consuming `br/public:avm/...` Bicep modules safely; RES vs PTN; version pinning.

### governance
- [`azure-naming-and-tagging`](governance/azure-naming-and-tagging/SKILL.md) — CAF-aligned naming abbreviations + required-tag set.
- [`azure-policy-baseline`](governance/azure-policy-baseline/SKILL.md) — MCSB initiative, effect ladder, remediation tasks, audit-then-enforce rollout.

## Roadmap

Wanted but not yet authored:

- `compute/azure-virtual-machines`, `compute/azure-container-instances`
- `data/azure-sql-managed-instance`, `data/azure-cosmos-db-mongo`
- `networking/azure-vpn-gateway`, `networking/azure-firewall`
- `integration/azure-logic-apps`, `integration/azure-data-factory`
- `ai-and-ml/azure-ai-foundry`, `ai-and-ml/azure-machine-learning`
- `observability/azure-monitor-workbooks`, `observability/azure-managed-grafana`
- `devops/azure-devops-oidc`, `devops/azure-deployment-environments`
- `infrastructure-as-code/terraform-azurerm-baseline`
- `governance/azure-resource-groups`, `governance/azure-cost-management`

PRs welcome — see [`../CONTRIBUTING.md`](../CONTRIBUTING.md).

