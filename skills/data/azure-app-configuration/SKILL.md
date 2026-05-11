---
name: azure-app-configuration
description: >
  Provision an Azure App Configuration store with secure defaults:
  Standard tier, `disableLocalAuth: true` (real property here, unlike
  ACR), `enablePurgeProtection: true`, public network access disabled
  with private endpoint to `privatelink.azconfig.io`. Use Key Vault
  references for secret values and feature flags for runtime toggles.
version: 0.1.0
azure_services:
  - Microsoft.AppConfiguration/configurationStores
  - Microsoft.AppConfiguration/configurationStores/keyValues
  - Microsoft.AppConfiguration/configurationStores/replicas
tags:
  - data
  - configuration
  - feature-flags
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/azure-app-configuration/overview
  - https://learn.microsoft.com/azure/azure-app-configuration/howto-disable-access-key-authentication
  - https://learn.microsoft.com/azure/azure-app-configuration/concept-private-endpoint
  - https://learn.microsoft.com/azure/azure-app-configuration/use-key-vault-references-dotnet-core
  - https://learn.microsoft.com/azure/azure-app-configuration/concept-soft-delete
  - https://learn.microsoft.com/azure/azure-app-configuration/howto-geo-replication
  - https://learn.microsoft.com/azure/azure-app-configuration/howto-best-practices
  - https://learn.microsoft.com/azure/azure-app-configuration/concept-enable-rbac
  - https://learn.microsoft.com/azure/templates/microsoft.appconfiguration/configurationstores
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2024-06-01"
last_reviewed: 2026-05-11
---

# Azure App Configuration (secure baseline)

## When to use this skill

- Centralizing application configuration (non-secrets) across services.
- Adding feature flags / variant feature flags without a code deploy.
- Pulling secrets from Key Vault by reference, but keeping the rest of
  the config in a single source of truth.

## When NOT to use this skill

- Storing actual secrets — those go in Key Vault. App Configuration
  *references* Key Vault secrets but doesn't store them.
- Per-user / per-tenant runtime configuration that changes thousands of
  times per minute — use a database.

## Tier picker

| Need | Tier |
| --- | --- |
| Hello world / prototype | Free (1k requests/day, 10 MB, no SLA, no PE, no soft delete) |
| Non-prod with private endpoint, lower cost | Developer |
| **Production** | **Standard** (private endpoints, soft delete, replicas, SLA) |
| 99.99% SLA, very high request volume | Premium |

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| `sku.name` | `'Standard'` minimum for prod | Free / Developer have feature gaps. |
| `disableLocalAuth` (Bicep) / `--disable-local-auth true` (CLI) | `true` | **This is a valid property here** (unlike ACR). Disables all access keys; forces Entra ID. |
| `publicNetworkAccess` | `'Disabled'` | Pair with PE to `privatelink.azconfig.io`. |
| `enablePurgeProtection` | `true` | Cannot be disabled once set. Standard / Premium only. |
| `softDeleteRetentionInDays` | `7` | Standard / Premium only; auto-enabled. |
| `identity.type` | `'SystemAssigned'` | For CMK encryption + outbound to Key Vault. |
| Replicas | one extra in a paired region for prod | Standard / Premium feature. **Cannot add replicas after a static-IP private endpoint is attached** — provision replicas **first**. |
| Sentinel-key + cache refresh | configure in the SDK | App Config doesn't push changes; the SDK polls. Use a sentinel key updated last to trigger a single refresh after a coordinated change. |

## RBAC roles

- `App Configuration Data Reader` — apps that read configuration.
- `App Configuration Data Owner` — CI / admin tools that write.
- `App Configuration Reader` (control-plane) — view the resource itself.
- `App Configuration Contributor` (control-plane) — manage the resource.

## Recipe — Azure CLI

```bash
RG=rg-appconfig-prod
LOC=eastus
STORE=appcs-app-prod-$RANDOM

# 1. Standard store, Entra-only, no public access
az appconfig create -g "$RG" -n "$STORE" -l "$LOC" \
  --sku Standard \
  --disable-local-auth true \
  --enable-public-network false

# 2. Purge protection (irreversible — set deliberately)
az appconfig update -g "$RG" -n "$STORE" --enable-purge-protection true

# 3. Enable system MI (for outbound to KV / CMK)
az appconfig update -g "$RG" -n "$STORE" --identity-type SystemAssigned

# 4. Grant the consuming app's MI Data Reader on the store
STORE_ID=$(az appconfig show -g "$RG" -n "$STORE" --query id -o tsv)
az role assignment create \
  --assignee-object-id <app-mi-objectid> \
  --assignee-principal-type ServicePrincipal \
  --role "App Configuration Data Reader" --scope "$STORE_ID"

# 5. Add a Key Vault reference (versionless — refresh policy controlled by the client SDK)
az appconfig kv set-keyvault -n "$STORE" \
  --key "App:Settings:DbPassword" \
  --secret-identifier "https://kv-app-prod.vault.azure.net/secrets/db-password" \
  --yes
# Grant the App Config store's MI 'Key Vault Secrets User' on the vault — it does the fetch
KV_ID=$(az keyvault show -g "$RG" -n kv-app-prod --query id -o tsv)
STORE_PRINCIPAL=$(az appconfig show -g "$RG" -n "$STORE" --query identity.principalId -o tsv)
az role assignment create \
  --assignee-object-id "$STORE_PRINCIPAL" --assignee-principal-type ServicePrincipal \
  --role "Key Vault Secrets User" --scope "$KV_ID"

# 6. Feature flag
az appconfig feature set -n "$STORE" --feature Beta --yes

# 7. Geo-replica (BEFORE attaching any static-IP private endpoint)
az appconfig replica create -g "$RG" --store-name "$STORE" \
  --name "${STORE}-westus3" --location westus3

# 8. Private endpoint (groupId = configurationStores)
az network private-endpoint create -g "$RG" -n "pe-$STORE" \
  --vnet-name vnet-app --subnet snet-pe \
  --private-connection-resource-id "$STORE_ID" \
  --connection-name "pec-$STORE" --group-id configurationStores
az network private-dns zone create -g "$RG" -n privatelink.azconfig.io
az network private-dns link vnet create -g "$RG" -n vnet-app-link \
  -z privatelink.azconfig.io --virtual-network vnet-app --registration-enabled false
az network private-endpoint dns-zone-group create -g "$RG" --endpoint-name "pe-$STORE" \
  -n zg-appcs --private-dns-zone privatelink.azconfig.io --zone-name configurationStores
```

## Recipe — Bicep

```bicep
param storeName string
param location string = resourceGroup().location

resource appcs 'Microsoft.AppConfiguration/configurationStores@2024-06-01' = {
  name: storeName
  location: location
  sku: { name: 'Standard' }
  identity: { type: 'SystemAssigned' }
  properties: {
    disableLocalAuth: true              // valid property; disables all access keys
    publicNetworkAccess: 'Disabled'
    enablePurgeProtection: true         // irreversible
    softDeleteRetentionInDays: 7
  }
}

output endpoint string = appcs.properties.endpoint
```

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| App fails 401 / connection refused after `disableLocalAuth: true` | App still uses a connection string (= access key) | Switch to `DefaultAzureCredential` + the store endpoint URL; grant `App Configuration Data Reader` to the MI. |
| Key Vault reference returns null | The **store's** MI lacks `Key Vault Secrets User` on the KV | Grant the role to the App Config store's MI (not the consuming app's MI). |
| Feature flag still serves stale value | SDK cache hasn't expired; sentinel key not updated | Use the sentinel-key pattern: write changes, then bump the sentinel; SDK reloads everything when the sentinel changes. ([Source](https://learn.microsoft.com/azure/azure-app-configuration/howto-best-practices)) |
| ARM deployment can't read App Config values after `disableLocalAuth: true` | ARM `dataPlaneProxy.authenticationMode` defaults to `Local` (key-based) | Switch to `dataPlaneProxy.authenticationMode: 'Pass-through'`. |
| Cannot add a replica | A static-IP private endpoint already exists on the store | Add replicas **before** attaching a static-IP PE. |
| `name conflict` after deletion | The store is in soft-deleted state and the name is reserved | Either purge: `az appconfig purge -n <name> -l <loc>`, or wait out the retention. |

## References

- [App Configuration overview](https://learn.microsoft.com/azure/azure-app-configuration/overview)
- [Disable access key authentication](https://learn.microsoft.com/azure/azure-app-configuration/howto-disable-access-key-authentication)
- [Private endpoints](https://learn.microsoft.com/azure/azure-app-configuration/concept-private-endpoint)
- [Key Vault references](https://learn.microsoft.com/azure/azure-app-configuration/use-key-vault-references-dotnet-core)
- [Soft delete](https://learn.microsoft.com/azure/azure-app-configuration/concept-soft-delete)
- [Geo-replication](https://learn.microsoft.com/azure/azure-app-configuration/howto-geo-replication)
- [Best practices (sentinel-key pattern)](https://learn.microsoft.com/azure/azure-app-configuration/howto-best-practices)
- [RBAC](https://learn.microsoft.com/azure/azure-app-configuration/concept-enable-rbac)
- [`Microsoft.AppConfiguration/configurationStores` template](https://learn.microsoft.com/azure/templates/microsoft.appconfiguration/configurationstores)
