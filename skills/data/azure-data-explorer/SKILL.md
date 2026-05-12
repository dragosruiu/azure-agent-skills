---
name: azure-data-explorer
description: >
  Provision an Azure Data Explorer (Kusto) cluster + database with
  system MI, public network access disabled, restrictive outbound,
  empty `trustedExternalTenants`, and disk encryption. Data-plane
  access is via Database Admin / User / Viewer roles set inside the
  database (not Azure RBAC).
version: 0.1.0
azure_services:
  - Microsoft.Kusto/clusters
  - Microsoft.Kusto/clusters/databases
tags:
  - data
  - analytics
  - kusto
  - kql
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/data-explorer/data-explorer-overview
  - https://learn.microsoft.com/azure/templates/microsoft.kusto/clusters
  - https://learn.microsoft.com/azure/templates/microsoft.kusto/clusters/databases
  - https://learn.microsoft.com/azure/data-explorer/manage-database-permissions
  - https://learn.microsoft.com/azure/data-explorer/ingest-data-overview
  - https://learn.microsoft.com/kusto/query
validated_with:
  az_cli: ">=2.60.0 (with `kusto` extension; experimental)"
  api_version: "2025-02-14"
last_reviewed: 2026-05-12
---

# Azure Data Explorer (Kusto)

## When to use this skill

- Time-series / telemetry / log analytics at scale (KQL).
- Free-text search + aggregations across very large datasets.
- A query backend for Grafana / Power BI / custom dashboards over
  high-volume event data.

## When NOT to use this skill

- Transactional / OLTP workloads — use Azure SQL or PostgreSQL.
- Document-style retrieval — use Cosmos DB or Azure AI Search.
- One-shot log queries on Azure resource logs — Log Analytics is
  already there and cheaper for that use case.

> The `az kusto` CLI extension is marked **experimental**; CLI surface
> may change. Verify with `az kusto cluster create --help`.

## SKU picker

| Series | Examples | Best for |
| --- | --- | --- |
| **Standard_E*** (memory-optimized) | `Standard_E8ads_v5`, `Standard_E16ads_v5` | Most analytics workloads (recommended default) |
| **Standard_L*** (storage-optimized) | `Standard_L8s_v3`, `Standard_L32s_v3` | Very large datasets where hot cache > compute matters |
| **Standard_D*** (general) | `Standard_D32d_v5` | General compute |
| **Dev (No SLA)** | `Dev(No SLA)_Standard_D11_v2`, `Dev(No SLA)_Standard_E2a_v4` | Dev/test only |

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| `identity.type` | `'SystemAssigned'` | For ingestion auth (Event Hubs / Storage / KV). |
| `properties.publicNetworkAccess` | `'Disabled'` | Pair with PE to `privatelink.<region>.kusto.windows.net`. |
| `properties.restrictOutboundNetworkAccess` | `'Enabled'` | Cluster can only reach approved outbound destinations. |
| `properties.trustedExternalTenants` | `[]` (empty) | Same-tenant only. Add other tenant IDs only if cross-tenant query is required. |
| `properties.enableDiskEncryption` | `true` | At-rest encryption. |
| `properties.enableDoubleEncryption` | `true` for compliance scenarios | Two layers — service + infra. |
| `properties.enableAutoStop` | `false` for prod | Auto-stop is good for dev; bad for production query latency. |
| `properties.enablePurge` | `false` (default) — only `true` if GDPR/right-to-be-forgotten needed | Enables `.purge` management commands. |
| `properties.enableStreamingIngest` | `true` only if you need < 10 s ingestion latency | Trade-off: streaming latency vs queued throughput. |
| `optimizedAutoscale` | enabled, `min` and `max` set | Cost guardrails. |
| `zones` | `['1','2','3']` where supported | AZ-redundant. |
| Database `softDeletePeriod` | `'P365D'` (1 year) typical; longer for compliance | Determines how long data is queryable. |
| Database `hotCachePeriod` | `'P31D'` typical | Data in hot cache returns sub-second; outside it goes through cold queries (still fast, just slower). |

## Data-plane roles (KQL-managed, not Azure RBAC)

Verified from [manage-database-permissions](https://learn.microsoft.com/azure/data-explorer/manage-database-permissions):

| Role | Capability |
| --- | --- |
| **Database Admin** | Full data + management on the database. |
| **Database User** | Run queries; create tables / functions. |
| **Database Viewer** | Read-only — query, view schema. |
| **Database Ingestor** | Ingest data only. |
| **Database Monitor** | Read perf / system tables. |
| **Database Unrestricted Viewer** | Viewer + access to system metadata (less common). |

Set via **portal → Database → Permissions** or via KQL management commands:

```kusto
.add database mydb admins ('aaduser=user@contoso.onmicrosoft.com')
.add database mydb viewers ('aadgroup=<group-objectid>')
```

`az role assignment create` does **not** grant data-plane access here.

## Recipe — Azure CLI

```bash
az extension add --name kusto

RG=rg-adx-prod
LOC=eastus
CLUSTER=adx-app-prod
DB=appdb

# 1. Cluster (memory-optimized, 2 instances, MI on, public access off)
az kusto cluster create \
  -g "$RG" -n "$CLUSTER" -l "$LOC" \
  --sku name=Standard_E8ads_v5 capacity=2 tier=Standard \
  --type SystemAssigned \
  --enable-auto-stop false \
  --enable-disk-encryption true \
  --public-network-access Disabled \
  --restrict-outbound-network-access Enabled \
  --trusted-external-tenants "[]"

# 2. Database (1-year soft delete, 31-day hot cache)
az kusto database create \
  -g "$RG" --cluster-name "$CLUSTER" --database-name "$DB" \
  --read-write-database location="$LOC" soft-delete-period=P365D hot-cache-period=P31D

# 3. Grant Database Admin via KQL (run in the Data Explorer portal or via the SDK)
#    .add database appdb admins ('aaduser=user@contoso.com')

# 4. Private endpoint (groupId = cluster). The DNS zone is regional:
#    privatelink.<region>.kusto.windows.net
CLUSTER_ID=$(az kusto cluster show -g "$RG" -n "$CLUSTER" --query id -o tsv)
az network private-endpoint create -g "$RG" -n "pe-$CLUSTER" \
  --vnet-name vnet-app --subnet snet-pe \
  --private-connection-resource-id "$CLUSTER_ID" \
  --connection-name "pec-$CLUSTER" --group-id cluster
```

## Recipe — Bicep

```bicep
param clusterName string
param dbName string
param location string = resourceGroup().location

resource cluster 'Microsoft.Kusto/clusters@2025-02-14' = {
  name: clusterName
  location: location
  identity: { type: 'SystemAssigned' }
  sku: { name: 'Standard_E8ads_v5', tier: 'Standard', capacity: 2 }
  zones: [ '1', '2', '3' ]
  properties: {
    enableAutoStop: false
    enableDiskEncryption: true
    enableDoubleEncryption: false
    enablePurge: false
    enableStreamingIngest: false
    publicNetworkAccess: 'Disabled'
    restrictOutboundNetworkAccess: 'Enabled'
    trustedExternalTenants: []
    optimizedAutoscale: {
      isEnabled: true
      minimum: 2
      maximum: 10
      version: 1
    }
  }
}

resource db 'Microsoft.Kusto/clusters/databases@2025-02-14' = {
  parent: cluster
  name: dbName
  location: location
  kind: 'ReadWrite'
  properties: {
    softDeletePeriod: 'P365D'
    hotCachePeriod: 'P31D'
  }
}
```

## KQL starter set

```kusto
// take: bounded sample
StormEvents | take 10

// where + summarize: aggregation
StormEvents
| where StartTime > ago(7d)
| summarize EventCount = count() by State

// join (defaults to innerunique — deduplicates left rows)
StormEvents
| join kind=leftouter (Population | project State, Pop) on State
| summarize per_capita = sum(InjuriesDirect) / max(Pop) by State

// let: declare variables / scope subqueries
let cutoff = ago(1d);
StormEvents | where StartTime > cutoff | take 100

// Materialized view (precomputed; query the materialized part only)
materialized_view('MyView') | take 10
```

> `join` defaults to `innerunique` (dedupes the left side). When you
> need every left row, use `kind=leftouter`.

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| Cluster paused; queries time out | `enableAutoStop: true` and the cluster auto-stopped | Set `enableAutoStop: false` for prod. |
| `az role assignment` granted but user can't query | Data-plane access uses **KQL roles**, not Azure RBAC | Use `.add database <db> viewers (...)` (or admins/users) inside KQL. |
| Joins return surprising row counts | Default `join` kind is `innerunique` | Specify `kind=` explicitly (`leftouter`, `inner`, `fullouter`). |
| Streaming ingest latency > 10 s | `enableStreamingIngest` is `false`, so you're using queued ingestion | Enable streaming ingest on the cluster + table for low-latency paths. |
| Cold queries are slow | Data is outside the `hotCachePeriod` | Lengthen `hotCachePeriod` or accept the cold-query cost. |
| `.purge` fails | `enablePurge: false` | Set `enablePurge: true` only when GDPR-style deletes are genuinely required (it carries operational risk). |
| Cross-tenant query rejected | `trustedExternalTenants: []` | Add the other tenant ID(s) explicitly — but understand the security implications. |

## References

- [ADX overview](https://learn.microsoft.com/azure/data-explorer/data-explorer-overview)
- [`Microsoft.Kusto/clusters` template](https://learn.microsoft.com/azure/templates/microsoft.kusto/clusters)
- [`Microsoft.Kusto/clusters/databases` template](https://learn.microsoft.com/azure/templates/microsoft.kusto/clusters/databases)
- [Database permissions](https://learn.microsoft.com/azure/data-explorer/manage-database-permissions)
- [Ingest data overview](https://learn.microsoft.com/azure/data-explorer/ingest-data-overview)
- [KQL reference](https://learn.microsoft.com/kusto/query)
