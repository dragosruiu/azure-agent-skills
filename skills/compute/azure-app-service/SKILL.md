---
name: azure-app-service
description: >
  Provision an Azure App Service (Linux Web App) with secure defaults:
  HTTPS-only, TLS 1.2+, FTP disabled, Always On, system-assigned managed
  identity, Key Vault references for secrets, and an authV2 (Easy Auth)
  hook for Microsoft Entra sign-in.
version: 0.1.0
azure_services:
  - Microsoft.Web/serverfarms
  - Microsoft.Web/sites
  - Microsoft.Web/sites/slots
tags:
  - compute
  - web
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/app-service/quickstart-arm-template
  - https://learn.microsoft.com/azure/app-service/overview-managed-identity
  - https://learn.microsoft.com/azure/app-service/configure-authentication-provider-aad
  - https://learn.microsoft.com/azure/app-service/app-service-key-vault-references
  - https://learn.microsoft.com/azure/app-service/configure-ssl-bindings
  - https://learn.microsoft.com/azure/app-service/deploy-staging-slots
  - https://learn.microsoft.com/azure/app-service/configure-vnet-integration-enable
  - https://learn.microsoft.com/azure/app-service/configure-common
  - https://learn.microsoft.com/azure/templates/microsoft.web/sites
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2025-03-01"
last_reviewed: 2026-05-11
---

# Azure App Service (Linux Web App, secure baseline)

## When to use this skill

- The user is shipping a stateless HTTP API or web UI in any of the
  built-in runtimes (Node, Python, .NET, Java, Ruby, PHP, custom container).
- The user needs deployment slots for blue/green or canary.
- The user wants Microsoft Entra sign-in for the app without writing
  auth middleware (Easy Auth v2).

## When NOT to use this skill

- Workload is event-driven and benefits from scale-to-zero — use Azure
  Functions on Flex Consumption instead.
- Workload is already containerized as a microservice with KEDA scaling
  needs — use Azure Container Apps instead.
- Workload needs cluster-level features (DaemonSets, custom CNI, GPUs) —
  use AKS.

## Prerequisites

- Azure CLI `>= 2.60.0`.
- For `az webapp auth ...` (Easy Auth v2): `az extension add --name authV2`.
- An existing Microsoft Entra app registration if you plan to use Easy Auth.
- A Key Vault with RBAC enabled if you'll use Key Vault references —
  see [`identity-and-access/azure-key-vault`](../../identity-and-access/azure-key-vault/SKILL.md).

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| `httpsOnly` / `--https-only` | `true` | Redirect all HTTP→HTTPS. |
| `siteConfig.minTlsVersion` / `--min-tls-version` | `'1.2'` | PCI-DSS minimum; current platform default. |
| `siteConfig.ftpsState` / `--ftps-state` | `'Disabled'` | No unencrypted FTP. Use `'FtpsOnly'` only if FTP is genuinely required. |
| `siteConfig.alwaysOn` / `--always-on` | `true` | Prevents cold starts. **Requires Basic B1 SKU or higher.** |
| `identity.type` / `--assign-identity` | `'SystemAssigned'` | Managed identity for downstream auth. |
| `properties.publicNetworkAccess` | `'Disabled'` | Combine with a private endpoint to block public ingress. Only do this when you have a frontdoor / app gateway / VNet path in place. |
| Basic publishing credentials (FTP/SCM password) | **disabled by default** since API `2024-11-01` | Tooling that uses FTP/SCM passwords will fail on new resources — that's the point. |
| Key Vault references in app settings | `@Microsoft.KeyVault(VaultName=<vault>;SecretName=<name>)` (versionless = auto-rotate within 24 h) | Avoids storing secrets in app settings. |
| App Service Plan `kind` / `properties.reserved` | `'linux'` / `true` | **`reserved: true` is required for Linux.** Omitting silently creates a Windows plan. |

## Recipe — Azure CLI

```bash
RG=rg-app-prod
LOC=eastus
PLAN=plan-app-prod
APP=app-app-prod
KV=kv-app-prod

# 1. Linux App Service Plan (P1V3 supports Always On + slots)
az appservice plan create \
  -g "$RG" -n "$PLAN" -l "$LOC" --sku P1V3 --is-linux

# 2. Web App with system-assigned MI
az webapp create \
  -g "$RG" -n "$APP" --plan "$PLAN" \
  --runtime "NODE:20-lts" \
  --assign-identity '[system]'

# 3. Harden the runtime
az webapp config set -g "$RG" -n "$APP" \
  --min-tls-version 1.2 \
  --ftps-state Disabled \
  --always-on true
az webapp update -g "$RG" -n "$APP" --https-only true

# 4. Grant the MI Key Vault Secrets User on a vault
PRINCIPAL_ID=$(az webapp identity show -g "$RG" -n "$APP" --query principalId -o tsv)
KV_ID=$(az keyvault show -g "$RG" -n "$KV" --query id -o tsv)
az role assignment create \
  --assignee-object-id "$PRINCIPAL_ID" \
  --assignee-principal-type ServicePrincipal \
  --role "Key Vault Secrets User" \
  --scope "$KV_ID"

# 5. Use a Key Vault reference (versionless = auto-rotates within 24 h)
az webapp config appsettings set -g "$RG" -n "$APP" --settings \
  "DB_PASSWORD=@Microsoft.KeyVault(VaultName=$KV;SecretName=db-password)"

# 6. Staging slot (Standard SKU or higher required)
az webapp deployment slot create -g "$RG" -n "$APP" --slot staging

# 7. Easy Auth v2 with Microsoft Entra
az extension add --name authV2
az webapp auth microsoft update -g "$RG" -n "$APP" \
  --client-id <APP_REG_CLIENT_ID> \
  --client-secret <APP_REG_SECRET> \
  --issuer "https://login.microsoftonline.com/<TENANT_ID>/v2.0" --yes
az webapp auth update -g "$RG" -n "$APP" \
  --enabled true --action LoginWithAzureActiveDirectory
```

## Recipe — Bicep

```bicep
param appName string
param location string = resourceGroup().location
param keyVaultName string

resource plan 'Microsoft.Web/serverfarms@2025-03-01' = {
  name: '${appName}-plan'
  location: location
  kind: 'linux'
  sku: { name: 'P1V3' }
  properties: {
    reserved: true   // REQUIRED for Linux
  }
}

resource webapp 'Microsoft.Web/sites@2025-03-01' = {
  name: appName
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    publicNetworkAccess: 'Disabled'   // pair with a private endpoint
    siteConfig: {
      linuxFxVersion: 'NODE|20-lts'
      minTlsVersion: '1.2'
      ftpsState: 'Disabled'
      alwaysOn: true
      appSettings: [
        {
          name: 'DB_PASSWORD'
          value: '@Microsoft.KeyVault(VaultName=${keyVaultName};SecretName=db-password)'
        }
      ]
    }
  }
}

resource staging 'Microsoft.Web/sites/slots@2025-03-01' = {
  parent: webapp
  name: 'staging'
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      minTlsVersion: '1.2'
      ftpsState: 'Disabled'
      alwaysOn: true
    }
  }
}
```

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| Cold starts after idle | SKU is F1/D1 (no Always On) or `alwaysOn: false` | Upgrade to B1+ and set `alwaysOn: true`. |
| Slot swap leaks staging settings into production | App settings weren't marked slot-sticky | Mark env-specific settings as **slot settings** (`slotSetting: true`). ([Source](https://learn.microsoft.com/azure/app-service/deploy-staging-slots)) |
| Easy Auth 401 loop on `/.auth/login/aad/callback` | Issuer URL is the legacy v1 (`https://sts.windows.net/<tid>`) | Use v2: `https://login.microsoftonline.com/<TID>/v2.0`. ([Source](https://learn.microsoft.com/azure/app-service/configure-authentication-provider-aad)) |
| App sees the literal `@Microsoft.KeyVault(...)` string | MI lacks `Key Vault Secrets User`, or the vault is private and the app has no VNet path | Grant the role; for private vault add VNet integration and `vnetRouteAllEnabled: true`. ([Source](https://learn.microsoft.com/azure/app-service/app-service-key-vault-references)) |
| KV reference shows stale value after secret rotation | App Service caches references for 24 h | Versionless URI auto-rotates within 24 h, or POST `/config/configreferences/appsettings/refresh?api-version=2022-03-01` to force. |
| FTP / Kudu auth fails on a brand-new app | Basic publishing credentials disabled by default since API `2024-11-01` | Re-enable explicitly only if you must (`scmBasicAuthEnabled` / `ftpBasicAuthEnabled`); prefer SCM with Entra ID. |

## References

- [Quickstart: ARM template](https://learn.microsoft.com/azure/app-service/quickstart-arm-template)
- [Managed identity for App Service](https://learn.microsoft.com/azure/app-service/overview-managed-identity)
- [Microsoft Entra authentication (Easy Auth v2)](https://learn.microsoft.com/azure/app-service/configure-authentication-provider-aad)
- [Key Vault references](https://learn.microsoft.com/azure/app-service/app-service-key-vault-references)
- [Configure SSL/TLS settings](https://learn.microsoft.com/azure/app-service/configure-ssl-bindings)
- [Set up staging environments](https://learn.microsoft.com/azure/app-service/deploy-staging-slots)
- [Enable VNet integration](https://learn.microsoft.com/azure/app-service/configure-vnet-integration-enable)
- [Microsoft.Web/sites template reference](https://learn.microsoft.com/azure/templates/microsoft.web/sites)
