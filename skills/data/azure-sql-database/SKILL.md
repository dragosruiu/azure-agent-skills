---
name: azure-sql-database
description: >
  Provision an Azure SQL Database with secure defaults: Microsoft Entra-only
  authentication, public network access disabled with a private endpoint to
  `privatelink.database.windows.net`, vCore General Purpose Serverless,
  Microsoft Defender for SQL enabled, and PITR retention 14 days.
version: 0.1.0
azure_services:
  - Microsoft.Sql/servers
  - Microsoft.Sql/servers/databases
  - Microsoft.Sql/servers/azureADOnlyAuthentications
tags:
  - data
  - relational
  - sql
  - security-baseline
sources:
  - https://learn.microsoft.com/cli/azure/sql/server
  - https://learn.microsoft.com/azure/azure-sql/database/authentication-aad-overview
  - https://learn.microsoft.com/azure/azure-sql/database/authentication-azure-ad-only-authentication
  - https://learn.microsoft.com/azure/azure-sql/database/connectivity-settings
  - https://learn.microsoft.com/azure/azure-sql/database/private-endpoint-overview
  - https://learn.microsoft.com/azure/azure-sql/database/serverless-tier-overview
  - https://learn.microsoft.com/azure/azure-sql/database/automated-backups-overview
  - https://learn.microsoft.com/azure/defender-for-cloud/defender-for-sql-introduction
  - https://learn.microsoft.com/azure/templates/microsoft.sql/servers
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2025-01-01"
last_reviewed: 2026-05-11
---

# Azure SQL Database (secure baseline)

## When to use this skill

- The user wants a managed SQL Server (T-SQL, OLTP) database on Azure.
- The user wants Entra-only auth (no SQL admin password).
- The user wants serverless auto-pause for spiky / dev workloads.

## When NOT to use this skill

- The user wants PostgreSQL / MySQL / MariaDB → see
  [`azure-postgresql-flexible`](../azure-postgresql-flexible/SKILL.md).
- The user wants document/JSON store → see
  [`azure-cosmos-db`](../azure-cosmos-db/SKILL.md).
- The workload needs SQL Server features only available on Managed
  Instance (CLR, SQL Agent, cross-DB queries) — pick SQL MI.

## Prerequisites

- An Entra ID identity (user, group, or SP) to be the server admin —
  get its **object ID** with `az ad user show --id <upn> --query id -o tsv`.
- A subnet for the private endpoint (with `privateEndpointNetworkPolicies: 'Disabled'`).
- The deployment principal needs `SQL Server Contributor` or `Contributor`.

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| `--enable-ad-only-auth` (or `properties.administrators.azureADOnlyAuthentication: true`) | enabled | Disables the SQL admin password. **Set the Entra admin first** in the same call. |
| `--external-admin-principal-type` | `User` / `Group` / `Application` | Required with `--enable-ad-only-auth`. |
| `--external-admin-name`, `--external-admin-sid` | UPN/group + object ID | The Entra principal that becomes server admin. |
| `--enable-public-network` | `false` (`publicNetworkAccess: 'Disabled'`) | Pair with a private endpoint. |
| `--minimal-tls-version` | `1.2` (or `1.3`) | Reject older TLS. |
| `--assign-identity` (on server) | enabled | Server MI for BYOK TDE / outbound auth. |
| Database compute model | **vCore General Purpose Serverless** for dev/spiky; vCore Provisioned for steady prod | Avoid DTU; vCore is the modern path. |
| `--auto-pause-delay` (Serverless) | `60` (minutes); `-1` to disable | Auto-pause idle DBs to control cost; cold start ~1 min on resume. |
| `--backup-storage-redundancy` | `Geo` (or `Zone`/`Local` per RTO) | Enables geo-restore. |
| PITR retention (`az sql db str-policy set --retention-days`) | `14` | Default is 7; range 1–35. |
| Microsoft Defender for SQL | enabled (subscription level preferred) | Threat detection, vuln assessment. |
| TDE | service-managed (default) — switch to CMK if your compliance needs it | Encryption at rest. |

> ⚠️ **Bicep caveat:** the `azureADOnlyAuthentication` flag on
> `properties.administrators` is only effective at server **creation**.
> To **toggle** it later, use the `Microsoft.Sql/servers/azureADOnlyAuthentications`
> child resource or `az sql server ad-only-auth enable`.
> ([Source](https://learn.microsoft.com/azure/templates/microsoft.sql/servers))

## Recipe — Azure CLI

```bash
RG=rg-sql-prod
LOC=eastus
SERVER=sqlsrv-app-prod-$RANDOM
DB=appdb
ADMIN_UPN=sqladmin@contoso.com
ADMIN_OID=$(az ad user show --id "$ADMIN_UPN" --query id -o tsv)

az group create -n "$RG" -l "$LOC"

# 1. Logical server: Entra-only, public access OFF, system MI
az sql server create -g "$RG" -n "$SERVER" -l "$LOC" \
  --enable-ad-only-auth \
  --external-admin-principal-type User \
  --external-admin-name "$ADMIN_UPN" \
  --external-admin-sid "$ADMIN_OID" \
  --enable-public-network false \
  --minimal-tls-version 1.2 \
  --assign-identity

# 2. Database: vCore General Purpose Serverless, geo-redundant backup
az sql db create -g "$RG" -s "$SERVER" -n "$DB" \
  --edition GeneralPurpose --family Gen5 \
  --capacity 4 --compute-model Serverless \
  --min-capacity 0.5 --auto-pause-delay 60 \
  --backup-storage-redundancy Geo

# 3. Defender for SQL
az sql server advanced-threat-protection-setting update -g "$RG" -n "$SERVER" --state Enabled

# 4. PITR retention (range 1-35; default 7)
az sql db str-policy set -g "$RG" -s "$SERVER" -n "$DB" --retention-days 14

# 5. Private endpoint to privatelink.database.windows.net (groupId = sqlServer)
SERVER_ID=$(az sql server show -g "$RG" -n "$SERVER" --query id -o tsv)
az network private-endpoint create -g "$RG" -n "pe-$SERVER" \
  --vnet-name vnet-app --subnet snet-pe \
  --private-connection-resource-id "$SERVER_ID" \
  --connection-name "pec-$SERVER" --group-id sqlServer
az network private-dns zone create -g "$RG" -n privatelink.database.windows.net
az network private-dns link vnet create -g "$RG" -n vnet-app-link \
  -z privatelink.database.windows.net --virtual-network vnet-app --registration-enabled false
az network private-endpoint dns-zone-group create -g "$RG" --endpoint-name "pe-$SERVER" \
  -n zg-sql --private-dns-zone privatelink.database.windows.net --zone-name sql
```

Then connect as the Entra admin and create contained users for app
identities:

```sql
USE [appdb];
CREATE USER [app-mi-name] FROM EXTERNAL PROVIDER;
ALTER ROLE db_datareader ADD MEMBER [app-mi-name];
ALTER ROLE db_datawriter ADD MEMBER [app-mi-name];
```

## Recipe — Bicep

```bicep
param serverName string
param dbName string
param location string = resourceGroup().location
@description('Entra principal that becomes the server admin')
param adminLoginName string
param adminObjectId string
param tenantId string = subscription().tenantId

resource sqlServer 'Microsoft.Sql/servers@2025-01-01' = {
  name: serverName
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    publicNetworkAccess: 'Disabled'
    minimalTlsVersion: '1.2'
    administrators: {
      administratorType: 'ActiveDirectory'
      principalType: 'User'         // or Group / Application
      login: adminLoginName
      sid: adminObjectId            // Entra object ID (GUID)
      tenantId: tenantId
      azureADOnlyAuthentication: true   // effective at creation only
    }
  }
}

resource db 'Microsoft.Sql/servers/databases@2025-01-01' = {
  parent: sqlServer
  name: dbName
  location: location
  sku: { name: 'GP_S_Gen5_4', tier: 'GeneralPurpose', family: 'Gen5', capacity: 4 }
  properties: {
    requestedBackupStorageRedundancy: 'Geo'
    autoPauseDelay: 60
    minCapacity: json('0.5')
    zoneRedundant: false
  }
}
```

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| Cannot connect: `Cannot open server requested by the login` | Public access is disabled and no firewall rule / private endpoint | Add a private endpoint, or temporarily enable public + add a firewall rule. |
| `Login failed for user` after enabling Entra-only | App is using the SQL admin password | Switch the app to `DefaultAzureCredential`; create a contained user `FROM EXTERNAL PROVIDER`. |
| Bicep deployment hangs / fails to flip `azureADOnlyAuthentication` | The property is creation-time only on the parent resource | Use the `Microsoft.Sql/servers/azureADOnlyAuthentications` child resource (or `az sql server ad-only-auth enable`). ([Source](https://learn.microsoft.com/azure/templates/microsoft.sql/servers)) |
| Serverless DB has cold-start latency on first request after idle | `autoPauseDelay` paused the DB | Set `--auto-pause-delay -1` to disable, or accept the ~1 min wake. |
| `azureADOnlyAuthentication` accidentally enabled and admin can't sign in | The SQL admin password is now rejected | Re-enable mixed mode via `az sql server ad-only-auth disable -g $RG -n $SERVER`. |
| TDE BYOK setup fails | Server MI lacks `Key Vault Crypto Service Encryption User` on the vault | Grant the role to the server's MI principal. |

## References

- [`az sql server` reference](https://learn.microsoft.com/cli/azure/sql/server)
- [Microsoft Entra authentication overview](https://learn.microsoft.com/azure/azure-sql/database/authentication-aad-overview)
- [Microsoft Entra-only authentication](https://learn.microsoft.com/azure/azure-sql/database/authentication-azure-ad-only-authentication)
- [Connectivity settings (TLS, public access)](https://learn.microsoft.com/azure/azure-sql/database/connectivity-settings)
- [Private endpoint overview](https://learn.microsoft.com/azure/azure-sql/database/private-endpoint-overview)
- [Serverless compute tier](https://learn.microsoft.com/azure/azure-sql/database/serverless-tier-overview)
- [Automated backups](https://learn.microsoft.com/azure/azure-sql/database/automated-backups-overview)
- [Microsoft Defender for SQL](https://learn.microsoft.com/azure/defender-for-cloud/defender-for-sql-introduction)
- [`Microsoft.Sql/servers` template reference](https://learn.microsoft.com/azure/templates/microsoft.sql/servers)
