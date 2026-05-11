---
name: azure-functions
description: >
  Provision an Azure Function App on the Flex Consumption plan with
  identity-based AzureWebJobsStorage (no connection string), connection-
  string-based Application Insights ingestion (not the deprecated
  instrumentation key), and Entra-based App Insights auth.
version: 0.1.0
azure_services:
  - Microsoft.Web/sites
  - Microsoft.Web/serverfarms
tags:
  - compute
  - serverless
  - functions
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/azure-functions/flex-consumption-plan
  - https://learn.microsoft.com/azure/azure-functions/flex-consumption-how-to
  - https://learn.microsoft.com/azure/azure-functions/functions-app-settings
  - https://learn.microsoft.com/azure/azure-functions/storage-considerations
  - https://learn.microsoft.com/azure/azure-functions/functions-identity-based-connections-tutorial
  - https://learn.microsoft.com/azure/azure-functions/functions-bindings-storage-blob-trigger
  - https://learn.microsoft.com/azure/azure-functions/functions-networking-options
  - https://learn.microsoft.com/azure/templates/microsoft.web/sites
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2025-03-01"
last_reviewed: 2026-05-11
---

# Azure Functions (Flex Consumption, secure baseline)

## When to use this skill

- The user is building event-driven, short-lived, scale-to-zero compute
  in .NET isolated, Node, Python, Java, or PowerShell.
- The user needs VNet integration and/or private endpoints — Flex
  Consumption supports both, the legacy Consumption plan does not.
- The user wants per-function scaling and configurable instance memory
  (512 / 2048 / 4096 MB).

## When NOT to use this skill

- The workload needs **in-process .NET** — Flex Consumption supports
  **isolated worker only**. Use Premium plan if you can't migrate.
- The workload needs the **polling** blob trigger — Flex Consumption
  supports **only** the event-based (Event Grid) blob trigger. ([Source](https://learn.microsoft.com/azure/azure-functions/functions-bindings-storage-blob-trigger))
- The workload is Windows-only — Flex Consumption is **Linux only**.

## Prerequisites

- Azure CLI `>= 2.60.0` (required for `--flexconsumption-location`).
- A backing Storage account (used for deployment artifacts and host
  state). Configure with secure defaults — see [`data/azure-storage-account`](../../data/azure-storage-account/SKILL.md).
- An Application Insights resource (workspace-based) — see
  [`observability/azure-application-insights`](../../observability/azure-application-insights/SKILL.md).
- The Flex Consumption plan is not GA in every region — check first:
  ```bash
  az functionapp list-flexconsumption-locations \
    --query "sort_by(@, &name)[].{Region:name}" -o table
  ```

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| `--flexconsumption-location <region>` | (no `--plan`) | Triggers Flex Consumption plan creation. **Don't pass `--consumption-plan-location` (legacy) or `--plan` (Premium/Dedicated).** |
| `--runtime` | `dotnet-isolated` (or `node`, `python`, `java`, `powershell`) | In-process .NET is unsupported. |
| `AzureWebJobsStorage__accountName` | `<storage account name>` | Identity-based connection. Remove the `AzureWebJobsStorage` connection string. |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | full connection string | **Required** in sovereign clouds. Do **not** use `APPINSIGHTS_INSTRUMENTATIONKEY`. |
| `APPLICATIONINSIGHTS_AUTHENTICATION_STRING` | `Authorization=AAD` (system MI) or `Authorization=AAD;ClientId=<client-id>` (user MI) | Entra-based App Insights ingestion — no local keys. Requires `Monitoring Metrics Publisher` role on the AI resource. |
| `httpsOnly` / `--https-only` | `true` | Enforce HTTPS. |
| `siteConfig.minTlsVersion` | `'1.2'` | TLS 1.2+. |
| `siteConfig.ftpsState` | `'Disabled'` | No FTP. |
| `identity.type` | `'SystemAssigned'` | MI for storage / KV / AI auth. |
| `functionAppConfig.scaleAndConcurrency.instanceMemoryMB` | `2048` (default) | Pick `512` for tiny workloads, `4096` for memory-heavy. |

## Required RBAC for identity-based AzureWebJobsStorage

The function app's MI needs all of these on the backing storage account
([source](https://learn.microsoft.com/azure/azure-functions/storage-considerations)):

- `Storage Blob Data Owner` — for deployment package & host state
- `Storage Queue Data Contributor` — for queue triggers and host queues
- `Storage Table Data Contributor` — for diagnostics / task hub state

## Recipe — Azure CLI

```bash
RG=rg-app-prod
LOC=eastus
SA=stappprod$RANDOM
APP=func-app-prod
AI=appi-app-prod

# 1. Storage account (configure per `data/azure-storage-account`; minimal here)
az storage account create -g "$RG" -n "$SA" -l "$LOC" \
  --sku Standard_LRS --allow-blob-public-access false

# 2. Function app on Flex Consumption (.NET isolated)
az functionapp create \
  -g "$RG" -n "$APP" \
  --storage-account "$SA" \
  --flexconsumption-location "$LOC" \
  --runtime dotnet-isolated --runtime-version 8.0

# 3. Enable system-assigned MI
az functionapp identity assign -g "$RG" -n "$APP"

PRINCIPAL=$(az functionapp identity show -g "$RG" -n "$APP" --query principalId -o tsv)
SA_ID=$(az storage account show -g "$RG" -n "$SA" --query id -o tsv)

# 4. Grant the MI the storage roles required by identity-based AzureWebJobsStorage
for ROLE in "Storage Blob Data Owner" "Storage Queue Data Contributor" "Storage Table Data Contributor"; do
  az role assignment create \
    --assignee-object-id "$PRINCIPAL" \
    --assignee-principal-type ServicePrincipal \
    --role "$ROLE" --scope "$SA_ID"
done

# 5. Switch AzureWebJobsStorage to identity-based and configure App Insights
APPI_CONN=$(az monitor app-insights component show -g "$RG" -a "$AI" --query connectionString -o tsv)
az functionapp config appsettings set -g "$RG" -n "$APP" --settings \
  "AzureWebJobsStorage__accountName=$SA" \
  "APPLICATIONINSIGHTS_CONNECTION_STRING=$APPI_CONN" \
  "APPLICATIONINSIGHTS_AUTHENTICATION_STRING=Authorization=AAD"

# Remove the old AzureWebJobsStorage connection string if present
az functionapp config appsettings delete -g "$RG" -n "$APP" \
  --setting-names AzureWebJobsStorage

# 6. Grant Monitoring Metrics Publisher on App Insights for Entra-based ingestion
AI_ID=$(az monitor app-insights component show -g "$RG" -a "$AI" --query id -o tsv)
az role assignment create \
  --assignee-object-id "$PRINCIPAL" \
  --assignee-principal-type ServicePrincipal \
  --role "Monitoring Metrics Publisher" --scope "$AI_ID"
```

## Recipe — Bicep

```bicep
// Some Flex Consumption schema fields (deployment.storage.authentication.type
// allowed string values, the FlexConsumption SKU name) are not enumerated in
// the public template reference text at the time of writing. Confirm against
// the official Flex Consumption Bicep samples:
//   https://github.com/Azure-Samples/azure-functions-flex-consumption-samples

param funcAppName string
param location string = resourceGroup().location
param storageAccountName string
param appInsightsConnectionString string

resource flexPlan 'Microsoft.Web/serverfarms@2025-03-01' = {
  name: '${funcAppName}-plan'
  location: location
  kind: 'functionapp'
  sku: { tier: 'FlexConsumption', name: 'FC1' }
  properties: { reserved: true }
}

resource funcApp 'Microsoft.Web/sites@2025-03-01' = {
  name: funcAppName
  location: location
  kind: 'functionapp,linux'
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: flexPlan.id
    httpsOnly: true
    siteConfig: {
      minTlsVersion: '1.2'
      ftpsState: 'Disabled'
      appSettings: [
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsightsConnectionString }
        { name: 'AzureWebJobsStorage__accountName', value: storageAccountName }
        { name: 'APPLICATIONINSIGHTS_AUTHENTICATION_STRING', value: 'Authorization=AAD' }
      ]
    }
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: 'https://${storageAccountName}.blob.core.windows.net/deployments'
          authentication: { type: 'SystemAssignedIdentity' }
        }
      }
      runtime: { name: 'dotnet-isolated', version: '8.0' }
      scaleAndConcurrency: {
        instanceMemoryMB: 2048
        maximumInstanceCount: 100
        alwaysReady: []   // empty = scale to zero
      }
    }
  }
}
```

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| Host won't start; logs show `403 Forbidden` on storage | MI missing one of the three required storage roles | Grant **all three**: Blob Data Owner + Queue Data Contributor + Table Data Contributor on the storage account. ([Source](https://learn.microsoft.com/azure/azure-functions/storage-considerations)) |
| App Insights shows nothing | `APPINSIGHTS_INSTRUMENTATIONKEY` set instead of `APPLICATIONINSIGHTS_CONNECTION_STRING` | Replace with the connection string. The instrumentation key is deprecated and unsupported in sovereign clouds. ([Source](https://learn.microsoft.com/azure/azure-functions/functions-app-settings)) |
| App Insights data disappears after enabling Entra auth | `APPLICATIONINSIGHTS_AUTHENTICATION_STRING=Authorization=AAD` set but MI lacks `Monitoring Metrics Publisher` on the AI resource | Grant the role on the AI resource (not the workspace). |
| Blob trigger never fires on Flex Consumption | Polling-based trigger; Flex only supports event-based | Use the Event Grid blob trigger (`source = "EventGrid"` binding parameter). |
| `az functionapp create` errors with "region not supported" | Flex Consumption isn't GA everywhere | `az functionapp list-flexconsumption-locations` and pick a supported region. |
| `az functionapp create` errors with "in-process model not supported" | Used `--runtime dotnet` (in-process) | Switch to `--runtime dotnet-isolated`. |

## References

- [Flex Consumption plan overview](https://learn.microsoft.com/azure/azure-functions/flex-consumption-plan)
- [Flex Consumption: how-to guide](https://learn.microsoft.com/azure/azure-functions/flex-consumption-how-to)
- [Functions app settings reference](https://learn.microsoft.com/azure/azure-functions/functions-app-settings)
- [Storage considerations for Functions](https://learn.microsoft.com/azure/azure-functions/storage-considerations)
- [Identity-based connections tutorial](https://learn.microsoft.com/azure/azure-functions/functions-identity-based-connections-tutorial)
- [Blob storage trigger (Flex notes)](https://learn.microsoft.com/azure/azure-functions/functions-bindings-storage-blob-trigger)
- [Functions networking options](https://learn.microsoft.com/azure/azure-functions/functions-networking-options)
