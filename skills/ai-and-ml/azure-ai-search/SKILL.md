---
name: azure-ai-search
description: >
  Provision Azure AI Search with secure defaults: Standard SKU,
  `disableLocalAuth: true` to force Entra ID, public network access
  disabled with a private endpoint, semantic ranker on the `standard`
  plan, and a system-assigned MI used by indexers to read from Storage
  and call Azure OpenAI for integrated vectorization.
version: 0.1.0
azure_services:
  - Microsoft.Search/searchServices
tags:
  - ai-ml
  - search
  - rag
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/search/search-create-service-portal
  - https://learn.microsoft.com/azure/search/search-sku-tier
  - https://learn.microsoft.com/azure/search/search-security-rbac
  - https://learn.microsoft.com/azure/search/search-security-enable-roles
  - https://learn.microsoft.com/azure/search/service-create-private-endpoint
  - https://learn.microsoft.com/azure/search/semantic-search-overview
  - https://learn.microsoft.com/azure/search/vector-search-integrated-vectorization
  - https://learn.microsoft.com/azure/search/cognitive-search-skill-azure-openai-embedding
  - https://learn.microsoft.com/azure/search/search-howto-managed-identities-storage
  - https://learn.microsoft.com/azure/search/search-capacity-planning
  - https://learn.microsoft.com/azure/search/search-indexer-howto-access-private
  - https://learn.microsoft.com/azure/templates/microsoft.search/searchservices
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2025-05-01"
last_reviewed: 2026-05-11
---

# Azure AI Search (secure baseline)

## When to use this skill

- The user is building RAG: needs full-text + vector retrieval over
  documents.
- The user wants integrated vectorization (Search calls Azure OpenAI
  embedding models on insert/index).
- The user wants semantic ranker (BM25 results re-ranked by an L2 model).

## When NOT to use this skill

- The user wants a vector-only store with no full-text — a database
  vector column (PostgreSQL `pgvector`, Cosmos DB) may be cheaper.
- The user needs analytics queries (aggregations on huge data) — use
  Azure Data Explorer / Synapse.

## Tier picker

| Need | Tier |
| --- | --- |
| Dev / 50 MB / no SLA | Free |
| Small prod, low QPS | Basic |
| Standard prod, multi-index, semantic ranker | **Standard (S1 / S2 / S3)** |
| Many tenants in one service (1000+ indexes) | Standard 3 with `hostingMode: 'highDensity'` |
| Storage-optimized large indexes | L1 / L2 |

> Free tier doesn't support semantic ranker, private endpoints, or many
> production features. Don't ship on Free.

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| `sku.name` | `'standard'` for prod | S1 = 25 GB/partition, S2 = 100 GB, S3 = 200 GB. |
| `properties.disableLocalAuth` | `true` | Disables admin/query keys; forces Entra ID. **Cannot be set together with `authOptions`.** |
| `properties.publicNetworkAccess` | `'Disabled'` | Pair with a private endpoint to `privatelink.search.windows.net`. |
| `properties.semanticSearch` | `'standard'` (or `'free'` for tiny dev usage; `'disabled'` to opt out) | Free tier is 1,000 requests/month free, then no longer billed at all if `'disabled'`. |
| `properties.replicaCount` | `>= 2` for SLA, `>= 3` for high availability | Replicas scale **query** throughput; SLA needs ≥ 2 for read, ≥ 3 for read+write. |
| `properties.partitionCount` | `1` initially, scale up for storage / indexing throughput | Allowed: 1, 2, 3, 4, 6, 12. **Search Units (SU) = replicas × partitions; max 36.** |
| `identity.type` | `'SystemAssigned'` | Lets the search service pull from Storage / call Azure OpenAI without secrets. |

## RBAC roles (data-plane)

| Role | Use case |
| --- | --- |
| `Search Index Data Contributor` | Apps that read **and** write index content. |
| `Search Index Data Reader` | Read-only query traffic. |
| `Search Service Contributor` | Manage indexes / indexers / data sources (control plane). |

For each external resource the indexer touches, grant the search
service's MI:

- Storage: `Storage Blob Data Reader`
- Azure OpenAI: `Cognitive Services OpenAI User`

## Recipe — Azure CLI

```bash
RG=rg-search-prod
LOC=eastus
SVC=srch-app-prod-$RANDOM
SA=stappprod
AOAI=oai-app-prod
PRINCIPAL_ID=<objectId-of-app-managed-identity>

# 1. Create the service
az search service create -g "$RG" -n "$SVC" -l "$LOC" \
  --sku standard --replica-count 2 --partition-count 1

# 2. Disable local auth (force Entra ID); disable public network access
az search service update -g "$RG" -n "$SVC" --disable-local-auth true
az search service update -g "$RG" -n "$SVC" --public-access disabled

# 3. Enable system-assigned MI on the search service
az search service update -g "$RG" -n "$SVC" --identity-type SystemAssigned

# 4. Grant the search MI the roles it needs on Storage + Azure OpenAI
SA_ID=$(az storage account show -g "$RG" -n "$SA" --query id -o tsv)
AOAI_ID=$(az cognitiveservices account show -g "$RG" -n "$AOAI" --query id -o tsv)
SVC_PRINCIPAL=$(az search service show -g "$RG" -n "$SVC" --query identity.principalId -o tsv)

az role assignment create \
  --assignee-object-id "$SVC_PRINCIPAL" --assignee-principal-type ServicePrincipal \
  --role "Storage Blob Data Reader" --scope "$SA_ID"
az role assignment create \
  --assignee-object-id "$SVC_PRINCIPAL" --assignee-principal-type ServicePrincipal \
  --role "Cognitive Services OpenAI User" --scope "$AOAI_ID"

# 5. Grant the calling app data-plane access to query / index data
SVC_ID=$(az search service show -g "$RG" -n "$SVC" --query id -o tsv)
az role assignment create \
  --assignee-object-id "$PRINCIPAL_ID" --assignee-principal-type ServicePrincipal \
  --role "Search Index Data Contributor" --scope "$SVC_ID"

# 6. Private endpoint (groupId = searchService)
az network private-endpoint create -g "$RG" -n "pe-$SVC" \
  --vnet-name vnet-app --subnet snet-pe \
  --private-connection-resource-id "$SVC_ID" \
  --connection-name "pec-$SVC" --group-id searchService
az network private-dns zone create -g "$RG" -n privatelink.search.windows.net
az network private-dns link vnet create -g "$RG" -n vnet-app-link \
  -z privatelink.search.windows.net --virtual-network vnet-app --registration-enabled false
az network private-endpoint dns-zone-group create -g "$RG" --endpoint-name "pe-$SVC" \
  -n zg-search --private-dns-zone privatelink.search.windows.net --zone-name searchService
```

> If your AOAI is also private, use **shared private link** from the
> Search service to the AOAI (`groupId: openai_account`) so the indexer
> can reach AOAI over Private Link. ([Source](https://learn.microsoft.com/azure/search/search-indexer-howto-access-private))

## Recipe — Bicep

```bicep
param searchServiceName string
param location string = resourceGroup().location

resource search 'Microsoft.Search/searchServices@2025-05-01' = {
  name: searchServiceName
  location: location
  sku: { name: 'standard' }
  identity: { type: 'SystemAssigned' }
  properties: {
    replicaCount: 2
    partitionCount: 1
    disableLocalAuth: true                  // do NOT set authOptions when this is true
    publicNetworkAccess: 'Disabled'
    semanticSearch: 'standard'              // 'free' | 'standard' | 'disabled'
  }
}

output principalId string = search.identity.principalId
```

## Integrated vectorization (RAG glue)

Use the `AzureOpenAIEmbeddingSkill` in your skillset; configure the
skill's `authIdentity: null` to use the search service's
**system-assigned MI** (which you've already granted
`Cognitive Services OpenAI User` on the AOAI account). Pin the
`apiVersion` and `deploymentId` to a known model (e.g.,
`text-embedding-3-large`).

```jsonc
{
  "@odata.type": "#Microsoft.Skills.Text.AzureOpenAIEmbeddingSkill",
  "resourceUri": "https://oai-app-prod.openai.azure.com",
  "deploymentId": "text-embedding-3-large",
  "apiKey": null,
  "authIdentity": null,            // null = use the search service's system MI
  "modelName": "text-embedding-3-large"
}
```

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| 401 from query / index call | App still using admin/query key but `disableLocalAuth: true` | Use `DefaultAzureCredential` / a search SDK that supports Entra. |
| Indexer fails reading from Storage | Search MI lacks `Storage Blob Data Reader` on the SA, or the SA blocks public access without a shared private link | Grant the role; add a shared private link to the SA if it's private. ([Source](https://learn.microsoft.com/azure/search/search-howto-managed-identities-storage)) |
| Vectorizer / embedding skill fails 401 | Search MI lacks `Cognitive Services OpenAI User` on the AOAI account, or the AOAI account is private and there's no shared private link | Grant the role; add a shared private link with `groupId: openai_account`. |
| Semantic ranker errors `Feature not enabled` | `semanticSearch: 'disabled'`, or running in a region that doesn't support it | Set to `'standard'`; use a [supported region](https://learn.microsoft.com/azure/search/search-region-support). |
| Hit query rate limit | Too few replicas | Increase `replicaCount`. Replicas scale query throughput; partitions scale storage and indexing. |
| Cannot increase capacity beyond 36 SU | Search Units = replicas × partitions; hard cap is 36 | Provision a second service or move to S2/S3. |
| Tried `disableLocalAuth: true` AND set `authOptions` | Mutually exclusive | Drop `authOptions` when `disableLocalAuth: true`. |

## References

- [Create a search service](https://learn.microsoft.com/azure/search/search-create-service-portal)
- [Choose a tier](https://learn.microsoft.com/azure/search/search-sku-tier)
- [Role-based access control](https://learn.microsoft.com/azure/search/search-security-rbac)
- [Enable RBAC / disable keys](https://learn.microsoft.com/azure/search/search-security-enable-roles)
- [Private endpoint](https://learn.microsoft.com/azure/search/service-create-private-endpoint)
- [Semantic ranker overview](https://learn.microsoft.com/azure/search/semantic-search-overview)
- [Integrated vectorization](https://learn.microsoft.com/azure/search/vector-search-integrated-vectorization)
- [Azure OpenAI Embedding skill](https://learn.microsoft.com/azure/search/cognitive-search-skill-azure-openai-embedding)
- [Indexer access to Storage with MI](https://learn.microsoft.com/azure/search/search-howto-managed-identities-storage)
- [Capacity planning](https://learn.microsoft.com/azure/search/search-capacity-planning)
- [Shared private link for outbound](https://learn.microsoft.com/azure/search/search-indexer-howto-access-private)
- [`Microsoft.Search/searchServices` template](https://learn.microsoft.com/azure/templates/microsoft.search/searchservices)
