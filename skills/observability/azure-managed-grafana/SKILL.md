---
name: azure-managed-grafana
description: >
  Provision Azure Managed Grafana (Standard tier — Essential is being
  retired) with Microsoft Entra-only access, system-assigned MI for the
  Azure Monitor data source, public network access disabled with a
  private endpoint, zone redundancy, and the auto-Monitoring-Reader
  role grant.
version: 0.1.0
azure_services:
  - Microsoft.Dashboard/grafana
tags:
  - observability
  - grafana
  - dashboards
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/managed-grafana/overview
  - https://learn.microsoft.com/azure/managed-grafana/quickstart-managed-grafana-cli
  - https://learn.microsoft.com/azure/managed-grafana/how-to-permissions
  - https://learn.microsoft.com/azure/managed-grafana/how-to-private-endpoints
  - https://learn.microsoft.com/azure/managed-grafana/how-to-monitor-managed-grafana-workspace
  - https://learn.microsoft.com/azure/managed-grafana/how-to-api-calls
  - https://learn.microsoft.com/azure/templates/microsoft.dashboard/grafana
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2024-10-01"
last_reviewed: 2026-05-11
---

# Azure Managed Grafana (secure baseline)

## When to use this skill

- The user wants Grafana dashboards over Azure Monitor metrics + logs +
  Azure Managed Prometheus, without running Grafana themselves.
- The user wants Entra ID for Grafana RBAC (admin/editor/viewer mapped to
  Entra users/groups).

## When NOT to use this skill

- The user only needs Azure-native dashboards — see
  [`azure-monitor-workbooks`](../azure-monitor-workbooks/SKILL.md).
- Self-hosted Grafana is required (custom plugins not in the supported
  set, custom auth) — run Grafana on AKS/Container Apps/VM yourself.

## Tier picker

> **Essential is being retired** in favor of Standard. Don't pick
> Essential for new workspaces. Standard is the only tier that supports
> zone redundancy, private endpoints, deterministic outbound IPs,
> alerting, SMTP, reporting, and the full plugin set.

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| `sku.name` | `'Standard'` | Essential is deprecated. |
| `identity.type` | `'SystemAssigned'` | Required for Azure Monitor / AMW data source MI auth. |
| `properties.apiKey` | `'Disabled'` (default) | Service accounts can replace API keys; only enable if you genuinely need them. |
| `properties.publicNetworkAccess` | `'Disabled'` (default `'Enabled'`) | Pair with private endpoint. **Note:** Entra ID OAuth still traverses public internet even in private mode — only data-plane is restricted. |
| `properties.zoneRedundancy` | `'Enabled'` | HA across AZs. |
| `properties.deterministicOutboundIP` | `'Disabled'` (default) — `'Enabled'` only if data sources require IP allow-listing | Standard-only. |
| `properties.grafanaMajorVersion` | `'11'` | Pin to a major; Microsoft auto-patches minor versions. |
| `properties.grafanaConfigurations.security.csrfAlwaysCheck` | `true` | Hardened CSRF check. |
| Workspace MI roles | `Monitoring Reader` on subscription (Azure Monitor metrics + logs) and `Monitoring Data Reader` on each Azure Monitor Workspace (Prometheus) | These are different roles — assign both as needed. |
| Grafana Admin / Editor / Viewer | assign to **Entra groups** at the workspace resource scope | Avoid per-user grants. |

## Recipe — Azure CLI

```bash
RG=rg-grafana-prod
LOC=eastus
GRAFANA=amg-app-prod

az group create -n "$RG" -l "$LOC"

# 1. Standard workspace (system MI auto-on)
az grafana create -g "$RG" -n "$GRAFANA" -l "$LOC"

# 2. Workspace MI gets Monitoring Reader on the subscription (Azure Monitor data source)
GRAFANA_MI=$(az grafana show -g "$RG" -n "$GRAFANA" --query identity.principalId -o tsv)
SUB=$(az account show --query id -o tsv)
az role assignment create \
  --assignee-object-id "$GRAFANA_MI" --assignee-principal-type ServicePrincipal \
  --role "Monitoring Reader" --scope "/subscriptions/$SUB"

# 3. Grant Grafana Admin to a team Entra group (workspace-scope)
GRAFANA_ID=$(az grafana show -g "$RG" -n "$GRAFANA" --query id -o tsv)
az role assignment create \
  --assignee-object-id <admin-group-objectid> --assignee-principal-type Group \
  --role "Grafana Admin" --scope "$GRAFANA_ID"

# 4. (Optional) connect Azure Monitor Workspace (Prometheus)
AMW_ID=/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.Monitor/accounts/<amw-name>
az role assignment create \
  --assignee-object-id "$GRAFANA_MI" --assignee-principal-type ServicePrincipal \
  --role "Monitoring Data Reader" --scope "$AMW_ID"
# Then add the AMW integration via Bicep grafanaIntegrations or in the portal

# 5. Disable public network access (after PE provisioned)
az grafana update -g "$RG" -n "$GRAFANA" --public-network-access Disabled
```

## Recipe — Bicep

```bicep
param grafanaName string
param location string = resourceGroup().location
param amwResourceId string = ''   // Azure Monitor Workspace resource ID for Prometheus

resource grafana 'Microsoft.Dashboard/grafana@2024-10-01' = {
  name: grafanaName
  location: location
  identity: { type: 'SystemAssigned' }
  sku: { name: 'Standard' }
  properties: {
    apiKey: 'Disabled'
    publicNetworkAccess: 'Disabled'
    deterministicOutboundIP: 'Disabled'
    zoneRedundancy: 'Enabled'
    grafanaMajorVersion: '11'
    grafanaConfigurations: { security: { csrfAlwaysCheck: true } }
    grafanaIntegrations: {
      azureMonitorWorkspaceIntegrations: empty(amwResourceId) ? [] : [
        { azureMonitorWorkspaceResourceId: amwResourceId }
      ]
    }
  }
}

// Auto-grant Monitoring Reader at subscription scope
resource monitoringReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(subscription().id, grafana.id, 'Monitoring Reader')
  scope: subscription()
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '43d0d8ad-25c7-4714-9337-8ba259a9fe05'   // Monitoring Reader
    )
    principalId: grafana.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

output endpoint string = grafana.properties.endpoint
```

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| Dashboards say "No data" | Workspace MI lacks `Monitoring Reader` on the target sub/RG | Grant the role. |
| Cannot open Grafana UI after disabling public access | No path to the private endpoint | Use Bastion, VPN, or a VM in the VNet. **OAuth sign-in still goes over the internet — only data plane is private.** |
| "Pin to Grafana" from the portal fails after enabling private mode | The Azure portal can't reach the private Grafana endpoint | Known limitation; pin from Grafana itself. |
| Plugin install fails | You're on Essential, which restricts plugins | Migrate to Standard. |
| Service account token doesn't work | API keys / service accounts aren't enabled | Set `apiKey: 'Enabled'` (or via portal). |
| Prometheus dashboards empty | Workspace MI has `Monitoring Reader` but not `Monitoring Data Reader` on the AMW | Grant `Monitoring Data Reader` on the AMW. |
| User who created via CLI can't open the UI | CLI doesn't auto-grant Grafana Admin | `az role assignment create --role "Grafana Admin" --scope <grafana-id>`. |

## References

- [Managed Grafana overview](https://learn.microsoft.com/azure/managed-grafana/overview)
- [Quickstart (CLI)](https://learn.microsoft.com/azure/managed-grafana/quickstart-managed-grafana-cli)
- [Permissions](https://learn.microsoft.com/azure/managed-grafana/how-to-permissions)
- [Private endpoints](https://learn.microsoft.com/azure/managed-grafana/how-to-private-endpoints)
- [Monitor the workspace](https://learn.microsoft.com/azure/managed-grafana/how-to-monitor-managed-grafana-workspace)
- [API calls](https://learn.microsoft.com/azure/managed-grafana/how-to-api-calls)
- [`Microsoft.Dashboard/grafana` template](https://learn.microsoft.com/azure/templates/microsoft.dashboard/grafana)
