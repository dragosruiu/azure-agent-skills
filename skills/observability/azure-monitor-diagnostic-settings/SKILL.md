---
name: azure-monitor-diagnostic-settings
description: >
  Universal pattern for routing Azure platform logs and metrics from any
  resource to a Log Analytics workspace, Storage account, or Event Hub.
  Uses `categoryGroup: allLogs` + `category: AllMetrics` for full coverage
  and `logAnalyticsDestinationType: Dedicated` for resource-specific
  tables.
version: 0.1.0
azure_services:
  - Microsoft.Insights/diagnosticSettings
tags:
  - observability
  - logs
  - metrics
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/azure-monitor/essentials/diagnostic-settings
  - https://learn.microsoft.com/azure/azure-monitor/essentials/resource-manager-diagnostic-settings
  - https://learn.microsoft.com/cli/azure/monitor/diagnostic-settings
  - https://learn.microsoft.com/rest/api/monitor/diagnostic-settings/create-or-update
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2021-05-01-preview"
last_reviewed: 2026-05-11
---

# Azure Monitor diagnostic settings (universal pattern)

## When to use this skill

- The user provisioned an Azure resource and now needs its logs/metrics
  flowing somewhere queryable.
- The user wants compliance archive of platform logs to Storage and
  real-time queries in a LAW — diagnostic settings can multi-target.
- The user wants the activity log streamed to a LAW for cross-resource
  KQL.

## When NOT to use this skill

- Application telemetry (custom traces, spans, exceptions) — use
  Application Insights instead. See [`azure-application-insights`](../azure-application-insights/SKILL.md).
- Guest-OS metrics from a VM — that's the Azure Monitor Agent, separate
  surface.

## Prerequisites

- A destination already provisioned: Log Analytics workspace, Storage
  account, or Event Hub (any combination on a single setting).
- `Monitoring Contributor` (or `Owner`) at the resource scope.
- For Storage / Event Hub destinations behind a firewall: enable
  "Allow trusted Microsoft services" so Azure Monitor can write through.

## Hard limits

- **Max 5 diagnostic settings per resource.**
- **Only one of each destination type** per setting (1 LAW + 1 storage +
  1 EH per setting).
- Storage and Event Hub destinations must be **in the same region** as
  the monitored resource.
- Initial data may take **up to 90 minutes** to appear.

## Secure defaults

> Despite the `-preview` suffix, `Microsoft.Insights/diagnosticSettings@2021-05-01-preview`
> is the version Microsoft uses in **all** current official examples. There
> is no superseding non-preview version at this writing.

| Setting | Value | Why |
| --- | --- | --- |
| `properties.logs[].categoryGroup` | `'allLogs'` | Captures every current and future log category — no need to enumerate them. |
| `properties.logs[].category` | `null` (when using categoryGroup) | Cannot mix `category` and `categoryGroup` in one entry. |
| `properties.metrics[].category` | `'AllMetrics'` | The **only** valid value for most resources. Other names cause errors. |
| `properties.logAnalyticsDestinationType` / `--export-to-resource-specific` | `'Dedicated'` / `true` | Routes into resource-specific (Dedicated) tables instead of the catch-all `AzureDiagnostics` table. KQL is much cleaner. |
| `properties.workspaceId` | full ARM resource ID of the LAW | LAW destination. |
| `properties.storageAccountId` | full ARM resource ID | Archive destination. |
| `properties.eventHubAuthorizationRuleId` + `properties.eventHubName` | full ARM resource ID + name | Streaming destination. The auth rule needs `Manage`, `Send`, `Listen`. |
| Required RBAC | `Monitoring Contributor` on the resource | Minimum role to create / modify diagnostic settings. |

## Discovery

Not all resource types support all categories. Always check first:

```bash
az monitor diagnostic-settings categories list \
  --resource "/subscriptions/.../providers/Microsoft.KeyVault/vaults/<vaultName>"
```

If `categoryGroup` isn't supported on your resource, fall back to the
listed individual `category` entries.

## Recipe — Azure CLI

```bash
# Apply to ANY resource by passing its --resource ID
RESOURCE_ID="/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.KeyVault/vaults/my-kv"
LAW_ID="/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.OperationalInsights/workspaces/my-law"
SA_ID="/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.Storage/storageAccounts/diagarchprod"
EH_RULE="/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.EventHub/namespaces/diag-ns/authorizationrules/RootManageSharedAccessKey"
EH_NAME="diag-stream"

# All-logs, all-metrics, all three destinations, resource-specific tables
az monitor diagnostic-settings create \
  --name diag-alllogs-alldestinations \
  --resource "$RESOURCE_ID" \
  --workspace "$LAW_ID" \
  --storage-account "$SA_ID" \
  --event-hub "$EH_NAME" --event-hub-rule "$EH_RULE" \
  --export-to-resource-specific true \
  --logs '[{"categoryGroup":"allLogs","enabled":true}]' \
  --metrics '[{"category":"AllMetrics","enabled":true}]'

# List
az monitor diagnostic-settings list --resource "$RESOURCE_ID"

# Delete
az monitor diagnostic-settings delete -n diag-alllogs-alldestinations --resource "$RESOURCE_ID"

# Subscription-level (activity log) — different command
az monitor diagnostic-settings subscription create \
  --name diag-activity-log --location eastus \
  --workspace "$LAW_ID" \
  --logs '[
    {"category":"Administrative","enabled":true},
    {"category":"Security","enabled":true},
    {"category":"ServiceHealth","enabled":true},
    {"category":"Alert","enabled":true},
    {"category":"Recommendation","enabled":true},
    {"category":"Policy","enabled":true},
    {"category":"Autoscale","enabled":true},
    {"category":"ResourceHealth","enabled":true}
  ]'
```

## Recipe — Bicep (resource scope)

```bicep
@description('Existing resource to monitor (any type that supports diag settings)')
param targetResourceId string
param settingName string = 'diag-alllogs-alldestinations'
param workspaceId string
param storageAccountId string
param eventHubAuthorizationRuleId string
param eventHubName string

// To attach to a specific resource type, use 'existing' + scope:
resource vault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: split(targetResourceId, '/')[8]
}

resource diag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: settingName
  scope: vault
  properties: {
    workspaceId: workspaceId
    storageAccountId: storageAccountId
    eventHubAuthorizationRuleId: eventHubAuthorizationRuleId
    eventHubName: eventHubName
    logAnalyticsDestinationType: 'Dedicated'
    logs: [
      {
        categoryGroup: 'allLogs'
        enabled: true
        retentionPolicy: { enabled: false, days: 0 }   // retention managed by LAW
      }
    ]
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
        retentionPolicy: { enabled: false, days: 0 }
      }
    ]
  }
}
```

## Recipe — Bicep (subscription / activity log)

```bicep
targetScope = 'subscription'

param settingName string = 'diag-activity-log'
param workspaceId string

resource activityDiag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: settingName
  properties: {
    workspaceId: workspaceId
    logs: [
      { category: 'Administrative', enabled: true }
      { category: 'Security',       enabled: true }
      { category: 'ServiceHealth',  enabled: true }
      { category: 'Alert',          enabled: true }
      { category: 'Recommendation', enabled: true }
      { category: 'Policy',         enabled: true }
      { category: 'Autoscale',      enabled: true }
      { category: 'ResourceHealth', enabled: true }
    ]
  }
}
```

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| `Metric category 'X' is not supported` | Only `AllMetrics` is valid for most resources | Use `AllMetrics`. |
| Resource type doesn't support metrics at all | Some PaaS services have no exportable platform metrics | Omit the `metrics` block (use logs only). ([Source](https://learn.microsoft.com/azure/azure-monitor/essentials/diagnostic-settings)) |
| No data after creating setting | Initial propagation can take up to 90 min | Wait. Disable + re-enable if still nothing after 24 h. |
| Storage / Event Hub destination fails with auth error | Destination has VNet firewall blocking Azure Monitor | Enable "Allow trusted Microsoft services" on the destination. |
| `storage account must be in the same region` | Cross-region storage destination | Provision storage in the same region as the resource. |
| `categoryGroup: allLogs` not recognized | Older resource type — doesn't yet support category groups | Fall back to individual `category` names from `az monitor diagnostic-settings categories list`. |
| Permission denied on create | Caller lacks `Monitoring Contributor` at the resource scope | Grant the role. |
| Hard limit hit when adding the 6th setting | Max 5 per resource | Consolidate destinations or delete unused settings. |
| Data is in `AzureDiagnostics` table — KQL is messy across resources | `logAnalyticsDestinationType` was `null` (default `AzureDiagnostics`) | Set `'Dedicated'` (or `--export-to-resource-specific true`). |

## References

- [Diagnostic settings overview](https://learn.microsoft.com/azure/azure-monitor/essentials/diagnostic-settings)
- [Resource Manager templates for diagnostic settings](https://learn.microsoft.com/azure/azure-monitor/essentials/resource-manager-diagnostic-settings)
- [`az monitor diagnostic-settings`](https://learn.microsoft.com/cli/azure/monitor/diagnostic-settings)
- [REST: Diagnostic Settings — Create Or Update](https://learn.microsoft.com/rest/api/monitor/diagnostic-settings/create-or-update)
