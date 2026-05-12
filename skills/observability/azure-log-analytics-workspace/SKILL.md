---
name: azure-log-analytics-workspace
description: >
  Provision a Log Analytics workspace (LAW) — the foundation that
  Application Insights, Sentinel, Defender for Cloud, diagnostic
  settings, Container Insights, and Workbooks all sit on. Covers SKU
  picker, retention (default 30 / max 730 analytics / 12 yr archive),
  `disableLocalAuth`, AMPLS for private-only access, CMK via dedicated
  cluster, and the 31-day commitment-tier lock.
version: 0.1.0
azure_services:
  - Microsoft.OperationalInsights/workspaces
  - Microsoft.OperationalInsights/clusters
  - microsoft.insights/privateLinkScopes
tags:
  - observability
  - log-analytics
  - foundation
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/azure-monitor/logs/log-analytics-workspace-overview
  - https://learn.microsoft.com/azure/azure-monitor/logs/cost-logs
  - https://learn.microsoft.com/azure/azure-monitor/logs/data-retention-configure
  - https://learn.microsoft.com/azure/azure-monitor/logs/private-link-configure
  - https://learn.microsoft.com/azure/azure-monitor/logs/customer-managed-keys
  - https://learn.microsoft.com/azure/azure-monitor/logs/workspace-design
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2022-10-01"
last_reviewed: 2026-05-12
---

# Azure Log Analytics Workspace (foundation)

## When to use this skill

- The user is wiring Application Insights / Sentinel / Defender for
  Cloud / Container Insights / VM Insights — they all need a LAW.
- The user wants centralized log storage with KQL.
- The user wants `disableLocalAuth: true` enforced + private-only
  access via AMPLS.

## When NOT to use this skill

- Customer-facing app traces / spans only — see [`azure-application-insights`](../azure-application-insights/SKILL.md)
  (which still creates a LAW under the hood for workspace-based AI).
- Per-resource logs/metrics routing — see [`azure-monitor-diagnostic-settings`](../azure-monitor-diagnostic-settings/SKILL.md).

## SKU picker

| Tier | SKU | When |
| --- | --- | --- |
| Pay-as-you-go | `PerGB2018` (default) | Any workload < ~100 GB/day; no commitment. |
| Commitment 100 GB/day | `CapacityReservation` (capacity 100) | Sustained ingestion ≥ 100 GB/day; ~30% off PAYG. |
| Commitment 200 / 300 / 400 / 500 / 1 000 / 2 000 / 5 000 GB/day | `CapacityReservation` (capacity N) | Larger discounts at scale. |
| Dedicated cluster | `Microsoft.OperationalInsights/clusters` (≥ 100 GB/day) | Required for **CMK**, multi-workspace billing aggregation. |

> **31-day commitment lock:** changes to the tier are committed for
> 31 days. You can **increase** during the period (restarts the
> 31-day clock); **decrease blocked** until the period ends.

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| `sku.name` | `'PerGB2018'` (start here, switch to `CapacityReservation` once steady-state is known) | Avoid wasted commitment. |
| `retentionInDays` | `90` for Sentinel / sec workloads; `30` (default) for ops | First 90 days are free for Sentinel-enabled LAWs. |
| `features.disableLocalAuth` | `true` | Force Entra ID; no shared-key ingestion. |
| `features.enableLogAccessUsingOnlyResourcePermissions` | `true` | Log access scoped to RBAC on the resource the data came from, not just LAW-level. |
| `publicNetworkAccessForIngestion` | `'Disabled'` (with AMPLS) | Block public ingestion. |
| `publicNetworkAccessForQuery` | `'Disabled'` (with AMPLS) | Block public queries — including from the Azure portal unless caller is on a network with the AMPLS PE. |
| `workspaceCapping.dailyQuotaGb` | a value (not `-1`) for cost guardrails | `-1` = unlimited. |
| `immediatePurgeDataOn30Days` | `true` if you genuinely need 30-day-only retention for compliance | Default behavior may keep up to 31 days. |
| **CMK** | only via a dedicated `Microsoft.OperationalInsights/clusters` resource (min 100 GB/day) | Workspace-only CMK is not supported. |

## Retention model

| Layer | Range | Notes |
| --- | --- | --- |
| Analytics (interactive KQL) | **30 – 730 days** (default 30) | Direct query. `Usage`, `AzureActivity`, App Insights tables = 90 days free. |
| Long-term / archive | up to **12 years (4,383 days)** via portal/API; CLI/PS limited to 7 yrs | Requires a **search job** to bring data back into analytics retention. |
| Minimum analytics | 4 days (API/CLI only); no cost reduction below 31 days | |

## AMPLS (Azure Monitor Private Link Scope)

To make a LAW reachable only from inside a VNet, you need an AMPLS:

- Resource type: `microsoft.insights/privateLinkScopes` (always `location: 'global'`).
- `accessModeSettings.queryAccessMode` and `ingestionAccessMode`:
  `'PrivateOnly'` (recommended) or `'Open'` (fall back to public).
- DNS zones to create + link to the consumer VNet:
  - `privatelink.monitor.azure.com`
  - `privatelink.oms.opinsights.azure.com`
  - `privatelink.ods.opinsights.azure.com`
  - `privatelink.agentsvc.azure-automation.net`
  - `privatelink.blob.core.windows.net`
- Link the LAW to the AMPLS via `microsoft.insights/privateLinkScopes/scopedresources`.

## Recipe — Azure CLI

```bash
RG=rg-law-prod
LOC=eastus
LAW=law-app-prod

az group create -n "$RG" -l "$LOC"

# 1. Create LAW (PAYG, 90-day retention)
az monitor log-analytics workspace create -g "$RG" -n "$LAW" -l "$LOC" \
  --sku PerGB2018 --retention-time 90

# 2. Disable public access (require AMPLS)
az monitor log-analytics workspace update -g "$RG" -n "$LAW" \
  --ingestion-access Disabled --query-access Disabled

# 3. Set table-level retention (e.g., SecurityEvent → 180 days analytics + 2 yrs archive)
az monitor log-analytics workspace table update -g "$RG" --workspace-name "$LAW" \
  -n SecurityEvent --retention-time 180 --total-retention-time 730

# 4. AMPLS
az monitor private-link-scope create -g "$RG" -n ampls-prod
LAW_ID=$(az monitor log-analytics workspace show -g "$RG" -n "$LAW" --query id -o tsv)
az monitor private-link-scope scoped-resource create -g "$RG" \
  --scope-name ampls-prod -n "$LAW-link" --linked-resource "$LAW_ID"

# 5. Set commitment tier (only after 30+ days of measured ingestion)
# az monitor log-analytics workspace update -g "$RG" -n "$LAW" \
#   --sku CapacityReservation --capacity-reservation-level 200
```

## Recipe — Bicep

```bicep
param workspaceName string
param location string = resourceGroup().location
param retentionDays int = 90
param dailyCapGb int = -1     // -1 = unlimited; set a value for cost cap

resource law 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: workspaceName
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: retentionDays
    features: {
      disableLocalAuth: true
      enableLogAccessUsingOnlyResourcePermissions: true
    }
    publicNetworkAccessForIngestion: 'Disabled'
    publicNetworkAccessForQuery: 'Disabled'
    workspaceCapping: { dailyQuotaGb: dailyCapGb }
  }
}

// AMPLS to satisfy the publicNetworkAccess = Disabled constraint
resource ampls 'microsoft.insights/privateLinkScopes@2023-06-01-preview' = {
  name: 'ampls-${workspaceName}'
  location: 'global'
  properties: {
    accessModeSettings: {
      queryAccessMode: 'PrivateOnly'
      ingestionAccessMode: 'PrivateOnly'
    }
  }
}

resource amplsLink 'microsoft.insights/privateLinkScopes/scopedresources@2023-06-01-preview' = {
  parent: ampls
  name: '${workspaceName}-link'
  properties: { linkedResourceId: law.id }
}

output workspaceId string = law.id
```

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| KQL query returns no data | Source resource never had a diag setting to this LAW | Add a diag setting; verify with `Usage` and `Operation` tables. |
| Azure Portal can't query the LAW | `publicNetworkAccessForQuery: Disabled` and you're not on a network linked to the AMPLS PE | Set `queryAccessMode: 'Open'` temporarily, or query from a VM in the AMPLS VNet. |
| Cannot reduce commitment tier | 31-day lock active | Wait the 31 days; cannot decrease until period ends. |
| CMK setup fails: KV access denied | Cluster MI lacks `Key Vault Crypto Service Encryption User` (or `get/wrap/unwrap` access policies) on the KV | Grant the role; KV needs soft-delete + purge protection enabled first. |
| Hot-cache (last 14 days SSD) data inaccessible after revoking the CMK key | By design — key revocation deletes the hot cache | Re-grant access; data outside the hot cache is unaffected. |
| `disableLocalAuth: true` breaks existing agents | Agents were using shared-key auth | Migrate agents to AMA + MI **before** flipping `disableLocalAuth`. |
| Long-term-retention data isn't queryable in normal KQL | Archive needs a **search job** to surface | Run a search job, or use Data Restore. |
| Dedicated cluster billing started but no workspaces linked | Cluster billing begins at creation | Link workspaces immediately, or delete the cluster. |
| Workspace retention shows 31 days when set to 30 | Default behavior may keep up to 31 days | Set `immediatePurgeDataOn30Days: true` for strict 30-day compliance. |

## References

- [LAW overview](https://learn.microsoft.com/azure/azure-monitor/logs/log-analytics-workspace-overview)
- [Cost / pricing tiers](https://learn.microsoft.com/azure/azure-monitor/logs/cost-logs)
- [Configure data retention](https://learn.microsoft.com/azure/azure-monitor/logs/data-retention-configure)
- [Private Link (AMPLS) configuration](https://learn.microsoft.com/azure/azure-monitor/logs/private-link-configure)
- [Customer-managed keys](https://learn.microsoft.com/azure/azure-monitor/logs/customer-managed-keys)
- [Workspace design](https://learn.microsoft.com/azure/azure-monitor/logs/workspace-design)
