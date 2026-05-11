---
name: azure-storage-account
description: >
  Provision Azure Storage accounts with secure defaults — TLS 1.2+, public
  network access disabled, shared-key access disabled in favor of Entra ID
  (managed identity), infrastructure encryption, and soft delete enabled.
version: 0.1.0
azure_services:
  - Microsoft.Storage/storageAccounts
tags:
  - storage
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/storage/common/storage-account-overview
  - https://learn.microsoft.com/azure/storage/common/storage-account-create
  - https://learn.microsoft.com/azure/storage/common/storage-account-keys-manage
  - https://learn.microsoft.com/azure/storage/common/shared-key-authorization-prevent
  - https://learn.microsoft.com/azure/storage/common/transport-layer-security-configure-minimum-version
  - https://learn.microsoft.com/azure/storage/blobs/soft-delete-blob-overview
  - https://learn.microsoft.com/azure/storage/common/infrastructure-encryption-enable
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2023-05-01"
last_reviewed: 2026-05-11
---

# Azure Storage Account (secure baseline)

## When to use this skill

- The user asks to create, provision, or "spin up" an Azure Storage account.
- The user is wiring up blob/file/queue/table storage for an app and hasn't
  yet picked a security posture.
- The user needs to migrate from access-key auth to Entra ID auth.

## When NOT to use this skill

- The user is configuring an *existing* storage account's networking only —
  use `azure-storage-private-endpoint` instead (planned).
- The workload requires Azure Data Lake Storage Gen2 hierarchical namespace —
  most defaults below still apply but enable `--hns true` and consult
  `azure-adls-gen2` (planned).

## Prerequisites

- Azure CLI `>= 2.60.0` (`az --version`).
- Logged in: `az login` (or workload identity in CI).
- Subscription selected: `az account set --subscription <id>`.
- Resource group exists or will be created.
- Caller has `Contributor` (or finer) on the target RG.

## Secure defaults

The agent MUST apply *all* of these on creation. None of them require a
premium SKU.

| Setting | Value | Why |
| --- | --- | --- |
| `--min-tls-version` | `TLS1_2` | TLS 1.0/1.1 are deprecated; 1.2 is the minimum supported by Microsoft. |
| `--allow-blob-public-access` | `false` | Prevents accidental anonymous container/blob exposure. |
| `--allow-shared-key-access` | `false` | Forces Entra ID (RBAC / managed identity). Storage account keys can still be rotated for break-glass. |
| `--public-network-access` | `Disabled` | Combine with a private endpoint, or set `Enabled` *only* if you also pass `--default-action Deny` and an explicit IP/VNet allow-list. |
| `--default-action` (network rules) | `Deny` | Default deny; allow-list explicitly. |
| `--require-infrastructure-encryption` | `true` | Adds a second encryption layer at the infrastructure level. Must be set at creation; cannot be enabled later. |
| `--enable-hierarchical-namespace` | `false` (unless ADLS Gen2 needed) | Avoids accidental ADLS semantics. |
| Blob soft delete | Enabled, retention >= 7 days | Recovers from accidental deletes. |
| Container soft delete | Enabled, retention >= 7 days | Recovers from accidental deletes. |
| Versioning | Enabled (recommended) | Required for change feed / point-in-time restore. |

## Recipe — Azure CLI

```bash
# Variables
RG=rg-app-prod
LOC=westus3
SA=stappprod$RANDOM           # must be 3–24 chars, lowercase + digits, globally unique
SKU=Standard_RAGZRS           # zone-redundant + read-access geo-redundant; pick per RTO/RPO

# 1. Resource group (idempotent)
az group create --name "$RG" --location "$LOC"

# 2. Create storage account with secure defaults
az storage account create \
  --name "$SA" \
  --resource-group "$RG" \
  --location "$LOC" \
  --sku "$SKU" \
  --kind StorageV2 \
  --min-tls-version TLS1_2 \
  --allow-blob-public-access false \
  --allow-shared-key-access false \
  --public-network-access Disabled \
  --default-action Deny \
  --bypass AzureServices \
  --require-infrastructure-encryption true \
  --enable-hierarchical-namespace false

# 3. Enable blob + container soft delete and versioning
az storage account blob-service-properties update \
  --account-name "$SA" \
  --resource-group "$RG" \
  --enable-delete-retention true --delete-retention-days 14 \
  --enable-container-delete-retention true --container-delete-retention-days 14 \
  --enable-versioning true \
  --enable-change-feed true

# 4. Grant the calling principal data-plane RBAC (Entra ID auth, not keys)
PRINCIPAL_ID=$(az ad signed-in-user show --query id -o tsv)
SCOPE=$(az storage account show -n "$SA" -g "$RG" --query id -o tsv)
az role assignment create \
  --assignee "$PRINCIPAL_ID" \
  --role "Storage Blob Data Contributor" \
  --scope "$SCOPE"
```

> Because `--public-network-access Disabled` blocks data-plane traffic from
> the public internet, a follow-up step (private endpoint, or explicit
> network rule for an allowed VNet/IP) is required before the account is
> usable. Use the `azure-storage-private-endpoint` skill (planned) to wire
> that up.

## Recipe — Bicep

```bicep
@minLength(3) @maxLength(24)
param storageAccountName string

@allowed([ 'Standard_LRS','Standard_ZRS','Standard_GRS','Standard_RAGRS','Standard_GZRS','Standard_RAGZRS' ])
param sku string = 'Standard_RAGZRS'

param location string = resourceGroup().location

resource sa 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  sku: { name: sku }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    publicNetworkAccess: 'Disabled'
    networkAcls: {
      defaultAction: 'Deny'
      bypass: 'AzureServices'
    }
    encryption: {
      requireInfrastructureEncryption: true
      services: {
        blob: { enabled: true, keyType: 'Account' }
        file: { enabled: true, keyType: 'Account' }
      }
      keySource: 'Microsoft.Storage'
    }
    supportsHttpsTrafficOnly: true
  }
}

resource blobSvc 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: sa
  name: 'default'
  properties: {
    deleteRetentionPolicy: { enabled: true, days: 14 }
    containerDeleteRetentionPolicy: { enabled: true, days: 14 }
    isVersioningEnabled: true
    changeFeed: { enabled: true }
  }
}
```

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| `StorageAccountAlreadyTaken` | Names are global; another tenant has it. | Append more entropy or use a deterministic naming convention with subscription ID hash. |
| `RequestDisallowedByPolicy` | Azure Policy blocks the chosen SKU/region. | Check `az policy state list --resource <id>`; pick a compliant SKU/region. |
| Client gets `AuthorizationFailure` after create | `--allow-shared-key-access false` and the client is using a connection string with a key. | Switch the client to `DefaultAzureCredential` / managed identity. Don't re-enable shared key. |
| `PublicAccessNotPermitted` on data-plane calls | `--public-network-access Disabled`. | Add a private endpoint or a scoped network rule; do not flip the account to `Enabled` blindly. |
| `requireInfrastructureEncryption` not settable on existing account | It can only be enabled at creation. | Recreate the account; migrate data with `az storage copy` or AzCopy. |

## References

- [Storage account overview](https://learn.microsoft.com/azure/storage/common/storage-account-overview)
- [Create a storage account](https://learn.microsoft.com/azure/storage/common/storage-account-create)
- [Manage storage account access keys](https://learn.microsoft.com/azure/storage/common/storage-account-keys-manage)
- [Prevent shared key authorization](https://learn.microsoft.com/azure/storage/common/shared-key-authorization-prevent)
- [Configure minimum TLS version](https://learn.microsoft.com/azure/storage/common/transport-layer-security-configure-minimum-version)
- [Blob soft delete](https://learn.microsoft.com/azure/storage/blobs/soft-delete-blob-overview)
- [Enable infrastructure encryption](https://learn.microsoft.com/azure/storage/common/infrastructure-encryption-enable)
