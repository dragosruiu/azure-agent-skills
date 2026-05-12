---
name: azure-nat-gateway
description: >
  Provision Azure NAT Gateway for predictable, scalable outbound SNAT
  from VNet subnets without exposing per-resource public IPs. Standard
  SKU is zonal (pin a zone — immutable), StandardV2 is zone-redundant
  by default. Each public IP gives 64,512 SNAT ports.
version: 0.1.0
azure_services:
  - Microsoft.Network/natGateways
  - Microsoft.Network/publicIPAddresses
  - Microsoft.Network/publicIPPrefixes
tags:
  - networking
  - egress
  - snat
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/nat-gateway/nat-overview
  - https://learn.microsoft.com/azure/nat-gateway/nat-sku
  - https://learn.microsoft.com/azure/nat-gateway/quickstart-create-nat-gateway-portal
  - https://learn.microsoft.com/azure/reliability/reliability-nat-gateway
  - https://learn.microsoft.com/azure/firewall/integrate-with-nat-gateway
  - https://learn.microsoft.com/azure/templates/microsoft.network/natgateways
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2025-05-01"
last_reviewed: 2026-05-12
---

# Azure NAT Gateway

## When to use this skill

- The user wants outbound-only SNAT for many VMs / Container Apps env /
  AKS pods without exposing each one with a public IP.
- The user is hitting SNAT port exhaustion behind a Standard Load
  Balancer (NAT GW gives 64,512 ports per public IP — vastly more).
- The user wants a fixed, predictable set of egress IPs for an
  upstream allow-list.

## When NOT to use this skill

- The user needs L7 inspection / TLS inspection / IDPS on egress —
  use [`azure-firewall`](../azure-firewall/SKILL.md) (Premium SKU).
- The user only needs inbound load balancing — that's Standard Load
  Balancer / Front Door / App Gateway, not NAT GW.

## SKU picker

| Feature | Standard | StandardV2 |
| --- | --- | --- |
| Zone model | **Zonal** (pin a single zone) or nonzonal | **Zone-redundant by default** |
| IPv6 | ❌ | ✅ |
| Bandwidth ceiling | 50 Gbps | 100 Gbps |
| Packets/sec | 5 M | 10 M |
| Public IP SKU required | Standard | **StandardV2 only** |
| Flow logs | ❌ | ✅ |
| Upgrade Standard → StandardV2 | not supported — redeploy | n/a |

> **Pick StandardV2** unless you have a specific reason to pin a single
> zone. **Zone selection on Standard SKU is immutable after deployment.**

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| `sku.name` | `'StandardV2'` for prod (zone-redundant); `'Standard'` only when zone-pinning is wanted | NAT GW has no Basic SKU. |
| Standard zonal: `zones` | `['1']` (or 2 / 3) | Immutable after deploy. |
| StandardV2: `zones` | omit | Auto zone-redundant. |
| Public IP SKU | `Standard` (with Standard NAT GW); `StandardV2` (with StandardV2 NAT GW); both `--allocation-method Static` | Required pairing. |
| Public IP zone | match the NAT GW zone (Standard SKU) | Otherwise fails. |
| `idleTimeoutInMinutes` | `4` (default; range 4–120) | Higher values hold SNAT ports longer = exhaustion risk. Don't raise without measured need. |
| Public IP **prefix** instead of single IP | `/30` (4 IPs = ~258 K SNAT ports) — for predictable, allowlist-friendly egress | Each IP adds 64,512 SNAT ports. |
| Subnet association | one or more subnets per NAT GW (per-subnet, not per-VNet) | NAT GW is a subnet attribute. |
| **Don't combine** with Standard Load Balancer outbound rules on the same subnet | conflict | NAT GW takes precedence and the LB outbound rules become moot — but configurations get confusing. |
| **Don't add a UDR** `0.0.0.0/0 → NVA` on the NAT-GW-attached subnet | traffic bypasses NAT GW | A UDR overrides the NAT GW egress path. |

## Recipe — Azure CLI

```bash
RG=rg-egress-prod
LOC=eastus2
NATGW=natgw-prod
PIP=pip-natgw

az group create -n "$RG" -l "$LOC"

# 1. VNet + workload subnet (no public IP on the subnet)
az network vnet create -g "$RG" -n vnet-prod \
  --address-prefix 10.1.0.0/16 \
  --subnet-name snet-workload --subnet-prefix 10.1.1.0/24

# 2. Standard, Static public IP — pin to the same zone as the NAT GW
az network public-ip create -g "$RG" -n "$PIP" --sku Standard \
  --allocation-method Static --zone 1

# (Alternative: a /30 public IP prefix for predictable contiguous IPs)
# az network public-ip prefix create -g "$RG" -n ippfx-natgw --length 30 --zone 1

# 3. NAT Gateway (Standard SKU, pinned to zone 1)
az network nat gateway create -g "$RG" -n "$NATGW" -l "$LOC" \
  --sku standard \
  --public-ip-addresses "$PIP" \
  --idle-timeout 4 --zone 1

# 4. Associate with the workload subnet
az network vnet subnet update -g "$RG" --vnet-name vnet-prod -n snet-workload \
  --nat-gateway "$NATGW"

# 5. Verify outbound — from a VM on the subnet:
#    curl ifconfig.me   # should return the NAT GW public IP
```

## Recipe — Bicep (StandardV2, zone-redundant)

```bicep
param location string = resourceGroup().location
param natGatewayName string = 'natgw-prod'

resource pip 'Microsoft.Network/publicIPAddresses@2024-05-01' = {
  name: 'pip-${natGatewayName}'
  location: location
  sku: { name: 'Standard' }                    // 'StandardV2' if NAT GW is StandardV2
  zones: [ '1', '2', '3' ]                     // zone-redundant public IP
  properties: { publicIPAllocationMethod: 'Static' }
}

resource natGw 'Microsoft.Network/natGateways@2025-05-01' = {
  name: natGatewayName
  location: location
  // StandardV2: omit zones[]; zone-redundant by default
  // Standard zonal: zones: ['1']  ← immutable after deploy
  sku: { name: 'StandardV2' }
  properties: {
    idleTimeoutInMinutes: 4
    publicIpAddresses: [ { id: pip.id } ]
    // publicIpPrefixes: [ { id: prefix.id } ]   // for contiguous SNAT IP block
  }
}

// Associate by setting natGateway on the subnet
resource snet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' = {
  name: 'vnet-prod/snet-workload'
  properties: {
    addressPrefix: '10.1.1.0/24'
    natGateway: { id: natGw.id }
  }
}
```

## SNAT port math

| Source | Ports / public IP |
| --- | --- |
| **NAT Gateway** | **64,512 per IP** (max ~16 IPs = ~1 M ports) |
| Standard Load Balancer outbound | 1,024 (default) – 64,512 per IP per VM (allocated) |
| Default outbound (no NAT/LB; deprecated for new VNets) | 1,024 per VM |

Need more egress capacity? Add more public IPs (or use a public IP
prefix) — each adds 64,512 ports.

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| SNAT port exhaustion despite NAT GW | Same subnet also has a Standard LB with outbound rules **or** instance-level public IPs | Remove conflicting outbound paths; NAT GW takes precedence but configurations drift. |
| NAT GW egress doesn't apply | A UDR with `0.0.0.0/0 → VirtualAppliance` is on the subnet | Remove the UDR or accept that NAT GW is bypassed. |
| Workload in zone 2 fails over but NAT GW is in zone 1 | Standard SKU NAT GW is **zonal** — failure of zone 1 takes the NAT GW with it | Use StandardV2 (zone-redundant), or deploy one NAT GW per zone with subnets-per-zone. |
| Public IP attach fails | NAT GW + public-IP SKU mismatch (Standard NAT GW with StandardV2 IP, or vice-versa) | Match the SKU. |
| Egress IP changed unexpectedly | Single public IP rotated or got a new IP after deallocation | Use a static public IP **or** a `/30`/`/29` public IP prefix for stability. |
| Tried to upgrade Standard → StandardV2 | Not supported in place | Deploy a new StandardV2 NAT GW + new public IPs; switch subnet association; delete the old. |

## References

- [NAT Gateway overview](https://learn.microsoft.com/azure/nat-gateway/nat-overview)
- [NAT Gateway SKU comparison](https://learn.microsoft.com/azure/nat-gateway/nat-sku)
- [Quickstart (portal)](https://learn.microsoft.com/azure/nat-gateway/quickstart-create-nat-gateway-portal)
- [Reliability for NAT Gateway](https://learn.microsoft.com/azure/reliability/reliability-nat-gateway)
- [Integrate Firewall + NAT GW](https://learn.microsoft.com/azure/firewall/integrate-with-nat-gateway)
- [`Microsoft.Network/natGateways` template](https://learn.microsoft.com/azure/templates/microsoft.network/natgateways)
