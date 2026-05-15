---
name: azure-load-balancer
description: >
  Standard Load Balancer authoring with closed-by-default posture: NSG
  required on the backend NIC/subnet, Standard SKU public IP only,
  zone-redundant frontend, TCP probes (HTTP/HTTPS optional), TCP Reset
  on idle, `disableOutboundSnat: true` so a NAT Gateway on the subnet
  is the outbound path. Covers HA Ports for NVAs (internal LB only),
  Floating IP for SQL Always On listeners, and the SNAT exhaustion math.
version: 0.1.0
azure_services:
  - Microsoft.Network/loadBalancers
  - Microsoft.Network/publicIPAddresses
tags:
  - networking
  - load-balancer
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/load-balancer/load-balancer-overview
  - https://learn.microsoft.com/azure/load-balancer/skus
  - https://learn.microsoft.com/azure/load-balancer/components
  - https://learn.microsoft.com/azure/load-balancer/load-balancer-custom-probe-overview
  - https://learn.microsoft.com/azure/load-balancer/load-balancer-ha-ports-overview
  - https://learn.microsoft.com/azure/load-balancer/load-balancer-tcp-reset
  - https://learn.microsoft.com/azure/load-balancer/load-balancer-outbound-connections
  - https://learn.microsoft.com/azure/load-balancer/outbound-rules
  - https://learn.microsoft.com/azure/load-balancer/cross-region-overview
  - https://learn.microsoft.com/azure/load-balancer/load-balancer-troubleshoot-health-probe-status
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2024-05-01"
last_reviewed: 2026-05-15
---

# Azure Load Balancer (Standard SKU)

## When to use this skill

- L4 (TCP/UDP) load balancing inside a VNet — VMs, VMSS, NVAs.
- HA Ports for active/active firewalls / SD-WAN appliances (internal LB).
- The user wants the lowest-overhead, fastest L4 frontend.

## When NOT to use this skill

- L7 / HTTP routing, WAF, path-based rules — use
  [`azure-application-gateway`](../azure-application-gateway/SKILL.md).
- Global, multi-region L7 with WAF — use
  [`azure-front-door`](../azure-front-door/SKILL.md).
- Outbound-only — use [`azure-nat-gateway`](../azure-nat-gateway/SKILL.md)
  on the subnet (preferred for outbound SNAT).

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| SKU | `Standard` | Basic is being retired; no SLA; no zones. |
| Frontend public IP | Standard SKU, Static, **zone-redundant** (`zones: ['1','2','3']`) | Required for Standard LB; zonal redundancy with no extra cost. |
| Backend NSG | NSG on backend NIC/subnet allowing only the required ports | Standard LB is **closed by default** — without an NSG allowing traffic, nothing flows. |
| Allow `AzureLoadBalancer` service tag inbound on probe port | `Allow Inbound` | Probes come from `168.63.129.16`; blocking it makes backends look unhealthy. |
| Outbound SNAT | `disableOutboundSnat: true` on every load-balancing rule + NAT Gateway on the subnet | NAT Gateway takes precedence over LB outbound rules and removes SNAT-port exhaustion class of bugs. |
| `enableTcpReset` on rules | `true` | Sends a TCP RST on idle timeout — predictable for the client vs silent drop. |
| Idle timeout | tune in 4–100 min range | Default 4 min is too aggressive for many DB-backed apps. |
| Backend pool type | NIC-based for new designs | IP-based pool is treated like Basic LB for outbound (default outbound on). |
| HA Ports rule | only on **internal** Standard LB, for NVAs | Not supported on public LB or Basic. |

## Frontends, pools, probes, rules

| Concept | Notes |
| --- | --- |
| Frontend IP | Public (Standard SKU IP) or Internal (private IP in VNet). Multiple frontends supported. |
| Backend pool | NIC-based (most common) or IP-based; scope = VMs in a single VNet. |
| Health probe | TCP, HTTP (Standard+Basic), HTTPS (**Standard only**). Default interval 5 s. Probe source = `168.63.129.16`. |
| Restricted HTTP probe ports | 19, 21, 25, 70, 110, 119, 143, 220, 993 — WinHTTP blocks these. Use TCP probe instead. |
| Load-balancing rule | distributes across the whole pool (5-tuple hash) |
| Inbound NAT rule | port-forwards to a specific instance |
| `inboundNatPools` | auto-generates per-instance NAT rules for VMSS |
| HA Ports | `protocol: 'All'`, `frontendPort: 0`, `backendPort: 0` on internal LB |
| Floating IP / DSR | required for SQL Always On listeners (VM needs loopback config) |

## Outbound: prefer NAT Gateway

Recommended order for outbound from a subnet:

| Priority | Method | Notes |
| --- | --- | --- |
| 1 | **NAT Gateway** on subnet | dynamic SNAT, no exhaustion class of bugs; takes precedence over LB outbound rules |
| 2 | Instance public IP | static 1:1 NAT |
| 3 | LB outbound rules (explicit) | declarative, 64K SNAT ports per frontend IP |
| 4 | LB implicit SNAT (no outbound rules) | not recommended; SNAT-port pinch |
| 5 | "Default outbound access" | **retiring 2026-03-31** for new VNets |

SNAT ports per VM (default LB outbound rule):

| Pool size | Default ports per VM |
| --- | --- |
| 1–50 | 1,024 |
| 51–100 | 512 |
| 101–200 | 256 |
| 201–400 | 128 |
| 401–800 | 64 |
| 801–1,000 | 32 |

## Recipe — Azure CLI (public Standard LB)

```bash
RG=lb-demo-rg
LOC=eastus
LB=my-lb

az group create -n "$RG" -l "$LOC"

az network vnet create -g "$RG" -n my-vnet --address-prefix 10.0.0.0/16 \
  --subnet-name backend --subnet-prefix 10.0.1.0/24

# Standard, Static, zone-redundant public IP
az network public-ip create -g "$RG" -n "${LB}-pip" \
  --sku Standard --allocation-method Static --zone 1 2 3

# Standard LB
az network lb create -g "$RG" -n "$LB" --sku Standard \
  --frontend-ip-name fe --public-ip-address "${LB}-pip" \
  --backend-pool-name be

az network lb probe create -g "$RG" --lb-name "$LB" \
  --name tcp80 --protocol tcp --port 80 --interval 5 --threshold 2

# disable outbound SNAT — NAT Gateway on the subnet handles outbound
az network lb rule create -g "$RG" --lb-name "$LB" --name http \
  --protocol Tcp --frontend-port 80 --backend-port 80 \
  --frontend-ip-name fe --backend-pool-name be --probe-name tcp80 \
  --idle-timeout 15 --enable-tcp-reset true --disable-outbound-snat true

# NSG (Standard LB is closed by default — must explicitly allow probes + traffic)
az network nsg create -g "$RG" -n be-nsg
az network nsg rule create -g "$RG" --nsg-name be-nsg -n allow-probe \
  --priority 100 --source-address-prefixes AzureLoadBalancer \
  --destination-port-ranges 80 --access Allow --protocol Tcp --direction Inbound
az network nsg rule create -g "$RG" --nsg-name be-nsg -n allow-http \
  --priority 110 --source-address-prefixes Internet \
  --destination-port-ranges 80 --access Allow --protocol Tcp --direction Inbound
az network vnet subnet update -g "$RG" --vnet-name my-vnet -n backend \
  --network-security-group be-nsg

# Attach NAT Gateway for outbound (preferred)
az network public-ip create -g "$RG" -n natgw-pip --sku Standard \
  --allocation-method Static --zone 1
az network nat gateway create -g "$RG" -n my-natgw \
  --public-ip-addresses natgw-pip --idle-timeout 10 --zone 1
az network vnet subnet update -g "$RG" --vnet-name my-vnet -n backend \
  --nat-gateway my-natgw
```

## Recipe — Bicep

```bicep
param location string = resourceGroup().location
param lbName string = 'myLoadBalancer'

resource lbPip 'Microsoft.Network/publicIPAddresses@2024-05-01' = {
  name: '${lbName}-pip'
  location: location
  sku: { name: 'Standard', tier: 'Regional' }
  properties: {
    publicIPAllocationMethod: 'Static'
    publicIPAddressVersion: 'IPv4'
  }
  zones: [ '1', '2', '3' ]
}

resource lb 'Microsoft.Network/loadBalancers@2024-05-01' = {
  name: lbName
  location: location
  sku: { name: 'Standard', tier: 'Regional' }
  properties: {
    frontendIPConfigurations: [
      {
        name: 'fe'
        properties: { publicIPAddress: { id: lbPip.id } }
        zones: [ '1', '2', '3' ]
      }
    ]
    backendAddressPools: [ { name: 'be' } ]
    probes: [
      {
        name: 'tcp80'
        properties: {
          protocol: 'Tcp'
          port: 80
          intervalInSeconds: 5
          numberOfProbes: 2
        }
      }
    ]
    loadBalancingRules: [
      {
        name: 'http'
        properties: {
          frontendIPConfiguration: { id: resourceId(
            'Microsoft.Network/loadBalancers/frontendIPConfigurations', lbName, 'fe') }
          backendAddressPool: { id: resourceId(
            'Microsoft.Network/loadBalancers/backendAddressPools', lbName, 'be') }
          probe: { id: resourceId(
            'Microsoft.Network/loadBalancers/probes', lbName, 'tcp80') }
          protocol: 'Tcp'
          frontendPort: 80
          backendPort: 80
          idleTimeoutInMinutes: 15
          enableTcpReset: true
          disableOutboundSnat: true       // NAT Gateway handles outbound
          enableFloatingIP: false         // true for SQL Always On listener
          loadDistribution: 'Default'
        }
      }
    ]
  }
}

output frontendIp string = lbPip.properties.ipAddress
```

> **HA Ports variant** (internal LB for NVA): set `protocol: 'All'`,
> `frontendPort: 0`, `backendPort: 0`, and use a `subnet` (not a
> `publicIPAddress`) on the frontend.

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| Traffic silently dropped | Standard LB is closed by default — no NSG on backend | Add NSG with explicit allow rules |
| Deployment fails: SKU mismatch | Basic public IP used with Standard LB (or vice versa) | Use Standard SKU for both |
| Backends marked unhealthy | NSG blocks probe source `168.63.129.16` | Allow `AzureLoadBalancer` service tag inbound on the probe port |
| Intermittent outbound connection failures | SNAT port exhaustion | Attach NAT Gateway to the subnet (preferred) or add frontend IPs to outbound rule |
| HA Ports rule rejected on public LB | HA Ports = internal Standard LB only | Use an internal LB for NVA HA |
| HTTP probe fails on ports 19/21/25/110/143/220/993 | WinHTTP blocks those ports | Switch to TCP probe |
| Internal LB backends have no internet | Internal LB has no outbound by default | Attach NAT Gateway to the subnet |
| HA Ports rule + non-HA rule on same frontend | Not supported unless both have Floating IP enabled | Separate frontends, or enable Floating IP |
| New-VNet VMs have no outbound after 2026-03-31 | Default outbound access retired | Define explicit outbound: NAT Gateway recommended |
| IP-based backend pool acts like Basic LB for outbound | IP-based pool defaults to outbound enabled | Use NIC-based pool for secure-by-default behavior |

## API versions

| Resource | Recommended | Latest |
| --- | --- | --- |
| `Microsoft.Network/loadBalancers` | `2024-05-01` | `2025-05-01` |
| `Microsoft.Network/publicIPAddresses` | `2024-05-01` | `2025-05-01` |

## References

- [Load Balancer overview](https://learn.microsoft.com/azure/load-balancer/load-balancer-overview)
- [Standard vs Basic SKUs](https://learn.microsoft.com/azure/load-balancer/skus)
- [Components](https://learn.microsoft.com/azure/load-balancer/components)
- [Health probes](https://learn.microsoft.com/azure/load-balancer/load-balancer-custom-probe-overview)
- [HA Ports](https://learn.microsoft.com/azure/load-balancer/load-balancer-ha-ports-overview)
- [TCP Reset on Idle](https://learn.microsoft.com/azure/load-balancer/load-balancer-tcp-reset)
- [Outbound connections](https://learn.microsoft.com/azure/load-balancer/load-balancer-outbound-connections)
- [Outbound rules](https://learn.microsoft.com/azure/load-balancer/outbound-rules)
- [Cross-region (global) LB](https://learn.microsoft.com/azure/load-balancer/cross-region-overview)
- [Health probe troubleshooting](https://learn.microsoft.com/azure/load-balancer/load-balancer-troubleshoot-health-probe-status)
