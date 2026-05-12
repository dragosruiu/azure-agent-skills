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
| [`security/`](security/) | "How do I detect threats and check posture?" |
| [`migration/`](migration/) | "How do I move existing workloads into Azure?" |

## Skill index

### identity-and-access
- [`azure-managed-identity`](identity-and-access/azure-managed-identity/SKILL.md) — System vs user-assigned MI; assigning to App Service / Functions / Container Apps; federated credentials for OIDC.
- [`azure-key-vault`](identity-and-access/azure-key-vault/SKILL.md) — Vault with RBAC authorization, purge protection, soft delete, network ACLs.
- [`azure-rbac-least-privilege`](identity-and-access/azure-rbac-least-privilege/SKILL.md) — Picking the smallest built-in role for common data-plane tasks.

### compute
- [`azure-app-service`](compute/azure-app-service/SKILL.md) — Linux Web App with MI, HTTPS-only, Easy Auth, Key Vault references.
- [`azure-functions`](compute/azure-functions/SKILL.md) — Flex Consumption Function App with MI and identity-based AzureWebJobsStorage.
- [`azure-container-apps`](compute/azure-container-apps/SKILL.md) — Container Apps with workload identity for ACR pull, ingress, scale rules.
- [`azure-container-registry`](compute/azure-container-registry/SKILL.md) — Premium ACR with admin user disabled, ARM-token rejection, dual private DNS zones.
- [`azure-aks-cluster`](compute/azure-aks-cluster/SKILL.md) — AKS with Entra + Azure RBAC, Azure CNI Overlay, OIDC + Workload Identity, private cluster.
- [`azure-virtual-machines`](compute/azure-virtual-machines/SKILL.md) — Linux VM with Trusted Launch, Encryption at Host, SSH-only, no public IP, JIT.
- [`azure-batch`](compute/azure-batch/SKILL.md) — Batch account + pool for HPC / parallel workloads; UAMI; user-subscription pool allocation; low-priority / Spot nodes.

### data
- [`azure-storage-account`](data/azure-storage-account/SKILL.md) — Storage account with TLS 1.2+, no shared key, infra encryption.
- [`azure-cosmos-db`](data/azure-cosmos-db/SKILL.md) — Cosmos DB for NoSQL with `disableLocalAuth`, RBAC data plane, serverless guidance.
- [`azure-postgresql-flexible`](data/azure-postgresql-flexible/SKILL.md) — Flexible Server with private access, Entra auth, zone-redundant HA.
- [`azure-sql-database`](data/azure-sql-database/SKILL.md) — Azure SQL with Entra-only auth, private endpoint, vCore Serverless.
- [`azure-redis-cache`](data/azure-redis-cache/SKILL.md) — Premium tier with Entra auth, TLS-only, private endpoint.
- [`azure-app-configuration`](data/azure-app-configuration/SKILL.md) — App Configuration with `disableLocalAuth`, purge protection, KV references, feature flags.
- [`azure-data-lake-storage-gen2`](data/azure-data-lake-storage-gen2/SKILL.md) — Storage account with `isHnsEnabled: true`; ABFS endpoints; ACL + RBAC interplay.
- [`azure-data-explorer`](data/azure-data-explorer/SKILL.md) — ADX cluster + database; KQL data-plane roles (Database Admin/User/Viewer/Ingestor/Monitor); ingestion pipelines.

### networking
- [`azure-vnet-baseline`](networking/azure-vnet-baseline/SKILL.md) — Hub-spoke pattern, subnet sizing, delegations, NSG default-deny without breaking AzureLoadBalancer.
- [`azure-private-endpoint`](networking/azure-private-endpoint/SKILL.md) — Generic private endpoint pattern incl. private DNS zone group.
- [`azure-front-door`](networking/azure-front-door/SKILL.md) — Front Door Standard/Premium with WAF, end-to-end HTTPS, managed certs.
- [`azure-application-gateway`](networking/azure-application-gateway/SKILL.md) — App Gateway WAF_v2 with TLS 1.2+, zone-redundant autoscale, custom probes.
- [`azure-firewall`](networking/azure-firewall/SKILL.md) — Azure Firewall with Firewall Policy, threat intel Deny, IDPS (Premium), per-type rule processing.
- [`azure-vpn-gateway`](networking/azure-vpn-gateway/SKILL.md) — Generation 2 VPN gateway, Active-Active, BGP, P2S Microsoft Entra ID with the new app.
- [`azure-nat-gateway`](networking/azure-nat-gateway/SKILL.md) — Outbound SNAT for subnets; preferred over outbound rules on Standard LB; PIP exhaustion math.
- [`azure-private-dns`](networking/azure-private-dns/SKILL.md) — Private DNS zones + VNet links + record sets; the canonical PE companion.

### integration
- [`azure-service-bus`](integration/azure-service-bus/SKILL.md) — Premium namespace, Entra-only, queues with DLQ + sessions, RBAC.
- [`azure-event-grid`](integration/azure-event-grid/SKILL.md) — System / custom topics, CloudEvents schema, retry + dead-letter, webhook handshake.
- [`azure-event-hubs`](integration/azure-event-hubs/SKILL.md) — Standard with auto-inflate, Kafka surface, Capture, RBAC, partition planning.
- [`azure-data-factory`](integration/azure-data-factory/SKILL.md) — ADF V2 with system MI, Git integration, MI-based linked services, dual private endpoints.
- [`azure-logic-apps`](integration/azure-logic-apps/SKILL.md) — Standard (single-tenant) on a Workflow Standard Windows plan with required app settings.
- [`azure-api-management`](integration/azure-api-management/SKILL.md) — APIM with system MI to backends, Entra-protected APIs, `<validate-jwt>` policy, developer portal, stv2 platform.

### ai-and-ml
- [`azure-openai-service`](ai-and-ml/azure-openai-service/SKILL.md) — Azure OpenAI with `disableLocalAuth`, MI access, content filter attachment.
- [`azure-ai-search`](ai-and-ml/azure-ai-search/SKILL.md) — AI Search with Entra-only, semantic ranker, integrated vectorization to Azure OpenAI.
- [`azure-machine-learning`](ai-and-ml/azure-machine-learning/SKILL.md) — AML workspace with HBI, four required dependencies, private link, serverless compute.
- [`azure-ai-foundry`](ai-and-ml/azure-ai-foundry/SKILL.md) — New Foundry (`Microsoft.CognitiveServices/accounts` kind=AIServices) vs classic Hub model; Agents Standard.
- [`azure-document-intelligence`](ai-and-ml/azure-document-intelligence/SKILL.md) — Formerly Form Recognizer; `kind: 'FormRecognizer'`; prebuilt + custom models; `disableLocalAuth`.
- [`azure-content-safety`](ai-and-ml/azure-content-safety/SKILL.md) — Text + image moderation; Prompt Shields for jailbreak / indirect injection; `kind: 'ContentSafety'`.

### observability
- [`azure-application-insights`](observability/azure-application-insights/SKILL.md) — Workspace-based App Insights with connection-string ingestion.
- [`azure-monitor-diagnostic-settings`](observability/azure-monitor-diagnostic-settings/SKILL.md) — Universal `Microsoft.Insights/diagnosticSettings` pattern.
- [`azure-monitor-alerts`](observability/azure-monitor-alerts/SKILL.md) — Metric, log, activity-log alerts; action groups; dynamic thresholds.
- [`azure-managed-grafana`](observability/azure-managed-grafana/SKILL.md) — Standard tier with system MI, Entra RBAC, private endpoint, Prometheus integration.
- [`azure-monitor-workbooks`](observability/azure-monitor-workbooks/SKILL.md) — Workbooks-as-code in Bicep via `loadTextContent()`; gallery / `sourceId` mapping.
- [`azure-log-analytics-workspace`](observability/azure-log-analytics-workspace/SKILL.md) — Foundational LAW: tables w/ Basic / Auxiliary plans, retention, customer-managed keys, daily caps; cross-referenced by App Insights / Sentinel / Defender / diag settings.

### devops
- [`github-actions-oidc-to-azure`](devops/github-actions-oidc-to-azure/SKILL.md) — Federated identity for GitHub Actions → Azure with no client secrets.
- [`azure-developer-cli`](devops/azure-developer-cli/SKILL.md) — `azd` template structure, environments, hooks, and OIDC pipeline config.
- [`azure-devops-oidc`](devops/azure-devops-oidc/SKILL.md) — Azure DevOps Pipelines Workload Identity Federation; the issuer / subject formats; task-version compatibility matrix.
- [`azure-deployment-environments`](devops/azure-deployment-environments/SKILL.md) — ADE Dev Center → Project → Environment Type → Environment; `environment.yaml` catalog; `Contributor + User Access Administrator` deployment identity.
- [`azure-pipelines-yaml-baseline`](devops/azure-pipelines-yaml-baseline/SKILL.md) — ADO YAML: `trigger` + `pr: none`, deployment jobs against Environments, `extends:` template pattern, KV-linked variable groups, `${{ }}` vs `$()`.

### infrastructure-as-code
- [`bicep-baseline`](infrastructure-as-code/bicep-baseline/SKILL.md) — Bicep repo layout, parameter files, what-if pipelines, scopes.
- [`azure-verified-modules`](infrastructure-as-code/azure-verified-modules/SKILL.md) — Consuming `br/public:avm/...` Bicep modules safely; RES vs PTN; version pinning.
- [`terraform-azurerm-baseline`](infrastructure-as-code/terraform-azurerm-baseline/SKILL.md) — Terraform `azurerm` provider with OIDC backend, AzAPI escape hatch, `plan -out` / `apply` separation.

### governance
- [`azure-naming-and-tagging`](governance/azure-naming-and-tagging/SKILL.md) — CAF-aligned naming abbreviations + required-tag set.
- [`azure-policy-baseline`](governance/azure-policy-baseline/SKILL.md) — MCSB initiative, effect ladder, remediation tasks, audit-then-enforce rollout.
- [`azure-resource-groups`](governance/azure-resource-groups/SKILL.md) — RG strategy (per env / app / blast-radius / lifecycle), locks, tag inheritance via Policy, move support.
- [`azure-cost-management`](governance/azure-cost-management/SKILL.md) — Budgets with Actual + Forecast thresholds, cost exports, anomaly detection (GA), Reservations vs Savings Plans.
- [`azure-management-groups`](governance/azure-management-groups/SKILL.md) — CAF MG hierarchy (Platform / Landing Zones / Sandbox / Decommissioned); `requireAuthorizationForGroupCreation`; never `deny` at root.

### security
- [`microsoft-defender-for-cloud`](security/microsoft-defender-for-cloud/SKILL.md) — CSPM Free vs Defender CSPM; Defender for Cloud workload-protection plans (Servers / SQL / Storage / Containers / KV / etc.); Microsoft Cloud Security Benchmark; Secure Score; auto-provisioning of agents.
- [`microsoft-sentinel`](security/microsoft-sentinel/SKILL.md) — Sentinel onboarded onto a LAW (cannot be moved across RG/sub afterwards); data connectors; analytics rules; UEBA; commitment tiers.

### migration
- [`azure-migrate`](migration/azure-migrate/SKILL.md) — Discovery + assessment + migration hub; appliance VM specs and outbound URL allow-list; agentless VMware vs agent-based migration; SQL / web app discovery.

## Roadmap

Wanted but not yet authored:

- `compute/azure-container-instances`, `compute/azure-spring-apps`
- `data/azure-sql-managed-instance`, `data/azure-cosmos-db-mongo`
- `ai-and-ml/azure-ai-speech`, `ai-and-ml/azure-ai-vision`, `ai-and-ml/azure-ai-language`
- `observability/application-insights-availability-tests`
- `governance/azure-purview` (Microsoft Purview), `governance/azure-lighthouse`
- `compute/azure-update-manager`

PRs welcome — see [`../CONTRIBUTING.md`](../CONTRIBUTING.md).


