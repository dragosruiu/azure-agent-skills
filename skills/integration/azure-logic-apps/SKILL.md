---
name: azure-logic-apps
description: >
  Provision Logic Apps Standard (single-tenant) with the required app
  settings (`APP_KIND=workflowApp`, `FUNCTIONS_EXTENSION_VERSION=~4`,
  etc.), system-assigned MI, Key Vault references for connection
  secrets, VNet integration + private endpoint, and Workflow Standard
  WS-tier App Service plan (Windows only).
version: 0.1.0
azure_services:
  - Microsoft.Web/sites          # kind: workflowapp
  - Microsoft.Web/serverfarms    # WS-series (Workflow Standard)
  - Microsoft.Web/connections    # managed API connections
tags:
  - integration
  - workflows
  - serverless
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/logic-apps/single-tenant-overview-compare
  - https://learn.microsoft.com/azure/logic-apps/create-single-tenant-workflows-azure-portal
  - https://learn.microsoft.com/azure/logic-apps/edit-app-settings-host-settings
  - https://learn.microsoft.com/azure/logic-apps/secure-single-tenant-workflow-virtual-network-private-endpoint
  - https://learn.microsoft.com/azure/logic-apps/authenticate-with-managed-identity
  - https://learn.microsoft.com/azure/logic-apps/connectors/managed
  - https://learn.microsoft.com/azure/logic-apps/connectors/built-in
  - https://learn.microsoft.com/azure/app-service/app-service-key-vault-references
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2022-03-01"
last_reviewed: 2026-05-11
---

# Azure Logic Apps Standard (single-tenant)

## When to use this skill

- The user wants a workflow with multiple actions, retries, conditional
  branches, and connectors to SaaS / Azure services.
- The user needs VNet integration and / or private endpoints (only
  Standard supports them).
- The user wants stateless workflows for low-latency request/response.

## When NOT to use this skill

- The workload is small custom code → an Azure Function is simpler.
- A single trigger fans out events to many subscribers → Event Grid.
- Strict exactly-once command processing → Service Bus.

## Standard vs Consumption (the picker)

| Need | Pick |
| --- | --- |
| Multiple workflows in one app, lower per-execution cost at scale, VNet integration / PE | **Standard** |
| Pay-per-execution, simplest, no infrastructure | Consumption |
| Local dev in VS Code | **Standard** |

**Standard is Windows-only.** Don't pick a Linux App Service plan.

## Required app settings (verified)

| Setting | Value | Notes |
| --- | --- | --- |
| `APP_KIND` | `workflowApp` | If missing, "Execute JavaScript Code" and other built-in actions fail. |
| `AzureWebJobsStorage` | Storage connection string | Backend storage for state and history. |
| `FUNCTIONS_EXTENSION_VERSION` | `~4` | Underlying Functions runtime. |
| `FUNCTIONS_WORKER_RUNTIME` | `dotnet` | Standard now requires `dotnet` (was `node` historically). |
| `WEBSITE_CONTENTAZUREFILECONNECTIONSTRING` | Storage connection string | Code share. |
| `WEBSITE_CONTENTSHARE` | autogen | File share name. |
| `WEBSITE_NODE_DEFAULT_VERSION` | `~18` | Node version for inline JS actions. |

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| App Service plan SKU | `WS1`/`WS2`/`WS3` (Workflow Standard) on a **Windows** plan | Logic Apps Standard requires Windows. |
| `identity.type` | `'SystemAssigned'` | Standard auto-enables system MI. Verify and use it. |
| App settings as Key Vault references | `@Microsoft.KeyVault(SecretUri=https://...)` or `@Microsoft.KeyVault(VaultName=...;SecretName=...)` | Centralizes secrets; auto-refreshes ~24 h. |
| MI on Key Vault | `Key Vault Secrets User` | Required for KV references to resolve. |
| `WEBSITE_SKIP_CONTENTSHARE_VALIDATION` | `1` | Avoids validation failures when `WEBSITE_CONTENTAZUREFILECONNECTIONSTRING` itself is a KV reference. |
| Private endpoint (inbound) | groupId `sites`; expect `403 Forbidden` from public URL after enabling | Test from a VM in the same VNet. |
| VNet integration (outbound) subnet | `/27` minimum, **`/26` recommended**; **immutable size after assignment** | Plan accordingly. |
| `vnetRouteAllEnabled` | `true` when KV is private | Routes outbound through the VNet so KV references work. |
| Inbound port requirements when backend Storage is private | TCP 443 (Storage), 445 (SMB), 20000–30000 (worker IPC) | Don't block these in NSGs. |
| Connectors picker | prefer **built-in** (in-process) over **managed** (separate API connection resource) when both exist | Built-in connectors avoid the `Microsoft.Web/connections` external dependency. |
| Managed connector outbound | allow outbound to managed connector IPs for the region | NSG / UDR / Firewall can break managed connectors. |

> **`WEBSITE_RUN_FROM_PACKAGE` warning:** the docs say to **remove** this
> setting (or set to `0`) when using GitHub integration with a private
> endpoint. Don't set it to `1` blindly.

## Recipe — Azure CLI

```bash
RG=rg-la-prod
LOC=eastus
PLAN=plan-la-prod
APP=la-app-prod
SA=stlaappprod$RANDOM

# 1. Workflow Standard (WS1) plan — Windows
az appservice plan create -g "$RG" -n "$PLAN" -l "$LOC" --sku WS1
# (No --is-linux: Standard requires Windows)

# 2. Storage account for state
az storage account create -g "$RG" -n "$SA" -l "$LOC" \
  --sku Standard_LRS --allow-blob-public-access false
SA_CONN=$(az storage account show-connection-string -g "$RG" -n "$SA" --query connectionString -o tsv)

# 3. Logic App Standard (kind = functionapp,workflowapp)
az logicapp create -g "$RG" -n "$APP" --plan "$PLAN" \
  --storage-account "$SA"

# 4. Required app settings
az webapp config appsettings set -g "$RG" -n "$APP" --settings \
  APP_KIND=workflowApp \
  FUNCTIONS_EXTENSION_VERSION=~4 \
  FUNCTIONS_WORKER_RUNTIME=dotnet \
  WEBSITE_NODE_DEFAULT_VERSION=~18

# 5. System MI (Standard auto-enables; assert it)
az webapp identity assign -g "$RG" -n "$APP"
PRINCIPAL=$(az webapp identity show -g "$RG" -n "$APP" --query principalId -o tsv)

# 6. Grant MI Key Vault Secrets User
KV_ID=$(az keyvault show -g "$RG" -n kv-la-prod --query id -o tsv)
az role assignment create \
  --assignee-object-id "$PRINCIPAL" --assignee-principal-type ServicePrincipal \
  --role "Key Vault Secrets User" --scope "$KV_ID"

# 7. App setting as a Key Vault reference (auto-refreshed by App Service ~24 h)
az webapp config appsettings set -g "$RG" -n "$APP" --settings \
  "DB_PASSWORD=@Microsoft.KeyVault(VaultName=kv-la-prod;SecretName=db-password)"

# 8. VNet integration (outbound) — subnet must be empty + delegated to Microsoft.Web/serverFarms
az webapp vnet-integration add -g "$RG" -n "$APP" --vnet vnet-app --subnet snet-la
az webapp config set -g "$RG" -n "$APP" --generic-configurations '{"vnetRouteAllEnabled": true}'

# 9. Private endpoint (inbound) — groupId 'sites', zone privatelink.azurewebsites.net
APP_ID=$(az webapp show -g "$RG" -n "$APP" --query id -o tsv)
az network private-endpoint create -g "$RG" -n "pe-$APP" \
  --vnet-name vnet-app --subnet snet-pe \
  --private-connection-resource-id "$APP_ID" \
  --connection-name "pec-$APP" --group-id sites
```

## Recipe — Bicep (skeleton; verify API versions)

```bicep
param logicAppName string
param location string = resourceGroup().location
param storageAccountName string

resource plan 'Microsoft.Web/serverfarms@2022-03-01' = {
  name: '${logicAppName}-plan'
  location: location
  sku: { name: 'WS1', tier: 'WorkflowStandard' }
  // Windows (no `kind: 'linux'`, no `properties.reserved: true`)
}

resource site 'Microsoft.Web/sites@2022-03-01' = {
  name: logicAppName
  location: location
  kind: 'functionapp,workflowapp'
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      minTlsVersion: '1.2'
      ftpsState: 'Disabled'
      appSettings: [
        { name: 'APP_KIND',                       value: 'workflowApp' }
        { name: 'FUNCTIONS_EXTENSION_VERSION',    value: '~4' }
        { name: 'FUNCTIONS_WORKER_RUNTIME',       value: 'dotnet' }
        { name: 'AzureWebJobsStorage',            value: storageAccountConnString }
        { name: 'WEBSITE_CONTENTAZUREFILECONNECTIONSTRING', value: storageAccountConnString }
        { name: 'WEBSITE_CONTENTSHARE',           value: toLower(logicAppName) }
        { name: 'WEBSITE_NODE_DEFAULT_VERSION',   value: '~18' }
      ]
    }
  }
}
```

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| `Execute JavaScript Code` action fails | Missing `APP_KIND=workflowApp` | Add the setting; restart. |
| Public URL returns 403 after enabling private endpoint | Expected — that's the point | Test from inside the VNet (or via a peered VNet). |
| Workflow can't reach Key Vault behind a PE | `vnetRouteAllEnabled: false` (so outbound goes via the App Service multi-tenant gateway) | Set `vnetRouteAllEnabled: true` and ensure the VNet has a path to KV. |
| Connector to Storage fails 401 even with MI | Built-in HTTP supports system MI but **not user-assigned MI** to firewalled Storage | Use system MI, or use the managed Azure Blob connector. |
| GitHub integration deploys but workflows don't appear | `WEBSITE_RUN_FROM_PACKAGE=1` set | Remove the setting (or set `0`) for GitHub-integrated deploys. |
| `WEBSITE_CONTENTAZUREFILECONNECTIONSTRING` as a KV reference fails validation | KV reference resolved later than the validation | Set `WEBSITE_SKIP_CONTENTSHARE_VALIDATION=1`. |
| Picked a Linux App Service plan | Standard Logic Apps require Windows | Recreate the plan without `--is-linux`. |
| Picked a non-WS SKU (P1V3 etc.) | Standard Logic Apps require WS-series | Use `WS1` / `WS2` / `WS3` SKU. |

## References

- [Standard vs Consumption](https://learn.microsoft.com/azure/logic-apps/single-tenant-overview-compare)
- [Create Standard workflows (portal)](https://learn.microsoft.com/azure/logic-apps/create-single-tenant-workflows-azure-portal)
- [App settings & host settings](https://learn.microsoft.com/azure/logic-apps/edit-app-settings-host-settings)
- [VNet + private endpoint](https://learn.microsoft.com/azure/logic-apps/secure-single-tenant-workflow-virtual-network-private-endpoint)
- [Authenticate with managed identity](https://learn.microsoft.com/azure/logic-apps/authenticate-with-managed-identity)
- [Built-in connectors](https://learn.microsoft.com/azure/logic-apps/connectors/built-in)
- [Managed connectors](https://learn.microsoft.com/azure/logic-apps/connectors/managed)
- [App Service Key Vault references](https://learn.microsoft.com/azure/app-service/app-service-key-vault-references)
