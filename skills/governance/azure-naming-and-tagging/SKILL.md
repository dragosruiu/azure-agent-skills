---
name: azure-naming-and-tagging
description: >
  Cloud Adoption Framework (CAF) naming pattern and tagging strategy
  for Azure resources. Includes the canonical CAF abbreviation table,
  the per-resource length / charset / scope rules, and a Bicep tag
  variable + Azure Policy "Inherit a tag from the resource group"
  recipe.
version: 0.1.0
azure_services:
  - Microsoft.Resources/resourceGroups
  - Microsoft.Authorization/policyAssignments
tags:
  - governance
  - naming
  - tagging
  - caf
sources:
  - https://learn.microsoft.com/azure/cloud-adoption-framework/ready/azure-best-practices/resource-naming
  - https://learn.microsoft.com/azure/cloud-adoption-framework/ready/azure-best-practices/resource-abbreviations
  - https://learn.microsoft.com/azure/azure-resource-manager/management/resource-name-rules
  - https://learn.microsoft.com/azure/cloud-adoption-framework/ready/azure-best-practices/resource-tagging
validated_with:
  az_cli: ">=2.60.0"
  api_version: "n/a (governance pattern)"
last_reviewed: 2026-05-11
---

# Azure naming and tagging (CAF-aligned)

## When to use this skill

- The user is bootstrapping a new subscription / RG layout.
- The user wants to enforce a naming convention without writing one from
  scratch.
- The user is hitting unique-name collisions on storage / Key Vault /
  ACR (the global-name traps).

## When NOT to use this skill

- The user already has a documented org-wide naming standard — follow it.
- One-off lab / sandbox resources where naming consistency doesn't matter.

## Secure defaults

These aren't *security* knobs in the usual sense, but they're the
non-negotiables for a healthy fleet — pick them up front because
retroactive renaming and re-tagging is expensive.

| Decision | Default | Why |
| --- | --- | --- |
| **Naming pattern** | `<abbrev>-<workload>-<env>[-<region>][-<instance>]` (CAF) | Predictable lookup; works with Azure Policy "match" rules. |
| **Globally-unique resource names** | append `uniqueString(resourceGroup().id)` | Avoids storage / Key Vault / ACR collisions; deterministic per RG. |
| **Tag values** | consistent casing (lowercase recommended) | Tag values are **case-sensitive in cost reports** — `prod` and `Prod` show as separate categories. |
| **Required-tag minimum** | `env`, `app`, `owner`, `costCenter`, `dataClassification` | Covers Functional / Ownership / Accounting / Classification CAF categories. |
| **Tags as inheritance** | Built-in policy `Inherit a tag from the resource group if missing` (`cd3aa116-8754-49c9-a813-ad46512ece54`) | Fewer tags to set on every child resource. **Forward-only — does NOT backfill.** |
| **Never in tags** | secrets, PII, compliance data | Tags are visible in cost reports, ARM API, deployment history, monitoring logs. |
| **Never in resource names** | `#` | Breaks ARM URL parsing. |

## Naming pattern (CAF)

```
<resource-abbreviation>-<workload>-<environment>[-<region>][-<instance>]
```

Examples:

```
rg-navigator-prod-001
oai-navigator-prod
kv-navigator-prod
stnavigatorprod         <- storage: NO hyphens, lowercase only, ≤ 24 chars
crnavigatorprod         <- ACR: NO hyphens or underscores, ≤ 50 chars
func-navigator-prod-001
app-navigator-prod-001
vnet-shared-eastus2-001
log-navigator-prod
appi-navigator-prod
```

## CAF abbreviation + naming-rule table

Verified against [resource-abbreviations](https://learn.microsoft.com/azure/cloud-adoption-framework/ready/azure-best-practices/resource-abbreviations) and [resource-name-rules](https://learn.microsoft.com/azure/azure-resource-manager/management/resource-name-rules).

| Resource | Abbrev. | ARM type | Scope | Length | Valid characters |
| --- | --- | --- | --- | --- | --- |
| Resource group | `rg` | `Microsoft.Resources/resourceGroups` | subscription | 1–90 | alphanumeric, underscore, hyphen, period, parens; can't end with `.` |
| Storage account | `st` | `Microsoft.Storage/storageAccounts` | **global** | **3–24** | **lowercase letters + digits only — NO hyphens** |
| Key Vault | `kv` | `Microsoft.KeyVault/vaults` | **global** | **3–24** | alphanumeric + hyphens; start with letter; no consecutive hyphens |
| Web App | `app` | `Microsoft.Web/sites` | global | 2–60 | alphanumeric + hyphens |
| Function App | `func` | `Microsoft.Web/sites` | global | 2–60 | alphanumeric + hyphens |
| Container App | `ca` | `Microsoft.App/containerApps` | resource group | 2–32 | lowercase alphanumeric + hyphens |
| Container Apps env | `cae` | `Microsoft.App/managedEnvironments` | resource group | 1–60 | alphanumeric + hyphens |
| AKS cluster | `aks` | `Microsoft.ContainerService/managedClusters` | resource group | 1–63 | alphanumeric, underscore, hyphen |
| Container Registry | `cr` | `Microsoft.ContainerRegistry/registries` | **global** | 5–50 | **alphanumeric only — NO hyphens or underscores** |
| Cosmos DB account | `cosmos` | `Microsoft.DocumentDB/databaseAccounts` | global | 3–44 | lowercase alphanumeric + hyphens |
| PostgreSQL Flexible | `psql` | `Microsoft.DBforPostgreSQL/flexibleServers` | global | 3–63 | lowercase alphanumeric + hyphens |
| Azure SQL server | `sql` | `Microsoft.Sql/servers` | global | 1–63 | lowercase alphanumeric + hyphens |
| Azure OpenAI | `oai` | `Microsoft.CognitiveServices/accounts` (kind=OpenAI) | resource group | 2–64 | alphanumeric + hyphens |
| AI Search | `srch` | `Microsoft.Search/searchServices` | global | 2–60 | lowercase alphanumeric + hyphens |
| VNet | `vnet` | `Microsoft.Network/virtualNetworks` | resource group | 2–64 | alphanumeric, underscore, period, hyphen |
| Subnet | `snet` | `Microsoft.Network/virtualNetworks/subnets` | virtual network | 1–80 | alphanumeric, underscore, period, hyphen |
| NSG | `nsg` | `Microsoft.Network/networkSecurityGroups` | resource group | 1–80 | alphanumeric, underscore, period, hyphen |
| Private endpoint | `pep` | `Microsoft.Network/privateEndpoints` | resource group | 2–64 | alphanumeric, underscore, period, hyphen |
| Public IP | `pip` | `Microsoft.Network/publicIPAddresses` | resource group | 1–80 | alphanumeric, underscore, period, hyphen |
| User-assigned MI | `id` | `Microsoft.ManagedIdentity/userAssignedIdentities` | resource group | 3–128 | alphanumeric, underscore, hyphen |
| Log Analytics workspace | `log` | `Microsoft.OperationalInsights/workspaces` | resource group | 4–63 | alphanumeric + hyphens |
| Application Insights | `appi` | `Microsoft.Insights/components` | resource group | 1–260 | (most chars) |
| API Management | `apim` | `Microsoft.ApiManagement/service` | global | 1–50 | alphanumeric + hyphens |
| Service Bus namespace | `sbns` | `Microsoft.ServiceBus/namespaces` | global | 6–50 | alphanumeric + hyphens |
| Event Grid topic | `evgt` | `Microsoft.EventGrid/topics` | global | 3–50 | alphanumeric + hyphens |
| Management group | `mg` | `Microsoft.Management/managementGroups` | tenant | 1–90 | alphanumeric, hyphen, underscore, period, parens |

> **The traps that bite agents most often:**
> - **Storage: NO hyphens. 24-char ceiling. Global.** `st-app-prod` is invalid.
> - **ACR: NO hyphens, NO underscores.** `cr-app-prod` is invalid.
> - **Key Vault: 24-char ceiling, global.** Plan accordingly when name = `kv-<long-app-name>-<env>`.
> - **Never use `#` in any resource name** — breaks ARM URL parsing.

For globally-unique names, append `uniqueString(resourceGroup().id)`:

```bicep
// stays under 24 chars when storagePrefix ≤ 11
var storageName = '${storagePrefix}${uniqueString(resourceGroup().id)}'
```

## Tagging strategy

The CAF does **not** mandate a specific required-tag list — it
recommends defining your own based on **categories**
([resource-tagging](https://learn.microsoft.com/azure/cloud-adoption-framework/ready/azure-best-practices/resource-tagging)):

| Category | Purpose | Example tag names |
| --- | --- | --- |
| **Functional** | Operational management | `app`, `tier`, `env`, `region` |
| **Classification** | Governance / security | `criticality`, `confidentiality`, `sla`, `dataClassification` |
| **Accounting** | Cost / chargeback | `costCenter`, `department`, `program`, `project` |
| **Purpose** | Business alignment | `businessProcess`, `businessImpact`, `revenueImpact` |
| **Ownership** | Accountability | `owner`, `businessUnit`, `opsTeam` |

A pragmatic default required-tag set for an agent provisioning new
resources (pick the ones that make sense for your org):

```
env, app, owner, costCenter, dataClassification
```

> **Tag values are case-sensitive in cost reports.** Pick a casing
> convention (`env: prod` vs `env: Production`) and stick to it.
> **Never put secrets in tags** — they end up in cost reports, ARM API
> responses, deployment history, and monitoring logs.

## Recipe — Azure CLI

```bash
# Apply tags at RG creation
az group create -n rg-navigator-prod-001 -l eastus --tags \
  env=prod app=navigator owner=team-platform costCenter=55332 dataClassification=internal

# Tag an existing resource
az resource tag \
  --ids /subscriptions/.../providers/Microsoft.Storage/storageAccounts/stnavigatorprod \
  --tags env=prod app=navigator costCenter=55332

# Find resources missing a required tag
az resource list -g rg-navigator-prod-001 \
  --query "[?tags.costCenter == null].{name:name, type:type}" -o table

# Assign the built-in policy "Inherit a tag from the resource group if missing"
# Policy ID is stable: cd3aa116-8754-49c9-a813-ad46512ece54
az policy assignment create \
  --name inherit-env-from-rg \
  --policy cd3aa116-8754-49c9-a813-ad46512ece54 \
  --scope "/subscriptions/$SUB" \
  --params '{ "tagName": { "value": "env" } }'

# To backfill tags on resources that existed before the policy was applied:
# create a remediation task on the policy assignment.
```

> The "Inherit a tag" policy adds the tag to **new and modified**
> resources. **It does NOT retroactively tag pre-existing resources** —
> you need an explicit remediation task or `az resource tag`.

## Recipe — Bicep

```bicep
param appName string
param environment string
param costCenter string
param owner string
param dataClassification string
param location string = resourceGroup().location

var requiredTags = {
  app: appName                  // Functional
  env: environment
  owner: owner                  // Ownership
  costCenter: costCenter        // Accounting
  dataClassification: dataClassification  // Classification
  managedBy: 'bicep'
}

resource rg 'Microsoft.Resources/resourceGroups@2025-04-01' = {
  name: 'rg-${appName}-${environment}-001'  // 1–90 chars, subscription scope
  location: location
  tags: requiredTags
}

// Storage: NO hyphens; ≤ 24 chars; global
var storageName = '${appName}${environment}${uniqueString(rg.id)}'  // keep input short
```

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| `StorageAccountAlreadyTaken` | Storage names are global; another tenant has it | Add entropy via `uniqueString(resourceGroup().id)`; keep prefix short. |
| Storage create rejects `st-app-prod` | Storage names cannot contain hyphens | Use `stappprod...` |
| ACR create rejects `cr-app-prod` | ACR names cannot contain hyphens or underscores | Use `crappprod...` |
| Key Vault create fails with name length | Global, ≤ 24 chars | Shorten the workload prefix or drop a segment. |
| Cost reports show `env: Production` and `env: production` as separate | Tag values are case-sensitive | Standardize casing (lowercase recommended); fix existing values via `az resource tag`. |
| New resource has the right tags but old ones don't | "Inherit a tag" policy applies forward only | Run a remediation task on the policy assignment. |
| Resource has a tag with sensitive data showing up in cost analysis | Secrets in tags are exposed everywhere | Remove and rotate the secret; never put credentials, PII, or compliance data in tags. |

## References

- [CAF: Resource naming](https://learn.microsoft.com/azure/cloud-adoption-framework/ready/azure-best-practices/resource-naming)
- [CAF: Resource abbreviation table](https://learn.microsoft.com/azure/cloud-adoption-framework/ready/azure-best-practices/resource-abbreviations)
- [Naming rules per resource type](https://learn.microsoft.com/azure/azure-resource-manager/management/resource-name-rules)
- [CAF: Resource tagging strategy](https://learn.microsoft.com/azure/cloud-adoption-framework/ready/azure-best-practices/resource-tagging)
