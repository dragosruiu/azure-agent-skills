---
name: azure-cosmos-db
description: >
  Provision Azure Cosmos DB for NoSQL with secure defaults: disable local
  (key) auth, force Entra ID via the native Cosmos data-plane RBAC,
  zone-redundant multi-region with auto-failover, public network access
  disabled. Notes the serverless-vs-provisioned tradeoff and 429 / hot-
  partition diagnosis.
version: 0.1.0
azure_services:
  - Microsoft.DocumentDB/databaseAccounts
  - Microsoft.DocumentDB/databaseAccounts/sqlDatabases
  - Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers
  - Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments
tags:
  - data
  - nosql
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/cosmos-db/nosql/how-to-create-account
  - https://learn.microsoft.com/azure/cosmos-db/nosql/security/how-to-grant-data-plane-role-based-access
  - https://learn.microsoft.com/azure/cosmos-db/reference-data-plane-security
  - https://learn.microsoft.com/azure/cosmos-db/serverless
  - https://learn.microsoft.com/azure/cosmos-db/throughput-serverless
  - https://learn.microsoft.com/azure/cosmos-db/how-to-configure-private-endpoints
  - https://learn.microsoft.com/azure/cosmos-db/how-to-manage-database-account
  - https://learn.microsoft.com/azure/cosmos-db/nosql/manage-with-bicep
  - https://learn.microsoft.com/azure/cosmos-db/troubleshoot-request-rate-too-large
  - https://learn.microsoft.com/cli/azure/cosmosdb/sql/role/assignment
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2024-11-15"
last_reviewed: 2026-05-11
---

# Azure Cosmos DB for NoSQL (secure baseline)

## When to use this skill

- The user is creating a Cosmos DB account for the NoSQL (SQL) API.
- The user wants global / zone-redundant document storage with single-
  digit ms reads at the 99th percentile.
- The user is migrating from key-based auth to Entra ID.

## When NOT to use this skill

- The user wants Mongo, Cassandra, Gremlin, or PostgreSQL APIs — those
  have different RBAC and config surfaces; consult their Learn pages.
- The user wants relational ACID transactions across rows — use
  PostgreSQL Flexible Server or Azure SQL DB.
- The user wants serverless **and** multi-region — serverless is
  single-region only. Use provisioned throughput.

## Prerequisites

- Azure CLI `>= 2.60.0`.
- The deployment principal needs `Cosmos DB Operator` (or `Contributor`)
  to create the account and `Microsoft.Authorization/roleAssignments/write`
  to grant data-plane RBAC.
- Pick a partition key with high cardinality and even traffic distribution
  *before* writing data — see the troubleshooting guide.

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| `properties.disableLocalAuth` | `true` | Forces Entra ID; primary/secondary keys and connection strings are rejected at the service layer. ([Source](https://learn.microsoft.com/azure/cosmos-db/nosql/security/how-to-grant-data-plane-role-based-access)) |
| `properties.publicNetworkAccess` | `'Disabled'` | Block all public ingress; pair with a private endpoint to `privatelink.documents.azure.com`. |
| `properties.enableAutomaticFailover` | `true` (with ≥ 2 regions) | Service-managed failover to the highest-priority region. |
| `properties.locations[].isZoneRedundant` | `true` | AZ-redundancy within each region. |
| `properties.consistencyPolicy.defaultConsistencyLevel` | `'Session'` | Balanced default. Stronger levels are required only for specific compliance needs and add latency. |
| `properties.enableMultipleWriteLocations` | `false` (default) | Only set `true` if you genuinely need active-active writes; multi-region writes prevent Strong consistency and add conflict-resolution complexity. ([Source](https://learn.microsoft.com/azure/cosmos-db/multi-region-writes)) |
| Capacity mode | **Serverless** for single-region dev / unpredictable spiky workloads under 50 GB; **Provisioned** for prod, multi-region, or sustained throughput | Serverless is single-region only and capped (current limits documented at [serverless](https://learn.microsoft.com/azure/cosmos-db/serverless)). |
| Container throughput | Autoscale `maxThroughput: 4000` for typical apps | Lets the container grow 10× without re-provisioning; you pay for what you use. |

## Cosmos data-plane is special

Cosmos DB for NoSQL **does not** use the standard ARM RBAC subsystem for
data-plane access. Use the Cosmos-specific subcommands and built-in role
definitions stored inside the account ([source](https://learn.microsoft.com/azure/cosmos-db/reference-data-plane-security)):

| Built-in role | Role definition ID |
| --- | --- |
| Cosmos DB Built-in Data Reader | `00000000-0000-0000-0000-000000000001` |
| Cosmos DB Built-in Data Contributor | `00000000-0000-0000-0000-000000000002` |

> Always confirm the IDs with `az cosmosdb sql role definition list --account-name $ACCOUNT --resource-group $RG`.

## Recipe — Azure CLI

```bash
RG=rg-cosmos-prod
LOC=eastus
LOC2=westus3
ACCOUNT=cosmos-app-prod-$RANDOM
PRINCIPAL_ID=<objectId-of-app-managed-identity>

# 1. Resource group
az group create -n "$RG" -l "$LOC"

# 2. Create the account (multi-region, zone-redundant, auto-failover, Session)
#    Note: disableLocalAuth and publicNetworkAccess can be set via `az resource update`
#          after creation. Bicep is cleaner for these — see Bicep recipe below.
az cosmosdb create \
  -g "$RG" -n "$ACCOUNT" \
  --kind GlobalDocumentDB \
  --locations regionName="$LOC"  failoverPriority=0 isZoneRedundant=true \
  --locations regionName="$LOC2" failoverPriority=1 isZoneRedundant=true \
  --enable-automatic-failover true \
  --default-consistency-level Session

# 3. Disable local key auth (force Entra ID)
az resource update \
  -g "$RG" -n "$ACCOUNT" \
  --resource-type Microsoft.DocumentDB/databaseAccounts \
  --set properties.disableLocalAuth=true

# 4. Disable public network access (then add a private endpoint — see networking/azure-private-endpoint)
az resource update \
  -g "$RG" -n "$ACCOUNT" \
  --resource-type Microsoft.DocumentDB/databaseAccounts \
  --set properties.publicNetworkAccess=Disabled

# 5. Grant data-plane RBAC to a managed identity (account-wide scope)
az cosmosdb sql role assignment create \
  -g "$RG" --account-name "$ACCOUNT" \
  --role-definition-name "Cosmos DB Built-in Data Contributor" \
  --principal-id "$PRINCIPAL_ID" \
  --scope "/"

# 6. Create database + container
az cosmosdb sql database create  -g "$RG" -a "$ACCOUNT" -n mydb
az cosmosdb sql container create -g "$RG" -a "$ACCOUNT" -d mydb -n mycontainer \
  --partition-key-path "/tenantId" --throughput 400
```

> The app then uses `DefaultAzureCredential` from the Azure SDK — no
> connection string. The SDK's metadata calls require the `readMetadata`
> permission, which is included in both built-in data-plane roles.

## Recipe — Bicep

```bicep
param accountName string
param primaryLocation string = resourceGroup().location
param secondaryLocation string
param dataPrincipalId string

var builtInDataContributorRoleId = '00000000-0000-0000-0000-000000000002'

resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' = {
  name: accountName
  location: primaryLocation
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    disableLocalAuth: true
    publicNetworkAccess: 'Disabled'
    consistencyPolicy: { defaultConsistencyLevel: 'Session' }
    locations: [
      { locationName: primaryLocation,   failoverPriority: 0, isZoneRedundant: true }
      { locationName: secondaryLocation, failoverPriority: 1, isZoneRedundant: true }
    ]
    enableAutomaticFailover: true
    enableMultipleWriteLocations: false
  }
}

resource db 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-11-15' = {
  parent: cosmosAccount
  name: 'mydb'
  properties: { resource: { id: 'mydb' } }
}

resource container 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-11-15' = {
  parent: db
  name: 'mycontainer'
  properties: {
    resource: {
      id: 'mycontainer'
      partitionKey: { paths: [ '/tenantId' ], kind: 'Hash' }
      indexingPolicy: {
        indexingMode: 'consistent'
        includedPaths: [ { path: '/*' } ]
        excludedPaths: [ { path: '/_etag/?' } ]
      }
    }
    options: { autoscaleSettings: { maxThroughput: 4000 } }
  }
}

resource dataRole 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = {
  parent: cosmosAccount
  name: guid(cosmosAccount.id, dataPrincipalId, builtInDataContributorRoleId)
  properties: {
    roleDefinitionId: '${cosmosAccount.id}/sqlRoleDefinitions/${builtInDataContributorRoleId}'
    principalId: dataPrincipalId
    scope: cosmosAccount.id
  }
}

output endpoint string = cosmosAccount.properties.documentEndpoint
```

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| `Unauthorized (401)` from the SDK | App is using a connection string but `disableLocalAuth: true` | Switch to `DefaultAzureCredential`. Grant a Cosmos DB SQL data-plane role via `az cosmosdb sql role assignment create`. |
| 401 even with `DefaultAzureCredential` and a role assigned | Custom role missing `Microsoft.DocumentDB/databaseAccounts/readMetadata` (the SDK calls it on init) | Use a built-in role, or include `readMetadata` in your custom role. ([Source](https://learn.microsoft.com/azure/cosmos-db/reference-data-plane-security)) |
| 429 `Request rate too large` spikes | Exceeding RU/s. **Hot partition** if one PartitionKeyRangeId is at 100% normalized RU consumption while others are idle. | (a) <5% rate is normal — retry. (b) Hot partition: redesign partition key to higher cardinality (composite or synthetic key); avoid `tenantId` if traffic is skewed. (c) Short-term: raise max RU/s or enable autoscale. ([Source](https://learn.microsoft.com/azure/cosmos-db/troubleshoot-request-rate-too-large)) |
| Cross-partition queries are slow | Low-cardinality partition key forces full fan-out | Choose partition key matching your most common query filter. |
| Serverless account create fails: "multi-region not supported" | Serverless is single-region by design | Use provisioned throughput for any geo-distribution. ([Source](https://learn.microsoft.com/azure/cosmos-db/serverless)) |
| Private endpoint added but DNS still resolves to public IP | Private DNS zone `privatelink.documents.azure.com` not linked to the consuming VNet | Create + link the zone (or check the "Integrate with private DNS zone" box during PE creation). ([Source](https://learn.microsoft.com/azure/cosmos-db/how-to-configure-private-endpoints)) |

## References

- [Create a Cosmos DB account (NoSQL)](https://learn.microsoft.com/azure/cosmos-db/nosql/how-to-create-account)
- [Grant data-plane RBAC](https://learn.microsoft.com/azure/cosmos-db/nosql/security/how-to-grant-data-plane-role-based-access)
- [Data-plane security reference (built-in roles)](https://learn.microsoft.com/azure/cosmos-db/reference-data-plane-security)
- [Serverless capacity mode](https://learn.microsoft.com/azure/cosmos-db/serverless)
- [Serverless vs provisioned](https://learn.microsoft.com/azure/cosmos-db/throughput-serverless)
- [Configure private endpoints](https://learn.microsoft.com/azure/cosmos-db/how-to-configure-private-endpoints)
- [Manage account (failover, regions)](https://learn.microsoft.com/azure/cosmos-db/how-to-manage-database-account)
- [Manage with Bicep](https://learn.microsoft.com/azure/cosmos-db/nosql/manage-with-bicep)
- [Troubleshoot 429s](https://learn.microsoft.com/azure/cosmos-db/troubleshoot-request-rate-too-large)
- [`az cosmosdb sql role assignment`](https://learn.microsoft.com/cli/azure/cosmosdb/sql/role/assignment)
