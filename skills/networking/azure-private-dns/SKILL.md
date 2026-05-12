---
name: azure-private-dns
description: >
  Manage Azure Private DNS — `Microsoft.Network/privateDnsZones` always
  in `location: 'global'`, VNet links with `registrationEnabled: false`
  for `privatelink.*` zones (always), and the gotcha that consumer
  VNets must be linked to the zone (not just the PE VNet) for resolution
  to work.
version: 0.1.0
azure_services:
  - Microsoft.Network/privateDnsZones
  - Microsoft.Network/privateDnsZones/virtualNetworkLinks
  - Microsoft.Network/privateDnsZones/A
  - Microsoft.Network/dnsResolvers
tags:
  - networking
  - dns
  - private-link
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/dns/private-dns-overview
  - https://learn.microsoft.com/azure/dns/private-dns-virtual-network-links
  - https://learn.microsoft.com/azure/dns/private-dns-autoregistration
  - https://learn.microsoft.com/azure/private-link/private-endpoint-dns
  - https://learn.microsoft.com/azure/dns/private-dns-getstarted-cli
  - https://learn.microsoft.com/azure/dns/dns-private-resolver-overview
  - https://learn.microsoft.com/azure/templates/microsoft.network/privatednszones
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2024-06-01"
last_reviewed: 2026-05-12
---

# Azure Private DNS

## When to use this skill

- The user added a private endpoint and the FQDN still resolves to a
  public IP from inside the VNet.
- The user runs a hub-and-spoke topology and needs each spoke to resolve
  PEs in the hub.
- The user wants an internal `internal.contoso.com` zone where VMs
  auto-register their A records.

## When NOT to use this skill

- The user needs **on-prem ↔ Azure** bidirectional DNS resolution or
  conditional forwarding from on-prem — that's **Azure DNS Private
  Resolver**, not just Private DNS zones.
- Public DNS — that's `Microsoft.Network/dnszones` (no `private`).

## Always-true rules

1. `location: 'global'` — hardcode it. Any other value is invalid.
2. For **`privatelink.*` zones backing Private Endpoints**:
   `registrationEnabled: false` on every VNet link. Always.
3. Consumer VNets need their **own** link to the zone — linking only the
   PE-host VNet does not propagate resolution to consumers.
4. The PE auto-creates the A record in the zone if you used the
   recommended `privatelink.*` zone name when wiring the PE's DNS zone
   group. Never compete with that A record by adding manual records to
   the same zone for the same hostname.

## Most-used `privatelink.*` zone names

Verified from [private-endpoint-dns](https://learn.microsoft.com/azure/private-link/private-endpoint-dns) (Commercial cloud). For the full table see
[`azure-private-endpoint`](../azure-private-endpoint/SKILL.md). Below
are the entries that have moved most or that catch people out.

| Service | Zone(s) |
| --- | --- |
| **Azure OpenAI / AI Foundry** (`Microsoft.CognitiveServices/accounts`, sub-resource `account`) | **THREE zones**: `privatelink.cognitiveservices.azure.com`, `privatelink.openai.azure.com`, `privatelink.services.ai.azure.com`. **Missing the third one breaks the new Foundry endpoint.** |
| Azure AI Search | `privatelink.search.windows.net` |
| App Configuration | `privatelink.azconfig.io` |
| Azure Cache for Redis | `privatelink.redis.cache.windows.net` |
| **Azure Managed Redis** (Enterprise+) | `privatelink.redis.azure.net` (distinct from the classic Redis zone) |
| PostgreSQL Flexible *and* Single Server | `privatelink.postgres.database.azure.com` (same zone for both) |
| Key Vault | `privatelink.vaultcore.azure.net` |
| Storage (blob / file / etc.) | `privatelink.blob.core.windows.net` (one zone per sub-resource) |
| Container Registry | `privatelink.azurecr.io` (the regional `{region}.data.privatelink.azurecr.io` records auto-populate inside this zone — do **not** create a separate zone for them) |
| Azure Monitor / LAW (via AMPLS) | **FIVE zones** — see [`azure-log-analytics-workspace`](../../observability/azure-log-analytics-workspace/SKILL.md) |
| Service Bus + Event Hubs | both use `privatelink.servicebus.windows.net` (same zone) |

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| Zone `location` | `'global'` (hardcode) | Required. |
| VNet link `registrationEnabled` | `false` for `privatelink.*` zones; `true` only for custom internal zones where VMs should auto-register | Auto-registration on a privatelink zone makes a mess. |
| Link both PE-host VNet and every consumer VNet | always | Consumer-side DNS resolution is what makes private endpoints work. |
| Hub-and-spoke | link **the zone** to **each spoke**, not just the hub | A peered VNet can't resolve via the peer's zone link. |
| Number of links per zone | up to 1,000 resolution-only; up to 100 registration-enabled links per zone, **1 registration-enabled zone per VNet** | Plan for fan-out. |
| Auto-A records | rely on the PE's `privateDnsZoneGroups` to manage them | Manual A records drift when PE IPs change. |

## Recipe — Azure CLI (typical Storage PE pattern)

```bash
RG=rg-private-dns
PE_VNET=vnet-pe
CONSUMER_VNET=vnet-app
ZONE=privatelink.blob.core.windows.net

# 1. Create the zone (no --location flag; CLI defaults to global for private DNS)
az network private-dns zone create -g "$RG" -n "$ZONE"

# 2. Link the VNet that contains the PE (resolution only)
az network private-dns link vnet create -g "$RG" -z "$ZONE" -n link-pe \
  --virtual-network "$PE_VNET" --registration-enabled false

# 3. Link every consumer VNet (they need their OWN link)
az network private-dns link vnet create -g "$RG" -z "$ZONE" -n link-consumer \
  --virtual-network "$CONSUMER_VNET" --registration-enabled false

# 4. Verify A records (auto-created by PE provisioning when using the recommended zone name)
az network private-dns record-set a list -g "$RG" -z "$ZONE" -o table

# Verify from a VM on the consumer VNet:
#   nslookup mystorage.blob.core.windows.net
#   → CNAME → mystorage.privatelink.blob.core.windows.net → 10.x.x.x
```

## Recipe — Bicep

```bicep
param vnetPeId string         // VNet containing the private endpoint
param vnetConsumerId string   // Consumer VNet
param zoneName string = 'privatelink.blob.core.windows.net'

resource zone 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: zoneName
  location: 'global'                       // ALWAYS 'global'
}

resource linkPe 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: zone
  name: 'link-pe'
  location: 'global'
  properties: {
    virtualNetwork: { id: vnetPeId }
    registrationEnabled: false             // false for ALL privatelink.* zones
  }
}

resource linkConsumer 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: zone
  name: 'link-consumer'
  location: 'global'
  properties: {
    virtualNetwork: { id: vnetConsumerId }
    registrationEnabled: false
  }
}

// Manual A record (only when PE auto-record isn't being used; cross-sub PE etc.)
resource manualA 'Microsoft.Network/privateDnsZones/A@2024-06-01' = {
  parent: zone
  name: 'mystorageaccount'                 // hostname only, no trailing dot
  properties: {
    ttl: 10
    aRecords: [ { ipv4Address: '10.1.2.4' } ]
  }
}
```

## `registrationEnabled` truth table

| Zone | `registrationEnabled` | Effect | Limit |
| --- | --- | --- | --- |
| `privatelink.*` | **`false`** (always) | PE auto-A records resolve correctly | 1,000 links / zone |
| Custom internal (e.g., `internal.contoso.com`) | `true` | VMs in the linked VNet auto-register A records | 100 reg-enabled links / zone; **1 reg-enabled zone / VNet** |
| Custom internal | `false` | Resolution-only; manage records manually | 1,000 links / zone |

## Private DNS zones vs Azure DNS Private Resolver

| Need | Pick |
| --- | --- |
| Resolve `privatelink.*` (and other private) names from inside a VNet | **Private DNS zones** |
| **Conditional forwarding** from on-prem DNS into Azure private zones (and vice versa) | **Azure DNS Private Resolver** (in addition to the zones) |
| One central DNS query path for hub-and-spoke + ExpressRoute | Resolver inbound endpoint (with conditional-forwarding rulesets on outbound) |

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| FQDN resolves to public IP from a VM in the consumer VNet | Zone linked only to the PE-host VNet, not the consumer VNet | Add a VNet link from the consumer VNet to the zone. |
| Private DNS resolution doesn't traverse VNet peering | Peering doesn't propagate DNS zones — each VNet needs its own link | Link the zone to every VNet that needs resolution. |
| A record points to wrong IP after PE recreate | Old auto-A record stale because the PE's `privateDnsZoneGroups` wasn't updated when the PE was recreated | Use `privateDnsZoneGroups` on the PE — it manages records lifecycle automatically. Don't manage them manually. |
| Tried to set `location` to a region | Private DNS zones are global only | Hardcode `location: 'global'`. |
| A peered hub VNet has the zone link but spoke VMs still fail | Peering ≠ DNS link inheritance | Add a separate link to the spoke VNet too (or use a Resolver in the hub with forwarding rulesets). |
| Two `privatelink.azurecr.io` zones (one per region) for ACR | Only one zone is needed; regional `{region}.data.*` records auto-populate in the same zone | Delete the duplicate. |

## References

- [Private DNS overview](https://learn.microsoft.com/azure/dns/private-dns-overview)
- [Virtual network links](https://learn.microsoft.com/azure/dns/private-dns-virtual-network-links)
- [Auto-registration](https://learn.microsoft.com/azure/dns/private-dns-autoregistration)
- [Private endpoint DNS configuration](https://learn.microsoft.com/azure/private-link/private-endpoint-dns)
- [CLI quickstart](https://learn.microsoft.com/azure/dns/private-dns-getstarted-cli)
- [Azure DNS Private Resolver overview](https://learn.microsoft.com/azure/dns/dns-private-resolver-overview)
- [`Microsoft.Network/privateDnsZones` template](https://learn.microsoft.com/azure/templates/microsoft.network/privatednszones)
