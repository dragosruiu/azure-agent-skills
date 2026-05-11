---
name: azure-postgresql-flexible
description: >
  Provision Azure Database for PostgreSQL Flexible Server with secure
  defaults: VNet-injected (no public access), Entra ID auth enabled and
  password auth disabled, zone-redundant HA on General Purpose tier,
  geo-redundant backup with 14-day retention.
version: 0.1.0
azure_services:
  - Microsoft.DBforPostgreSQL/flexibleServers
tags:
  - data
  - relational
  - postgresql
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/postgresql/flexible-server/quickstart-create-server-cli
  - https://learn.microsoft.com/azure/postgresql/flexible-server/quickstart-create-server-bicep
  - https://learn.microsoft.com/azure/postgresql/flexible-server/how-to-configure-sign-in-azure-ad-authentication
  - https://learn.microsoft.com/azure/postgresql/flexible-server/concepts-azure-ad-authentication
  - https://learn.microsoft.com/azure/postgresql/flexible-server/how-to-manage-azure-ad-users
  - https://learn.microsoft.com/azure/postgresql/flexible-server/how-to-create-users
  - https://learn.microsoft.com/azure/postgresql/flexible-server/concepts-networking-private
  - https://learn.microsoft.com/azure/postgresql/flexible-server/concepts-backup-restore
  - https://learn.microsoft.com/azure/postgresql/flexible-server/concepts-business-continuity
  - https://learn.microsoft.com/azure/postgresql/flexible-server/how-to-server-parameters-set-value
  - https://learn.microsoft.com/azure/templates/microsoft.dbforpostgresql/flexibleservers
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2025-08-01"
last_reviewed: 2026-05-11
---

# Azure Database for PostgreSQL Flexible Server

## When to use this skill

- The user wants managed PostgreSQL on Azure for an OLTP workload.
- The user is migrating off the **retired Single Server** offering.
- The user needs Entra ID / managed-identity authentication to PostgreSQL.

## When NOT to use this skill

- The user wants serverless / pay-per-request data — use Cosmos DB.
- The user wants SQL Server compatibility — use Azure SQL Database.
- The workload needs PG superuser-level extensions or `pg_repack` /
  `wal2json` not in the [Flexible Server allow-list](https://learn.microsoft.com/azure/postgresql/flexible-server/concepts-extensions) — consider
  Cosmos DB for PostgreSQL or self-hosted PG on a VM.

## Prerequisites

- Azure CLI `>= 2.60.0`.
- A delegated subnet (delegated to `Microsoft.DBforPostgreSQL/flexibleServers`)
  in a VNet, plus a private DNS zone — see [`networking/azure-private-endpoint`](../../networking/azure-private-endpoint/SKILL.md)
  for DNS-zone patterns. Subnet minimum is `/28` (Azure reserves 5 IPs;
  HA uses 4 addresses).
- A region with multiple availability zones if you want zone-redundant HA.
- An Entra ID identity (user, group, or SP/MI) to act as the Entra
  administrator.

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| `--tier` / `sku.tier` | `GeneralPurpose` (prod), `Burstable` (dev only) | HA and read replicas are **not available on Burstable** (`Standard_B*`). |
| `--version` / `properties.version` | `'17'` (current GA recommended) | Pin to a major version. PG 11 is reaching EOL. |
| `--high-availability` / `properties.highAvailability.mode` | `'ZoneRedundant'` | Synchronous standby in a different AZ. RTO < 120 s, RPO = 0. |
| `--backup-retention` / `properties.backup.backupRetentionDays` | `14` | Default 7; range 7–35. |
| `properties.backup.geoRedundantBackup` | `'Enabled'` | Geo-restore to paired region. **Cannot be changed after creation.** |
| `properties.network.publicNetworkAccess` | `'Disabled'` | No public endpoint. |
| `--vnet`, `--subnet`, `--private-dns-zone` (or Bicep `network.delegatedSubnetResourceId` + `network.privateDnsZoneArmResourceId`) | (resource IDs) | VNet integration. **Networking mode cannot be changed after creation.** |
| `properties.authConfig.activeDirectoryAuth` | `'Enabled'` | Entra token auth. |
| `properties.authConfig.passwordAuth` | `'Disabled'` | Entra-only. Set `'Enabled'` for mixed-mode if you must. |
| `properties.storage.autoGrow` | `'Enabled'` | Auto-expand storage near limit. |

> **Immutable-at-creation:** `geoRedundantBackup`, `publicNetworkAccess` /
> VNet networking mode (public ↔ VNet). Plan these up front.

## Recipe — Azure CLI

```bash
RG=rg-pg-prod
LOC=eastus
SERVER=pg-app-prod-$RANDOM
VNET=vnet-pg
SUBNET=snet-pg
DNS_ZONE="${SERVER}.private.postgres.database.azure.com"
PG_VERSION=17
ADMIN=pgadmin
ADMIN_PASSWORD='<strong-password>'

az group create -n "$RG" -l "$LOC"

# 1. VNet + delegated subnet (delegated to the PG flexible-servers RP)
az network vnet create -g "$RG" -n "$VNET" -l "$LOC" --address-prefix 10.0.0.0/16
az network vnet subnet create -g "$RG" --vnet-name "$VNET" -n "$SUBNET" \
  --address-prefix 10.0.1.0/24 \
  --delegations Microsoft.DBforPostgreSQL/flexibleServers
SUBNET_ID=$(az network vnet subnet show -g "$RG" --vnet-name "$VNET" -n "$SUBNET" --query id -o tsv)

# 2. Private DNS zone + VNet link
az network private-dns zone create -g "$RG" -n "$DNS_ZONE"
az network private-dns link vnet create -g "$RG" -z "$DNS_ZONE" -n pg-dns-link \
  --virtual-network "$VNET" --registration-enabled false
DNS_ZONE_ID=$(az network private-dns zone show -g "$RG" -n "$DNS_ZONE" --query id -o tsv)

# 3. Create the server (General Purpose, ZR-HA, VNet, no public access)
az postgres flexible-server create \
  -g "$RG" -n "$SERVER" -l "$LOC" \
  --admin-user "$ADMIN" --admin-password "$ADMIN_PASSWORD" \
  --tier GeneralPurpose --sku-name Standard_D4ds_v5 \
  --version "$PG_VERSION" \
  --high-availability ZoneRedundant --zone 1 --standby-zone 2 \
  --storage-size 128 --backup-retention 14 \
  --vnet "$VNET" --subnet "$SUBNET_ID" --private-dns-zone "$DNS_ZONE_ID"

# 4. Add the Entra administrator (CLI for ad-admin may be limited;
#    portal: Server → Security → Authentication → Add Microsoft Entra Admin
#    is the documented path as of the research date)

# 5. Connect as the Entra admin and create roles for app identities
export PGPASSWORD=$(az account get-access-token --resource-type oss-rdbms --query accessToken -o tsv)
psql "host=${SERVER}.postgres.database.azure.com user=admin@contoso.onmicrosoft.com dbname=postgres sslmode=require"

# Inside psql:
#   SELECT pgaadauth_create_principal('app-mi-name', false, false);
#   -- Or with explicit object ID (preferred for managed identities):
#   SELECT pgaadauth_create_principal_with_oid('app-mi-name', '<objectId>', 'service', false, false);
#   GRANT CONNECT ON DATABASE app_db TO "app-mi-name";

# 6. Tweak a server parameter (dynamic — no restart)
az postgres flexible-server parameter set \
  -g "$RG" --server-name "$SERVER" --name work_mem --value 65536

# 7. Point-in-time restore (creates a NEW server)
az postgres flexible-server restore \
  -g "$RG" -n "${SERVER}-restored" --source-server "$SERVER" \
  --restore-time "2026-05-01T10:00:00Z"
```

## Recipe — Bicep

```bicep
@description('Server name (3-63 chars, alphanumeric + hyphens)')
param serverName string
param location string = resourceGroup().location
@secure()
param administratorLoginPassword string
param delegatedSubnetId string
param privateDnsZoneId string
param pgVersion string = '17'

resource pg 'Microsoft.DBforPostgreSQL/flexibleServers@2025-08-01' = {
  name: serverName
  location: location
  sku: {
    name: 'Standard_D4ds_v5'
    tier: 'GeneralPurpose'   // Burstable cannot use HA or read replicas
  }
  properties: {
    version: pgVersion
    administratorLogin: 'pgadmin'
    administratorLoginPassword: administratorLoginPassword
    authConfig: {
      activeDirectoryAuth: 'Enabled'
      passwordAuth: 'Disabled'
    }
    highAvailability: {
      mode: 'ZoneRedundant'
      standbyAvailabilityZone: '2'
    }
    availabilityZone: '1'
    network: {
      delegatedSubnetResourceId: delegatedSubnetId
      privateDnsZoneArmResourceId: privateDnsZoneId
      publicNetworkAccess: 'Disabled'
    }
    storage: {
      storageSizeGB: 128
      autoGrow: 'Enabled'
    }
    backup: {
      backupRetentionDays: 14
      geoRedundantBackup: 'Enabled'   // immutable after creation
    }
  }
}

output fqdn string = pg.properties.fullyQualifiedDomainName
```

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| `connection to server ... failed` / timeout | VNet-integrated server but client isn't on the VNet (or peered VNet); or public access is disabled and no PE exists | Move client onto the VNet, peer VNets, or provision a new server with public access. **Networking mode cannot be flipped post-creation.** ([Source](https://learn.microsoft.com/azure/postgresql/flexible-server/concepts-networking-private)) |
| `FATAL: password authentication failed` with an Entra token | Entra admin not set, OR the role for the principal hasn't been created via `pgaadauth_create_principal`, OR `passwordAuth: Disabled` while a password is being used | Set the Entra admin first; create the PG role inside psql before the app connects. |
| Token rejected after ~60 minutes | Entra access tokens expire | Acquire a fresh token per connection — use a credential with auto-refresh in the SDK. ([Source](https://learn.microsoft.com/azure/postgresql/flexible-server/concepts-azure-ad-authentication)) |
| Deleted Entra user can still connect for up to 60 minutes | Cached token still valid; PG validates only on connect | `DROP ROLE rolename;` immediately after deleting the Entra principal. |
| HA failover loses in-flight transactions | RPO = 0 only for **committed** data; in-flight txns at the moment of failover are lost | App must use idempotent retries. ([Source](https://learn.microsoft.com/azure/postgresql/flexible-server/concepts-business-continuity)) |
| `az postgres flexible-server create` errors: "HA not available on selected SKU/tier" | Trying to use HA on Burstable | Pick `--tier GeneralPurpose` and a `Standard_D*` SKU. |
| Parameter change has no effect | The parameter is **static** — needs a restart | Restart the server (or use `--save-and-restart` if available). ([Source](https://learn.microsoft.com/azure/postgresql/flexible-server/how-to-server-parameters-set-value)) |
| Cannot enable geo-redundant backup post-hoc | Backup redundancy is **immutable after creation** | Plan up front, or PITR/dump-and-restore into a new server with the right setting. |

## References

- [Quickstart: create with Azure CLI](https://learn.microsoft.com/azure/postgresql/flexible-server/quickstart-create-server-cli)
- [Quickstart: create with Bicep](https://learn.microsoft.com/azure/postgresql/flexible-server/quickstart-create-server-bicep)
- [Configure Microsoft Entra authentication](https://learn.microsoft.com/azure/postgresql/flexible-server/how-to-configure-sign-in-azure-ad-authentication)
- [Concepts: Microsoft Entra authentication](https://learn.microsoft.com/azure/postgresql/flexible-server/concepts-azure-ad-authentication)
- [Manage Microsoft Entra users](https://learn.microsoft.com/azure/postgresql/flexible-server/how-to-manage-azure-ad-users)
- [Networking concepts (private)](https://learn.microsoft.com/azure/postgresql/flexible-server/concepts-networking-private)
- [Backup and restore concepts](https://learn.microsoft.com/azure/postgresql/flexible-server/concepts-backup-restore)
- [Business continuity (HA)](https://learn.microsoft.com/azure/postgresql/flexible-server/concepts-business-continuity)
- [Server parameters](https://learn.microsoft.com/azure/postgresql/flexible-server/how-to-server-parameters-set-value)
- [Microsoft.DBforPostgreSQL/flexibleServers template reference](https://learn.microsoft.com/azure/templates/microsoft.dbforpostgresql/flexibleservers)
