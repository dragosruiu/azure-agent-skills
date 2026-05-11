---
name: azure-private-endpoint
description: >
  Wire a private endpoint to an Azure PaaS resource so traffic stays
  inside your VNet. Covers the universal pattern (subnet + PE + private
  DNS zone + DNS zone group), the per-service sub-resource / DNS-zone
  table, and the most common DNS-resolution failure modes.
version: 0.1.0
azure_services:
  - Microsoft.Network/privateEndpoints
  - Microsoft.Network/privateDnsZones
  - Microsoft.Network/privateDnsZones/virtualNetworkLinks
  - Microsoft.Network/privateEndpoints/privateDnsZoneGroups
tags:
  - networking
  - private-link
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/private-link/private-endpoint-overview
  - https://learn.microsoft.com/azure/private-link/private-endpoint-dns
  - https://learn.microsoft.com/cli/azure/network/private-endpoint
  - https://learn.microsoft.com/azure/private-link/create-private-endpoint-bicep
  - https://learn.microsoft.com/azure/private-link/create-private-endpoint-cli
  - https://learn.microsoft.com/azure/templates/microsoft.network/privateendpoints
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2024-05-01"
last_reviewed: 2026-05-11
---

# Azure Private Endpoint (universal pattern)

## When to use this skill

- The user wants to consume an Azure PaaS resource (storage, Key Vault,
  Cosmos DB, OpenAI, ACR, App Service) from a VNet without traversing the
  public internet.
- The user disabled `publicNetworkAccess` on a service and now nothing
  can reach it.
- Needed any time the data service should be reachable only from a
  bounded set of VNets — production posture.

## When NOT to use this skill

- The consumer also lives outside Azure with no VPN/ExpressRoute — PEs
  are reachable only from VNets and on-prem networks connected to those
  VNets.
- The service doesn't yet support Private Link — check the [supported
  resources table](https://learn.microsoft.com/azure/private-link/availability).

## Prerequisites

- A VNet + subnet for the private endpoint. Subnet must have
  `privateEndpointNetworkPolicies: 'Disabled'`.
- The target resource (it must be a Private-Link-capable type and SKU —
  e.g., Storage requires StorageV2 / GPv2).
- For Storage: one PE *per sub-resource* you want to use (blob, file,
  queue, table separately).

## Sub-resource & DNS zone table

Source: [private-endpoint-overview](https://learn.microsoft.com/azure/private-link/private-endpoint-overview), [private-endpoint-dns](https://learn.microsoft.com/azure/private-link/private-endpoint-dns).

| Service | Resource type | `groupId` (sub-resource) | Required private DNS zone |
| --- | --- | --- | --- |
| Storage Blob | `Microsoft.Storage/storageAccounts` | `blob` | `privatelink.blob.core.windows.net` |
| Storage File | `Microsoft.Storage/storageAccounts` | `file` | `privatelink.file.core.windows.net` |
| Storage Table | `Microsoft.Storage/storageAccounts` | `table` | `privatelink.table.core.windows.net` |
| Storage Queue | `Microsoft.Storage/storageAccounts` | `queue` | `privatelink.queue.core.windows.net` |
| Key Vault | `Microsoft.KeyVault/vaults` | `vault` | `privatelink.vaultcore.azure.net` |
| Cosmos DB (NoSQL) | `Microsoft.DocumentDB/databaseAccounts` | `Sql` | `privatelink.documents.azure.com` |
| Cosmos DB (Mongo) | `Microsoft.DocumentDB/databaseAccounts` | `MongoDB` | `privatelink.mongo.cosmos.azure.com` |
| Cosmos DB (Cassandra) | `Microsoft.DocumentDB/databaseAccounts` | `Cassandra` | `privatelink.cassandra.cosmos.azure.com` |
| Cosmos DB (Gremlin) | `Microsoft.DocumentDB/databaseAccounts` | `Gremlin` | `privatelink.gremlin.cosmos.azure.com` |
| Azure SQL DB | `Microsoft.Sql/servers` | `sqlServer` | `privatelink.database.windows.net` |
| PostgreSQL Flexible | `Microsoft.DBforPostgreSQL/flexibleServers` | `postgresqlServer` | `privatelink.postgres.database.azure.com` |
| Cognitive Services / Azure OpenAI | `Microsoft.CognitiveServices/accounts` | `account` | `privatelink.cognitiveservices.azure.com` *and* `privatelink.openai.azure.com` *and* `privatelink.services.ai.azure.com` |
| Container Registry | `Microsoft.ContainerRegistry/registries` | `registry` | `privatelink.azurecr.io` (+ `{region}.data.privatelink.azurecr.io`) |
| App Service / Functions | `Microsoft.Web/sites` | `sites` | `privatelink.azurewebsites.net` (+ `scm.privatelink.azurewebsites.net`) |

> **OpenAI / Cognitive Services:** the `groupId` is `account`, not `openai`.
> Multiple DNS zones must all be linked to the consumer VNet.

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| Subnet `privateEndpointNetworkPolicies` | `'Disabled'` | Required to deploy a PE into the subnet. |
| `--connection-name` (or `privateLinkServiceConnections[].name` in Bicep) | descriptive | Required and uniquely names the connection. |
| `--manual-request` | omit (default `false`) | Auto-approve when you own the target. |
| Private DNS zone `--registration-enabled` (`registrationEnabled` in Bicep) | `false` | The zone is for `privatelink.*` records — not for VM hostname auto-registration. |
| Private DNS zone group on the PE | **always create one** | Lets Azure auto-manage the A record on the PE NIC; manual records drift. |
| `privatelink.*` zone link | linked to **the consumer VNet**, not the PE VNet (when they differ) | DNS resolution happens from the consumer's perspective. |

## Recipe — Azure CLI (Storage Blob target)

```bash
RG=rg-priv-prod
LOC=eastus
VNET=vnet-app
SUBNET=snet-app-pe
SA=stappprod$RANDOM
PE=pe-storage-blob
DNS_ZONE=privatelink.blob.core.windows.net

az group create -n "$RG" -l "$LOC"

# 1. VNet + PE subnet (PE network policies disabled)
az network vnet create -g "$RG" -l "$LOC" -n "$VNET" \
  --address-prefixes 10.0.0.0/16 \
  --subnet-name "$SUBNET" --subnet-prefixes 10.0.0.0/24
az network vnet subnet update -g "$RG" --vnet-name "$VNET" -n "$SUBNET" \
  --disable-private-endpoint-network-policies true

# 2. Storage account (GPv2, public access disabled)
az storage account create -g "$RG" -n "$SA" -l "$LOC" \
  --sku Standard_LRS --kind StorageV2 \
  --public-network-access Disabled
SA_ID=$(az storage account show -g "$RG" -n "$SA" --query id -o tsv)

# 3. Private endpoint (groupId = blob)
az network private-endpoint create \
  -g "$RG" -l "$LOC" -n "$PE" \
  --vnet-name "$VNET" --subnet "$SUBNET" \
  --private-connection-resource-id "$SA_ID" \
  --connection-name "${PE}-conn" \
  --group-id blob

# 4. Private DNS zone + link to the CONSUMER VNet
az network private-dns zone create -g "$RG" -n "$DNS_ZONE"
az network private-dns link vnet create -g "$RG" -z "$DNS_ZONE" -n "${VNET}-link" \
  --virtual-network "$VNET" --registration-enabled false

# 5. DNS zone group on the PE — auto-manages A records
az network private-endpoint dns-zone-group create \
  -g "$RG" --endpoint-name "$PE" \
  -n zg-blob \
  --private-dns-zone "$DNS_ZONE" \
  --zone-name blob

# Verify the FQDN now resolves to a 10.0.0.x address from inside the VNet
az network private-endpoint show -g "$RG" -n "$PE" \
  --query "customDnsConfigs[].{FQDN:fqdn,IP:ipAddresses}" -o table
```

## Recipe — Bicep (Storage Blob target)

```bicep
param location string = resourceGroup().location
param storageAccountName string
param vnetName string
param subnetName string
param privateEndpointName string = 'pe-${storageAccountName}-blob'

resource sa 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: vnetName
}

resource subnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' = {
  parent: vnet
  name: subnetName
  properties: {
    addressPrefix: '10.0.0.0/24'
    privateEndpointNetworkPolicies: 'Disabled'   // REQUIRED
  }
}

resource pe 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: privateEndpointName
  location: location
  properties: {
    subnet: { id: subnet.id }
    privateLinkServiceConnections: [
      {
        name: privateEndpointName
        properties: {
          privateLinkServiceId: sa.id
          groupIds: [ 'blob' ]
        }
      }
    ]
  }
}

var dnsZoneName = 'privatelink.blob.core.windows.net'

resource dnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: dnsZoneName
  location: 'global'   // private DNS zones are always 'global'
}

resource dnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: dnsZone
  name: '${vnetName}-link'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: vnet.id }
  }
}

resource zoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: pe
  name: 'zg-blob'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'blob-config'
        properties: { privateDnsZoneId: dnsZone.id }
      }
    ]
  }
}
```

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| `nslookup mystorage.blob.core.windows.net` from inside the VNet returns the **public** IP | Private DNS zone exists but is **not linked** to the consumer VNet | Add a `virtualNetworkLinks` to the consumer VNet with `registrationEnabled: false`. |
| DNS resolves to private IP but TCP connection fails | PE connection status is `Pending` | Approve the connection on the target resource (or use `--manual-request false`). |
| A records in the zone are wrong / stale | Manual A record was added instead of using a DNS Zone Group | Delete the manual record; create the DNS Zone Group on the PE — Azure auto-manages the lifecycle. ([Source](https://learn.microsoft.com/azure/private-link/private-endpoint-dns)) |
| Bicep deploy: "subnet has private endpoint network policies enabled" | `privateEndpointNetworkPolicies` not set to `'Disabled'` on the subnet | Set it. |
| Added a blob PE; queue still resolves publicly | Each storage sub-resource needs its own PE + zone | Create another PE with `--group-id queue` and a `privatelink.queue.core.windows.net` zone. |
| PE deploy blocked: "storage account is not GPv2" | Classic / BlobStorage kinds are unsupported | `--kind StorageV2`. |
| Hub-and-spoke: spokes can't resolve | Zone is linked only to the hub VNet | Add zone links for each spoke VNet (or use a custom DNS forwarder pattern). |
| Container Registry: docker push works but image layer pulls fail | Missing the `{region}.data.privatelink.azurecr.io` data-plane zone | Link the data zone too (single PE; ACR uses two zones). |

## References

- [Private endpoint overview](https://learn.microsoft.com/azure/private-link/private-endpoint-overview)
- [Private endpoint DNS configuration (zone table)](https://learn.microsoft.com/azure/private-link/private-endpoint-dns)
- [`az network private-endpoint`](https://learn.microsoft.com/cli/azure/network/private-endpoint)
- [Bicep quickstart](https://learn.microsoft.com/azure/private-link/create-private-endpoint-bicep)
- [CLI quickstart](https://learn.microsoft.com/azure/private-link/create-private-endpoint-cli)
- [`Microsoft.Network/privateEndpoints` template reference](https://learn.microsoft.com/azure/templates/microsoft.network/privateendpoints)
