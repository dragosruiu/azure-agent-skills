---
name: azure-key-vault
description: >
  Provision Azure Key Vault with secure defaults: RBAC authorization (not
  legacy access policies), purge protection, soft-delete max retention,
  public network access disabled, default-deny network ACLs. Use Key Vault
  Secrets User for app reads and Secrets Officer for rotation pipelines.
version: 0.1.0
azure_services:
  - Microsoft.KeyVault/vaults
tags:
  - identity
  - secrets
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/key-vault/general/rbac-guide
  - https://learn.microsoft.com/azure/key-vault/general/security-features
  - https://learn.microsoft.com/azure/key-vault/general/secure-key-vault
  - https://learn.microsoft.com/azure/key-vault/general/network-security
  - https://learn.microsoft.com/azure/key-vault/general/soft-delete-overview
  - https://learn.microsoft.com/azure/key-vault/general/quick-create-cli
  - https://learn.microsoft.com/azure/key-vault/general/rbac-access-policy
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2023-07-01"
last_reviewed: 2026-05-11
---

# Azure Key Vault (secure baseline)

## When to use this skill

- The user is creating a Key Vault to hold secrets (DB connection strings,
  API keys, certificates) for an application.
- The user is migrating off the legacy access-policy model to RBAC.
- The user accidentally deleted a vault and needs to recover it.

## When NOT to use this skill

- Storing application configuration that isn't sensitive — use App
  Configuration instead.
- Storing TLS certificates that the platform manages for you (App Service
  managed certificate, Front Door managed cert) — let the platform do it.
- Storing Cosmos DB / Storage account keys — disable shared-key auth on
  those services and use managed identity instead. Don't rotate
  yesterday's bad practice into Key Vault.

## Prerequisites

- Azure CLI `>= 2.60.0` (`az --version`).
- The deployment principal needs `Microsoft.KeyVault/vaults/write` plus
  `Microsoft.Authorization/roleAssignments/write` (i.e. `Owner` or `User
  Access Administrator`) at the vault scope to grant data-plane RBAC.

## Secure defaults

The agent MUST apply *all* of these on creation. Several cannot be
changed later (purge protection, soft-delete retention).

| Setting | Value | Why |
| --- | --- | --- |
| `--enable-rbac-authorization` | `true` | RBAC model is recommended over legacy access policies. The access-policy model has a known privilege-escalation issue: a `Contributor` on the vault can grant themselves data-plane access via `Microsoft.KeyVault/vaults/write`. Source: [rbac-access-policy](https://learn.microsoft.com/azure/key-vault/general/rbac-access-policy). |
| `--enable-purge-protection` | `true` | Prevents anyone (including subscription owners) from hard-deleting the vault during the soft-delete window. **Irreversible once enabled.** Source: [soft-delete-overview](https://learn.microsoft.com/azure/key-vault/general/soft-delete-overview). |
| `--retention-days` | `90` (max) | Soft-delete window. **Cannot be changed after creation.** Range 7–90. |
| `--public-network-access` | `Disabled` | Blocks all public data-plane connections. The vault FQDN is still publicly resolvable by design (DNS overlay) — that's fine. Source: [network-security](https://learn.microsoft.com/azure/key-vault/general/network-security). |
| `--default-action` (network ACLs) | `Deny` | Default-deny on the firewall. Add explicit rules for what's allowed. |
| `--bypass` | `AzureServices` | Allows trusted Microsoft services (ARM template deployments, Backup, etc.) through the firewall. |
| `--sku` | `standard` (default) — pick `premium` only if you need HSM-backed keys (FIPS 140-3 Level 3) | Premium is more expensive and not needed for ordinary secrets. |

> **Soft delete is on by default and cannot be disabled.** No flag needed.

## RBAC role picker

Verified from the [Key Vault RBAC guide](https://learn.microsoft.com/azure/key-vault/general/rbac-guide):

| Role | Role ID | Use when |
| --- | --- | --- |
| `Key Vault Administrator` | `00482a5a-887f-4fb3-b363-3b7fe8e74483` | Break-glass / vault owners. All data-plane ops on keys, secrets, certs. **Not** control-plane management. |
| `Key Vault Secrets Officer` | `b86a8fe4-44ce-4948-aee5-eccb2c155cd7` | Secret rotation pipelines. Full CRUD on secrets; cannot manage RBAC. |
| `Key Vault Secrets User` | `4633458b-17de-408a-b874-0445c86b69e6` | **Apps that read secrets.** Read-only — `secrets/getSecret/action`. |
| `Key Vault Crypto Officer` | `14b46e9e-c2b7-41b4-b07b-48a6ebf60603` | Key lifecycle (create / rotate / delete keys). |
| `Key Vault Crypto User` | `12338af0-0e69-4776-bea7-57ae8d297424` | Apps performing encrypt / decrypt / sign / verify. |
| `Key Vault Certificates Officer` | `a4417e6f-fecd-4de8-b567-7b0420556985` | Cert lifecycle. |
| `Key Vault Reader` | `21090545-7ca7-4776-b22c-e363652d74d2` | Metadata only. **Cannot** read secret values — common 403 trap. |
| `Key Vault Purge Operator` | `a68e7c17-0ab2-4c09-9a58-125dae29748c` | Permanently delete soft-deleted vaults. |

## Recipe — Azure CLI

```bash
RG=rg-app-prod
LOC=eastus
KV=kv-app-prod-$RANDOM       # 3–24 chars, alphanumeric + hyphens, globally unique

az keyvault create \
  --name "$KV" \
  --resource-group "$RG" \
  --location "$LOC" \
  --sku standard \
  --enable-rbac-authorization true \
  --enable-purge-protection true \
  --retention-days 90 \
  --public-network-access Disabled \
  --default-action Deny \
  --bypass AzureServices

# Grant Key Vault Secrets User to a managed identity
KV_ID=$(az keyvault show -n "$KV" -g "$RG" --query id -o tsv)
PRINCIPAL_ID=<objectId-of-app-managed-identity>
az role assignment create \
  --assignee-object-id "$PRINCIPAL_ID" \
  --assignee-principal-type ServicePrincipal \
  --role "Key Vault Secrets User" \
  --scope "$KV_ID"

# Recover a soft-deleted vault (within retention window)
az keyvault recover --name "$KV" --resource-group "$RG" --location "$LOC"
```

## Recipe — Bicep

```bicep
param vaultName string
param location string = resourceGroup().location
param principalId string  // object ID of the consuming managed identity

var keyVaultSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: vaultName
  location: location
  properties: {
    sku: { family: 'A', name: 'standard' }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 90
    enablePurgeProtection: true
    publicNetworkAccess: 'Disabled'
    networkAcls: {
      defaultAction: 'Deny'
      bypass: 'AzureServices'
      ipRules: []
      virtualNetworkRules: []
    }
  }
}

resource secretsUserAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, principalId, keyVaultSecretsUserRoleId)
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

output vaultUri string = keyVault.properties.vaultUri
output vaultId string = keyVault.id
```

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| App gets 403 immediately after creation + role grant | RBAC propagation delay (up to 5–10 min, occasionally 30) | Retry with exponential backoff. ([Source](https://learn.microsoft.com/azure/key-vault/general/rbac-guide)) |
| Need to recreate a vault under the same name and get `VaultAlreadyExists` | Vault name is globally reserved during the soft-delete retention period | `az keyvault recover` if you want it back, or wait out the retention period. **Recovered vaults do NOT restore RBAC assignments or Event Grid subscriptions** — re-create those. ([Source](https://learn.microsoft.com/azure/key-vault/general/soft-delete-overview)) |
| Cannot hard-delete a vault even as Owner | Purge protection is enabled — by design no override exists | Wait for the retention period to elapse; the vault auto-purges. ([Source](https://learn.microsoft.com/azure/key-vault/general/key-vault-recovery)) |
| App with `Key Vault Reader` role gets 403 reading secret value | `Key Vault Reader` is metadata-only | Use `Key Vault Secrets User` for apps that actually read secret values. |
| Connection works from local laptop but fails from Function App | `publicNetworkAccess: Disabled` and the Function App doesn't have a private endpoint or VNet integration to reach the vault | Add a private endpoint for the vault and integrate the Function App with the VNet, or temporarily allow the Function App's outbound IP via `--ip-address` — see `azure-private-endpoint`. |

## References

- [Use Azure RBAC to manage Key Vault data plane (rbac-guide)](https://learn.microsoft.com/azure/key-vault/general/rbac-guide)
- [Key Vault security features](https://learn.microsoft.com/azure/key-vault/general/security-features)
- [Securing your Key Vault](https://learn.microsoft.com/azure/key-vault/general/secure-key-vault)
- [Network security for Key Vault](https://learn.microsoft.com/azure/key-vault/general/network-security)
- [Soft-delete and purge protection](https://learn.microsoft.com/azure/key-vault/general/soft-delete-overview)
- [Quickstart: Create a Key Vault with the CLI](https://learn.microsoft.com/azure/key-vault/general/quick-create-cli)
- [RBAC vs access policies](https://learn.microsoft.com/azure/key-vault/general/rbac-access-policy)
