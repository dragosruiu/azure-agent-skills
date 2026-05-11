---
name: azure-container-apps
description: >
  Provision Azure Container Apps with secure defaults: workload-profiles
  environment, user-assigned managed identity for ACR pull, Key Vault
  reference secrets with auto-rotation, KEDA scaling using identity (not
  secrets), and HTTPS-only ingress.
version: 0.1.0
azure_services:
  - Microsoft.App/managedEnvironments
  - Microsoft.App/containerApps
  - Microsoft.ManagedIdentity/userAssignedIdentities
tags:
  - compute
  - containers
  - keda
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/container-apps/overview
  - https://learn.microsoft.com/azure/container-apps/managed-identity
  - https://learn.microsoft.com/azure/container-apps/managed-identity-image-pull
  - https://learn.microsoft.com/azure/container-apps/ingress-overview
  - https://learn.microsoft.com/azure/container-apps/ingress-how-to
  - https://learn.microsoft.com/azure/container-apps/scale-app
  - https://learn.microsoft.com/azure/container-apps/manage-secrets
  - https://learn.microsoft.com/azure/container-apps/revisions
  - https://learn.microsoft.com/azure/container-apps/workload-profiles-overview
  - https://learn.microsoft.com/azure/container-apps/environment
  - https://learn.microsoft.com/azure/container-apps/vnet-custom
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2026-01-01"
last_reviewed: 2026-05-11
---

# Azure Container Apps (secure baseline)

## When to use this skill

- The user is shipping a containerized HTTP service or worker.
- The user wants KEDA-based scaling on queue length, CPU, HTTP RPS, etc.
- The user wants blue/green or traffic-split deployments via revisions.
- The user wants Dapr sidecars, init containers, or per-app workload
  profiles.

## When NOT to use this skill

- Workload needs cluster-level features (CRDs, custom CNI, GPUs you
  configure yourself, DaemonSets) — use AKS.
- Workload is a single static web site — use Static Web Apps or App
  Service with a built-in runtime.

## Prerequisites

- `az extension add --name containerapp --upgrade` (the CLI subcommands
  ship as an extension).
- `az provider register --namespace Microsoft.App && az provider register --namespace Microsoft.OperationalInsights`.
- An Azure Container Registry containing the image (or use a public
  image to start).
- A user-assigned managed identity (preferred for ACR pull) — see
  [`identity-and-access/azure-managed-identity`](../../identity-and-access/azure-managed-identity/SKILL.md).

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| Environment type | **Workload profiles** (default for `az containerapp env create`) | Init containers can access MI here; the legacy Consumption-only env can't. ([Source](https://learn.microsoft.com/azure/container-apps/managed-identity)) |
| `ingress.allowInsecure` | `false` (default) | Keeps HTTP→HTTPS redirect. |
| `ingress.transport` | `'auto'` (default) | Detects HTTP/1 vs HTTP/2. |
| `ingress.targetPort` | the port the container *actually* listens on | Mismatch = 502 Bad Gateway. |
| `ingress.external` | `false` for backend services | Only set `true` if the app must be public. |
| `template.scale.minReplicas` | `1` for latency-sensitive apps, `0` for batch / burst | `0` saves cost but cold-starts. |
| `template.scale.maxReplicas` | `10` (default) — raise up to `1000` | Bound the scale-out. |
| ACR pull | User-assigned MI on `registry.identity` | No registry password. **Requires `az acr config authentication-as-arm update --status enabled`.** |
| Key Vault reference secrets | Versionless `keyVaultUrl` + MI in `secrets[].identity` | Auto-rotates within ~30 min. ([Source](https://learn.microsoft.com/azure/container-apps/manage-secrets)) |
| KEDA scale rules | `identity` field, **never** `auth` (secrets) | Use the MI; secrets-based KEDA auth is a regression. |
| `activeRevisionsMode` | `'Single'` (default) for zero-downtime rolling deploys; `'Multiple'` for traffic splitting | |
| Subnet for workload-profiles env | `/27` or larger; for legacy Consumption-only `/23` or larger | ([Source](https://learn.microsoft.com/azure/container-apps/vnet-custom)) |

## Recipe — Azure CLI

```bash
RG=rg-app-prod
LOC=eastus
ENV=cae-app-prod
APP=ca-app-prod
ACR=acrappprod
MI=id-app-acrpull

az extension add --name containerapp --upgrade
az provider register --namespace Microsoft.App
az provider register --namespace Microsoft.OperationalInsights

# 1. User-assigned MI for ACR pull (and Key Vault)
az identity create -g "$RG" -n "$MI" -l "$LOC"
MI_ID=$(az identity show -g "$RG" -n "$MI" --query id -o tsv)
MI_PRINCIPAL=$(az identity show -g "$RG" -n "$MI" --query principalId -o tsv)

# 2. Grant AcrPull on the registry, AND enable ARM-audience tokens on ACR (required)
ACR_ID=$(az acr show -n "$ACR" --query id -o tsv)
az role assignment create \
  --assignee-object-id "$MI_PRINCIPAL" \
  --assignee-principal-type ServicePrincipal \
  --role "AcrPull" --scope "$ACR_ID"
az acr config authentication-as-arm update --registry "$ACR" --status enabled

# 3. Container Apps environment (workload profiles — default)
az containerapp env create -g "$RG" -n "$ENV" -l "$LOC"

# 4. Container app with MI-based ACR pull
az containerapp create \
  -g "$RG" -n "$APP" --environment "$ENV" \
  --image "$ACR.azurecr.io/myimage:v1" \
  --target-port 8080 --ingress external \
  --min-replicas 1 --max-replicas 10 \
  --user-assigned "$MI_ID" \
  --registry-server "$ACR.azurecr.io" --registry-identity "$MI_ID"

# 5. HTTP scale rule (one replica per 100 concurrent requests)
az containerapp update -g "$RG" -n "$APP" \
  --scale-rule-name http-rule \
  --scale-rule-type http \
  --scale-rule-http-concurrency 100

# 6. Queue scale rule using MI (NOT a connection string)
az containerapp update -g "$RG" -n "$APP" \
  --scale-rule-name queue-rule \
  --scale-rule-type azure-queue \
  --scale-rule-metadata accountName=mystorage queueName=myqueue queueLength=5 \
  --scale-rule-identity "$MI_ID"
```

## Recipe — Bicep

```bicep
param location string = resourceGroup().location
param envName string
param appName string
param acrLoginServer string
param containerImage string
param keyVaultName string

resource acrPullIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-${appName}-acrpull'
  location: location
}

resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${envName}-logs'
  location: location
  properties: { sku: { name: 'PerGB2018' } }
}

resource caEnv 'Microsoft.App/managedEnvironments@2026-01-01' = {
  name: envName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: law.properties.customerId
        sharedKey: law.listKeys().primarySharedKey
      }
    }
    workloadProfiles: [
      { name: 'Consumption', workloadProfileType: 'Consumption' }
    ]
  }
}

resource app 'Microsoft.App/containerApps@2026-01-01' = {
  name: appName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${acrPullIdentity.id}': {} }
  }
  properties: {
    environmentId: caEnv.id
    configuration: {
      activeRevisionsMode: 'Single'
      registries: [
        { server: acrLoginServer, identity: acrPullIdentity.id }
      ]
      secrets: [
        {
          name: 'db-password'
          keyVaultUrl: 'https://${keyVaultName}.vault.azure.net/secrets/db-password'
          identity: acrPullIdentity.id
        }
      ]
      ingress: {
        external: true
        targetPort: 8080
        transport: 'auto'
        allowInsecure: false
        traffic: [ { latestRevision: true, weight: 100 } ]
      }
    }
    template: {
      containers: [
        {
          name: 'main'
          image: containerImage
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: [
            { name: 'DB_PASSWORD', secretRef: 'db-password' }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 10
        rules: [
          {
            name: 'http-rule'
            http: { metadata: { concurrentRequests: '100' } }
          }
          {
            name: 'queue-rule'
            azureQueue: {
              accountName: 'mystorage'
              queueName: 'myqueue'
              queueLength: 5
              identity: acrPullIdentity.id
            }
          }
        ]
      }
    }
  }
}
```

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| `Image pull failed` / `401 Unauthorized` from ACR | MI lacks `AcrPull`, OR ACR ARM-audience tokens are disabled | Grant `AcrPull`. Run `az acr config authentication-as-arm update --status enabled`. ([Source](https://learn.microsoft.com/azure/container-apps/managed-identity-image-pull)) |
| Revision shows `Running` but app returns 502 | `targetPort` doesn't match the container's actual listening port | Fix `targetPort`. Check container logs for the bind line. |
| Cold start latency on first request after idle | `minReplicas: 0` | Set `minReplicas: 1` if latency matters. |
| KV-backed secret is stale after rotating in Key Vault | `keyVaultUrl` includes a version → pinned | Remove the version (versionless URI auto-rotates within ~30 min). |
| Init containers cannot reach Key Vault / ACR | App is on the **legacy Consumption-only** env | Use a workload-profiles env (default for `az containerapp env create`). ([Source](https://learn.microsoft.com/azure/container-apps/managed-identity)) |
| `az containerapp env create` errors on subnet size | Subnet too small for workload profiles env | `/27` or larger for workload-profiles env; `/23` or larger for legacy. ([Source](https://learn.microsoft.com/azure/container-apps/vnet-custom)) |
| Queue scale rule returns 403 | Used the legacy `auth` (secret) shape instead of `identity` | Replace `auth` with `identity: '<MI-resource-id>'` (or `identity: 'system'`). |
| Traffic stays on old revision after deploy in `Multiple` mode | No `traffic` rule with `latestRevision: true` | Add the rule, or switch to `'Single'` mode. ([Source](https://learn.microsoft.com/azure/container-apps/revisions)) |

## References

- [Container Apps overview](https://learn.microsoft.com/azure/container-apps/overview)
- [Managed identity in Container Apps](https://learn.microsoft.com/azure/container-apps/managed-identity)
- [MI-based image pull from ACR](https://learn.microsoft.com/azure/container-apps/managed-identity-image-pull)
- [Ingress overview](https://learn.microsoft.com/azure/container-apps/ingress-overview)
- [Ingress how-to](https://learn.microsoft.com/azure/container-apps/ingress-how-to)
- [Scaling rules](https://learn.microsoft.com/azure/container-apps/scale-app)
- [Manage secrets (Key Vault references)](https://learn.microsoft.com/azure/container-apps/manage-secrets)
- [Revisions and revision modes](https://learn.microsoft.com/azure/container-apps/revisions)
- [Workload profiles overview](https://learn.microsoft.com/azure/container-apps/workload-profiles-overview)
- [Custom VNet](https://learn.microsoft.com/azure/container-apps/vnet-custom)
