---
name: azure-data-lake-storage-gen2
description: >
  Provision a Storage account with **`isHnsEnabled: true`** to make it
  an ADLS Gen2 data lake — hierarchical namespace + ABFS endpoints +
  POSIX ACLs alongside Azure RBAC. **HNS is creation-time only and
  effectively immutable.** Use the `dfs` endpoint (not `blob`) from
  Spark / Databricks / Synapse for ACL-aware semantics.
version: 0.1.0
azure_services:
  - Microsoft.Storage/storageAccounts
tags:
  - data
  - data-lake
  - adls
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/storage/blobs/data-lake-storage-introduction
  - https://learn.microsoft.com/azure/storage/blobs/create-data-lake-storage-account
  - https://learn.microsoft.com/azure/storage/blobs/data-lake-storage-namespace
  - https://learn.microsoft.com/azure/storage/blobs/data-lake-storage-access-control
  - https://learn.microsoft.com/azure/storage/blobs/data-lake-storage-access-control-model
  - https://learn.microsoft.com/azure/storage/blobs/lifecycle-management-overview
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2023-05-01"
last_reviewed: 2026-05-12
---

# Azure Data Lake Storage Gen2

## When to use this skill

- The user wants a data lake for analytics — Spark, Databricks, Synapse,
  Fabric, ADF.
- The user needs POSIX-style ACLs on top of (or instead of) Azure RBAC.
- The user wants directory-level operations that scale (rename, delete
  whole subtree atomically).

## When NOT to use this skill

- Plain blob storage for app uploads / downloads — see
  [`azure-storage-account`](../azure-storage-account/SKILL.md) (no HNS).
- Hot transactional store — use Cosmos DB / Azure SQL.

## The single most important rule

> **`isHnsEnabled: true` is set at storage-account creation time and is
> effectively immutable.** A migration path (`az storage account hns-migration`)
> exists but is a complex one-way validation/migration operation, not a
> simple toggle. If you might *ever* want ACL semantics, set HNS at
> creation. ([Source](https://learn.microsoft.com/azure/storage/blobs/data-lake-storage-introduction))

## ABFS endpoints

ADLS Gen2 exposes two endpoint URLs per account:

- **Blob endpoint** (`https://<acct>.blob.core.windows.net`) — works
  with HNS too, but requests via this URL **do not honor ACLs** — only
  RBAC.
- **DFS endpoint** (`abfss://<container>@<acct>.dfs.core.windows.net/<path>`) —
  the ABFS Hadoop-compatible URL. Required for Spark / Databricks /
  Synapse to get ACL-aware reads + writes.

Always use `abfss://` from analytics engines.

## RBAC vs ACLs

| Layer | Granularity | Recommended for |
| --- | --- | --- |
| Azure RBAC | container / account | Default. `Storage Blob Data Owner / Contributor / Reader` are typical. |
| **POSIX ACLs** | file / folder (read / write / execute, owning user / owning group / other / named users / named groups) | Fine-grained access where RBAC isn't expressive enough (multi-tenant lake, per-team subfolders). |
| Combined | both apply; access requires permission via **either** RBAC **or** ACLs | RBAC denials and ACL denials don't compound — either grants. |

> **`Storage Blob Data Owner` carries ACL admin** (the equivalent of
> super-user). Grant it carefully. ([Source](https://learn.microsoft.com/azure/storage/blobs/data-lake-storage-access-control-model))

## Secure defaults

Re-uses every secure-default from [`azure-storage-account`](../azure-storage-account/SKILL.md)
(TLS 1.2+, public access disabled, infra encryption, etc.) plus:

| Setting | Value | Why |
| --- | --- | --- |
| `properties.isHnsEnabled` | **`true`** | Makes it ADLS Gen2. **Set at creation.** |
| `properties.allowBlobPublicAccess` | `false` | Standard storage hygiene. |
| `properties.minimumTlsVersion` | `'TLS1_2'` | Standard. |
| `properties.networkAcls.defaultAction` | `'Deny'` | Default-deny network ACL. |
| `properties.publicNetworkAccess` | `'Disabled'` | Pair with PE to **all required sub-resource zones** (`blob` + `dfs` at minimum). |
| Lifecycle management | move cold data to Cool / Cold / Archive tier | Massive cost saver on warehouses. |
| Default ACL on parent folders | set so new children inherit | ACL changes don't propagate to existing children — use `azcopy set-properties` or recursive PowerShell to backfill. |
| Tools accessing data | use the **DFS** endpoint (`abfss://`), never `blob` | Otherwise ACLs are silently ignored. |

## Recipe — Azure CLI

```bash
RG=rg-lake-prod
LOC=eastus
SA=stlakeprod$RANDOM       # 3–24 chars, lowercase + digits, NO hyphens

# 1. Storage account with HNS = ADLS Gen2
az storage account create -g "$RG" -n "$SA" -l "$LOC" \
  --sku Standard_RAGZRS --kind StorageV2 \
  --hierarchical-namespace true \
  --min-tls-version TLS1_2 \
  --allow-blob-public-access false \
  --allow-shared-key-access false \
  --public-network-access Disabled \
  --default-action Deny --bypass AzureServices

# 2. Create a filesystem (= top-level container)
az storage fs create -n raw \
  --account-name "$SA" --auth-mode login

# 3. Grant the calling user/MI Storage Blob Data Contributor on the SA
SA_ID=$(az storage account show -n "$SA" -g "$RG" --query id -o tsv)
az role assignment create \
  --assignee-object-id <user-or-mi-objectid> --assignee-principal-type ServicePrincipal \
  --role "Storage Blob Data Contributor" --scope "$SA_ID"

# 4. Set POSIX ACL on a folder (read+write+execute for an Entra group)
az storage fs access set --acl \
  "user::rwx,group::r-x,other::---,group:<entra-group-objectid>:rwx,default:group:<entra-group-objectid>:rwx" \
  -p "subdir/" -f raw --account-name "$SA" --auth-mode login

# 5. PEs — one per sub-resource you'll use (at minimum blob + dfs)
for SUB in blob dfs; do
  az network private-endpoint create -g "$RG" -n "pe-$SA-$SUB" \
    --vnet-name vnet-app --subnet snet-pe \
    --private-connection-resource-id "$SA_ID" \
    --connection-name "pec-$SA-$SUB" --group-id "$SUB"
done
# (link privatelink.blob.core.windows.net + privatelink.dfs.core.windows.net to the consumer VNet)
```

## Recipe — Bicep

```bicep
param storageAccountName string
param location string = resourceGroup().location

resource sa 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  sku: { name: 'Standard_RAGZRS' }
  kind: 'StorageV2'
  properties: {
    isHnsEnabled: true                     // ADLS Gen2
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    supportsHttpsTrafficOnly: true
    publicNetworkAccess: 'Disabled'
    networkAcls: { defaultAction: 'Deny', bypass: 'AzureServices' }
    encryption: {
      requireInfrastructureEncryption: true
      services: {
        blob: { enabled: true, keyType: 'Account' }
        file: { enabled: true, keyType: 'Account' }
      }
      keySource: 'Microsoft.Storage'
    }
  }
}

// Lifecycle policy: move untouched data to Cool/Archive
resource lifecycle 'Microsoft.Storage/storageAccounts/managementPolicies@2023-05-01' = {
  parent: sa
  name: 'default'
  properties: {
    policy: {
      rules: [
        {
          name: 'cool-after-30d-archive-after-180d'
          enabled: true
          type: 'Lifecycle'
          definition: {
            filters: { blobTypes: [ 'blockBlob' ] }
            actions: {
              baseBlob: {
                tierToCool:    { daysAfterModificationGreaterThan: 30  }
                tierToArchive: { daysAfterModificationGreaterThan: 180 }
              }
            }
          }
        }
      ]
    }
  }
}
```

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| Tried to enable HNS on an existing account | `isHnsEnabled` is set at creation; the migration tool exists but is a one-way operation with limitations | Recreate the account; copy data with AzCopy or `az storage copy`. |
| Spark/Databricks read against `https://<acct>.blob.core.windows.net/...` shows files but ACLs are ignored | Wrong endpoint — `blob` endpoint doesn't honor ACLs | Switch to `abfss://<container>@<acct>.dfs.core.windows.net/<path>`. |
| ACL change "didn't propagate" | ACLs only apply to the file/folder they're set on | Set the **default ACL** on the parent for new children; backfill existing with `azcopy set-properties` or a recursive helper. |
| Caller has `Contributor` on the SA but can't read data | Control-plane Contributor doesn't grant data-plane | Add `Storage Blob Data Reader` (or higher). Same trap as plain Storage. |
| Lifecycle policy isn't moving data | Wrong filter (e.g., trying to age `appendBlob` with a `blockBlob` filter) | Inspect the policy; use `daysAfterCreationGreaterThan` if file mtime is unstable. |
| App packages on Azure Batch fail when auto-storage is HNS | **Batch application packages are incompatible with HNS-enabled storage accounts** | Use a separate non-HNS storage account for Batch auto-storage. |

## References

- [ADLS Gen2 introduction](https://learn.microsoft.com/azure/storage/blobs/data-lake-storage-introduction)
- [Create an ADLS Gen2 storage account](https://learn.microsoft.com/azure/storage/blobs/create-data-lake-storage-account)
- [Hierarchical namespace](https://learn.microsoft.com/azure/storage/blobs/data-lake-storage-namespace)
- [ACL overview](https://learn.microsoft.com/azure/storage/blobs/data-lake-storage-access-control)
- [Access control model (RBAC vs ACL)](https://learn.microsoft.com/azure/storage/blobs/data-lake-storage-access-control-model)
- [Lifecycle management](https://learn.microsoft.com/azure/storage/blobs/lifecycle-management-overview)
