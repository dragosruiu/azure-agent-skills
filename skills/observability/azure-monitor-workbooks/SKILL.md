---
name: azure-monitor-workbooks
description: >
  Deploy Azure Monitor Workbooks as Bicep — `Microsoft.Insights/workbooks`
  resources with `serializedData` loaded from a `.workbook` file via
  `loadTextContent()`. Covers the gallery / `sourceId` mapping,
  `kind: shared` (the only valid value), and KQL guards for missing
  tables.
version: 0.1.0
azure_services:
  - Microsoft.Insights/workbooks
  - microsoft.insights/workbooktemplates
tags:
  - observability
  - dashboards
  - kql
sources:
  - https://learn.microsoft.com/azure/azure-monitor/visualize/workbooks-overview
  - https://learn.microsoft.com/azure/azure-monitor/visualize/workbooks-create-workbook
  - https://learn.microsoft.com/azure/azure-monitor/visualize/workbooks-automate
  - https://learn.microsoft.com/azure/templates/microsoft.insights/workbooks
  - https://learn.microsoft.com/azure/azure-resource-manager/bicep/bicep-functions-files
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2023-06-01"
last_reviewed: 2026-05-11
---

# Azure Monitor Workbooks

## When to use this skill

- The user wants interactive, parameterized visualizations on top of a
  Log Analytics workspace or App Insights.
- The user wants dashboards-as-code in Bicep / Git, not click-ops.
- The user wants a Troubleshooting Guide (TSG) attached to an App
  Insights resource.

## When NOT to use this skill

- The user wants Grafana — see
  [`azure-managed-grafana`](../azure-managed-grafana/SKILL.md).
- Pure metric thresholds with action groups — see
  [`azure-monitor-alerts`](../azure-monitor-alerts/SKILL.md).

## Authoring workflow

1. Author interactively in the Azure portal under Azure Monitor →
   Workbooks (or Log Analytics → Workbooks).
2. Click **Edit → Advanced editor (`</>`) → Gallery Template** and
   copy the JSON.
3. Save as `dashboard.workbook` (extension is cosmetic — it's just JSON).
4. Reference from Bicep via `loadTextContent('./dashboard.workbook')`.
5. Deploy with `az deployment group create`.

## Secure defaults

| Property | Value | Why |
| --- | --- | --- |
| `kind` | `'shared'` | The **only** valid value. `'user'` is deprecated. |
| `properties.category` | `'workbook'` (general) or `'tsg'` (Troubleshooting Guide) or `'usage'` (App Insights usage) | Determines which gallery the workbook shows up in. |
| `properties.displayName` | unique within scope of `<RG, sourceId>` | Collisions cause the second deploy to fail. |
| `properties.serializedData` | string of valid JSON; load via `loadTextContent()` to avoid manual escaping | Required. |
| `properties.sourceId` | resource ID of the LAW / AI / RG, or the literal `'Azure Monitor'` for the global gallery | Determines which blade shows the workbook. |
| `properties.version` | `'Notebook/1.0'` | Should match the schema version inside `serializedData`. |
| `name` | `guid(resourceGroup().id, displayName)` | Deterministic ID; idempotent re-deploys. |
| RBAC to edit | `Monitoring Contributor` (or anything that grants `microsoft.insights/workbooks/write`) | |

## `sourceId` → gallery mapping

| Show in | `sourceId` value | `category` |
| --- | --- | --- |
| Azure Monitor Workbooks (global gallery) | `'Azure Monitor'` (case-insensitive) | `'workbook'` |
| A Log Analytics workspace | `<law-resource-id>` | `'workbook'` |
| Application Insights | `<ai-resource-id>` | `'workbook'` |
| App Insights TSG | `<ai-resource-id>` | `'tsg'` |
| App Insights Usage | `<ai-resource-id>` | `'usage'` |
| Resource group | `<rg-resource-id>` | `'workbook'` |

## Recipe — Bicep

```bicep
param location string = resourceGroup().location
param displayName string = 'My Application Dashboard'
@description('LAW or AI resource ID, or literal "Azure Monitor" for the global gallery')
param workbookSourceId string = 'Azure Monitor'

// Loaded at COMPILE time. File path must be a string literal (no variables).
var serializedWorkbook = loadTextContent('./dashboard.workbook')

resource workbook 'Microsoft.Insights/workbooks@2023-06-01' = {
  name: guid(resourceGroup().id, displayName)
  location: location
  kind: 'shared'
  properties: {
    category: 'workbook'
    displayName: displayName
    serializedData: serializedWorkbook
    sourceId: workbookSourceId
    version: 'Notebook/1.0'
  }
}

output workbookId string = workbook.id
output workbookUrl string = 'https://portal.azure.com/#@${tenant().tenantId}/resource${workbook.id}'
```

## Recipe — CLI deploy

```bash
az deployment group create \
  --name "wb-deploy-$(date +%Y%m%d-%H%M%S)" \
  --resource-group rg-monitoring-prod \
  --template-file workbook.bicep \
  --parameters \
    displayName="App Health Dashboard" \
    workbookSourceId="/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.OperationalInsights/workspaces/$LAW"

# List workbooks in an RG
az resource list -g rg-monitoring-prod \
  --resource-type microsoft.insights/workbooks \
  --query "[].{name:name, displayName:properties.displayName, category:properties.category}" -o table
```

## Robust KQL inside a workbook

Workbook tiles often outlive the schema they were written against.
Defensive KQL:

```kusto
union isfuzzy=true
  AppRequests,
  requests   // legacy classic AI table
| where TimeGenerated > ago(1h)
| extend Name = column_ifexists("Name", column_ifexists("name", ""))
| summarize count() by Name, bin(TimeGenerated, 5m)
```

`union isfuzzy=true` and `column_ifexists()` keep the workbook
rendering even if a table or column doesn't exist in the chosen LAW.

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| Workbook deploy fails with `'kind' invalid` | Tried `kind: 'user'` (deprecated) | Use `kind: 'shared'`. |
| `displayName` collision | Another workbook in the same `<RG, sourceId>` has the same name | Pick a unique displayName, or use a deterministic `guid(... displayName)` and accept the new GUID for renames. |
| Tiles return empty | KQL references a table or column that doesn't exist | Wrap with `union isfuzzy=true` / `column_ifexists()`. |
| Workbook never appears in the expected blade | Wrong `sourceId` for the chosen `category` | See the gallery mapping table above. |
| Workbook renders empty after Bicep deploy | `serializedData` JSON is malformed (manual escaping mistake) | Load via `loadTextContent()`; don't hand-escape JSON. |
| Cannot edit a shared workbook | Caller lacks `microsoft.insights/workbooks/write` | Grant `Monitoring Contributor` or a custom role with that action. |

## References

- [Workbooks overview](https://learn.microsoft.com/azure/azure-monitor/visualize/workbooks-overview)
- [Create a workbook](https://learn.microsoft.com/azure/azure-monitor/visualize/workbooks-create-workbook)
- [Automate workbooks (ARM/Bicep)](https://learn.microsoft.com/azure/azure-monitor/visualize/workbooks-automate)
- [`Microsoft.Insights/workbooks` template](https://learn.microsoft.com/azure/templates/microsoft.insights/workbooks)
- [Bicep `loadTextContent` function](https://learn.microsoft.com/azure/azure-resource-manager/bicep/bicep-functions-files)
