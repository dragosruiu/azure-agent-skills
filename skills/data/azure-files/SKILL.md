---
name: azure-files
description: >
  Azure Files SMB / NFS shares. Use a `FileStorage` (Premium) account
  with identity-based auth (Microsoft Entra Kerberos preferred for
  cloud-only / hybrid), `allowSharedKeyAccess: false`, TLS 1.2 minimum,
  soft delete (7 day default), and a private endpoint to the `file`
  sub-resource with a `privatelink.file.core.windows.net` private DNS
  zone. NFS = SSD-only, LRS/ZRS only, no Azure Backup, no identity auth
  (network-level only).
version: 0.1.0
azure_services:
  - Microsoft.Storage/storageAccounts (kind FileStorage)
  - Microsoft.Storage/storageAccounts/fileServices
  - Microsoft.Storage/storageAccounts/fileServices/shares
tags:
  - data
  - files
  - smb
  - nfs
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/storage/files/storage-files-planning
  - https://learn.microsoft.com/azure/storage/files/storage-files-active-directory-overview
  - https://learn.microsoft.com/azure/storage/files/files-nfs-protocol
  - https://learn.microsoft.com/azure/storage/files/storage-files-networking-overview
  - https://learn.microsoft.com/azure/storage/files/storage-files-prevent-file-share-deletion
  - https://learn.microsoft.com/azure/storage/files/storage-files-scale-targets
  - https://learn.microsoft.com/azure/storage/files/storage-how-to-use-files-cli
  - https://learn.microsoft.com/azure/templates/microsoft.storage/storageaccounts/fileservices/shares
validated_with:
  az_cli: ">=2.60.0"
  api_version: "shares 2026-04-01; fileServices/storageAccounts 2024-01-01"
last_reviewed: 2026-05-15
---

# Azure Files (SMB & NFS)

## When to use this skill

- Lift-and-shift workloads that need an SMB share (Windows / Linux).
- HPC / Linux workloads needing POSIX-compatible NFS 4.1.
- Cross-VM shared state (e.g., file uploads behind a load balancer).

## When NOT to use this skill

- Object storage / blob workloads — use
  [`azure-storage-account`](../azure-storage-account/SKILL.md) for blob
  patterns.
- Hierarchical analytics (Spark / Databricks) — use
  [`azure-data-lake-storage-gen2`](../azure-data-lake-storage-gen2/SKILL.md).

## SKU + protocol matrix

| Account kind | SKUs | Media | Protocols |
| --- | --- | --- | --- |
| `FileStorage` | `Premium_LRS`, `Premium_ZRS`, `PremiumV2_LRS`, `PremiumV2_ZRS` | SSD | SMB or NFS |
| `FileStorage` | `StandardV2_LRS / ZRS / GRS / GZRS` | HDD | SMB or NFS |
| `StorageV2` | `Standard_LRS / ZRS / GRS / GZRS` | HDD | SMB only |

> Use `FileStorage` for new deployments. **NFS requires SSD** and only
> supports LRS / ZRS (no GRS / GZRS).

| Feature | SMB | NFS 4.1 |
| --- | --- | --- |
| Identity auth | Kerberos (Entra / AD DS / Entra DS) or storage key | **none** (network-level only) |
| Internet access | yes (with encryption) | **no** — must use PE / VPN / ExpressRoute |
| Azure Backup | ✅ | ❌ |
| Azure File Sync | ✅ | ❌ |
| ACLs | Win32 ACLs | ❌ NFS ACLs not supported |
| Multichannel | ✅ (SSD only) | n/a |

## Identity-based auth (SMB only)

| Method | Identity source | Use case |
| --- | --- | --- |
| **Microsoft Entra Kerberos** | Entra ID | cloud-only or hybrid; Entra-joined / hybrid-joined VMs; no DC required |
| AD DS | Customer-owned on-prem AD | domain-joined clients (synced to Entra via Connect Sync) |
| Microsoft Entra Domain Services | Microsoft-managed AD | cloud VMs joined to Entra DS managed domain |

When using identity-based auth, also set `allowSharedKeyAccess: false`
and grant data-plane RBAC (e.g., `Storage File Data SMB Share
Contributor`) to users / groups.

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| `kind` | `FileStorage` (Premium) | Required for NFS; preferred billing model for SMB. |
| `allowSharedKeyAccess` | `false` | Disable storage-account keys; use identity-based auth + RBAC. |
| `minimumTlsVersion` | `TLS1_2` | Controls FileREST (HTTPS). |
| `supportsHttpsTrafficOnly` | `true` | Secure transfer required. |
| Soft delete | enabled, 7-day retention | Default; 1–365 days configurable. |
| SMB encryption in transit | enabled (`requireEncryption`); CLI/API default is **off** for backward compat — set explicitly | Portal default is on. |
| NFS network access | private endpoint + private DNS, or service endpoint | NFS rejects public access without explicit network restriction. |
| Identity auth (SMB) | **Microsoft Entra Kerberos** for cloud-only / hybrid | No on-prem DC required. |
| Private endpoint sub-resource | `file` | DNS via `privatelink.file.core.windows.net` zone linked to the VNet. |

## Recipe — Azure CLI (Premium SMB share with identity auth + PE)

```bash
RG=files-rg
LOC=eastus
ACCT=stfilesexample001              # 3–24 lowercase alphanum, globally unique
SHARE=appdata
VNET=hub-vnet
SUBNET=privatelink

az group create -n "$RG" -l "$LOC"

az storage account create -g "$RG" -n "$ACCT" -l "$LOC" \
  --kind FileStorage --sku Premium_ZRS \
  --min-tls-version TLS1_2 --https-only true \
  --allow-shared-key-access false

# 100 GiB minimum for Premium
az storage share-rm create -g "$RG" --storage-account "$ACCT" -n "$SHARE" \
  --quota 100 --enabled-protocols SMB --access-tier Premium

# Soft delete (7 d)
az storage account file-service-properties update -g "$RG" --account-name "$ACCT" \
  --enable-delete-retention true --delete-retention-days 7

# Private endpoint to the 'file' sub-resource
ACCT_ID=$(az storage account show -g "$RG" -n "$ACCT" --query id -o tsv)
az network private-endpoint create -g "$RG" -n pe-files \
  --vnet-name "$VNET" --subnet "$SUBNET" \
  --private-connection-resource-id "$ACCT_ID" --group-ids file \
  --connection-name pe-files-conn

# Private DNS zone + VNet link + zone group
az network private-dns zone create -g "$RG" -n privatelink.file.core.windows.net
az network private-dns link vnet create -g "$RG" \
  --zone-name privatelink.file.core.windows.net -n dns-link-files \
  --virtual-network "$VNET" --registration-enabled false
az network private-endpoint dns-zone-group create -g "$RG" \
  --endpoint-name pe-files -n filesZG \
  --private-dns-zone privatelink.file.core.windows.net --zone-name files

# Enable Microsoft Entra Kerberos (additional domain-join steps may be needed)
az storage account update -g "$RG" -n "$ACCT" --enable-files-aadkerberos true
```

> **NFS variant:** `--enabled-protocols NFS`, `--sku Premium_LRS` (or
> ZRS), and skip `--allow-shared-key-access false` — NFS uses
> network-level access only and must sit behind a PE / VPN / ER.

## Recipe — Bicep

```bicep
param storageAccountName string
param location string = resourceGroup().location

resource sa 'Microsoft.Storage/storageAccounts@2024-01-01' = {
  name: storageAccountName
  location: location
  kind: 'FileStorage'                  // dedicated for file shares
  sku: { name: 'Premium_ZRS' }
  properties: {
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowSharedKeyAccess: false        // identity-based auth only
  }
}

resource fileSvc 'Microsoft.Storage/storageAccounts/fileServices@2024-01-01' = {
  parent: sa
  name: 'default'
  properties: {
    shareDeleteRetentionPolicy: { enabled: true, days: 7 }
  }
}

resource smbShare 'Microsoft.Storage/storageAccounts/fileServices/shares@2026-04-01' = {
  parent: fileSvc
  name: 'appdata'
  properties: {
    enabledProtocols: 'SMB'            // 'SMB' or 'NFS' — immutable after create
    shareQuota: 100                    // GiB; min 100 for Premium
    accessTier: 'Premium'
  }
}

// NFS variant:
// resource nfsShare 'Microsoft.Storage/storageAccounts/fileServices/shares@2026-04-01' = {
//   parent: fileSvc
//   name: 'nfsdata'
//   properties: {
//     enabledProtocols: 'NFS'
//     shareQuota: 100
//     accessTier: 'Premium'
//     rootSquash: 'RootSquash'        // 'NoRootSquash' | 'RootSquash' | 'AllSquash'
//   }
// }
```

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| NFS mount: "Permission denied" | NFS is network-auth only; not on the PE / allow-list | Ensure access via private endpoint, service endpoint, or VPN/ExpressRoute |
| Port 445 blocked from on-prem clients | ISP / corporate egress blocks SMB port 445 | VPN / ExpressRoute + PE; or SMB-over-QUIC via Azure File Sync |
| NFS share creation fails on `StorageV2` | NFS needs `FileStorage` (SSD) | Use `kind: 'FileStorage'`, `Premium_LRS / ZRS` |
| SMB encryption in transit defaults OFF via CLI | Portal default = on; CLI/API/PowerShell default = off (backward compat) | Set explicitly: `--https-only true` and per-protocol SMB encryption settings |
| `allowSharedKeyAccess: false` breaks AzCopy / Storage Explorer | Tools use storage keys | Reconfigure tooling for identity-based auth + RBAC before flipping the switch |
| SMB Multichannel unavailable on HDD shares | Multichannel = SSD `FileStorage` only | Use `Premium_LRS / ZRS / PremiumV2_*` |
| NFS Azure Backup unavailable | not supported | Use NFS share snapshots (max 200 / share) |
| NFS GRS / GZRS rejected | NFS = LRS / ZRS only | Use LRS / ZRS or replicate manually |
| Soft-deleted Premium shares still billed | Provisioned billing continues during retention | Keep soft-delete short; to permanently delete, undelete → disable soft delete → delete |
| Hit max 50 shares / Provisioned v2 account | Hard limit on PV2 FileStorage | Distribute across accounts, or use the new `Microsoft.FileShares` RP (preview) |
| Entra Kerberos doesn't issue tickets for hybrid users | Hybrid identity needs Entra Connect Sync (or cloud sync) to Entra ID | Set up sync first |
| DNS resolves to public IP despite PE | `privatelink.file.core.windows.net` zone not linked to the VNet | Create + link the zone, then create the PE's DNS zone group |

## API versions

| Resource | Pinned |
| --- | --- |
| `Microsoft.Storage/storageAccounts/fileServices/shares` | `2026-04-01` (verified latest) |
| `Microsoft.Storage/storageAccounts/fileServices` | `2024-01-01` |
| `Microsoft.Storage/storageAccounts` | `2024-01-01` |

## References

- [Files planning](https://learn.microsoft.com/azure/storage/files/storage-files-planning)
- [Identity-based auth overview](https://learn.microsoft.com/azure/storage/files/storage-files-active-directory-overview)
- [NFS protocol support](https://learn.microsoft.com/azure/storage/files/files-nfs-protocol)
- [Networking overview](https://learn.microsoft.com/azure/storage/files/storage-files-networking-overview)
- [Prevent share deletion (soft delete)](https://learn.microsoft.com/azure/storage/files/storage-files-prevent-file-share-deletion)
- [Scale + IO targets](https://learn.microsoft.com/azure/storage/files/storage-files-scale-targets)
- [Azure CLI quickstart](https://learn.microsoft.com/azure/storage/files/storage-how-to-use-files-cli)
- [`shares` template reference](https://learn.microsoft.com/azure/templates/microsoft.storage/storageaccounts/fileservices/shares)
