---
name: azure-vnet-baseline
description: >
  Hub-and-spoke VNet baseline with sensible subnet sizing, the four
  required subnet delegation strings (App Service, Container Apps,
  PostgreSQL Flexible, Azure Firewall), default-deny NSGs that don't
  block the AzureLoadBalancer health probe, and a UDR for forced
  tunneling through a hub firewall.
version: 0.1.0
azure_services:
  - Microsoft.Network/virtualNetworks
  - Microsoft.Network/virtualNetworks/subnets
  - Microsoft.Network/networkSecurityGroups
  - Microsoft.Network/routeTables
tags:
  - networking
  - vnet
  - hub-spoke
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/virtual-network/virtual-networks-overview
  - https://learn.microsoft.com/azure/architecture/reference-architectures/hybrid-networking/hub-spoke
  - https://learn.microsoft.com/azure/virtual-network/network-security-groups-overview
  - https://learn.microsoft.com/azure/virtual-network/subnet-delegation-overview
  - https://learn.microsoft.com/azure/virtual-network/virtual-network-service-endpoints-overview
  - https://learn.microsoft.com/azure/virtual-network/virtual-networks-udr-overview
  - https://learn.microsoft.com/azure/virtual-network/virtual-network-manage-subnet
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2023-09-01"
last_reviewed: 2026-05-11
---

# Azure VNet baseline (hub-and-spoke)

## When to use this skill

- The user is bootstrapping a new VNet for a workload that will use
  private endpoints, App Service VNet integration, Container Apps,
  PostgreSQL Flexible, or any other service requiring a delegated subnet.
- The user is planning subnet sizes and asks "how big should this be?".
- The user wants forced tunneling through a hub firewall.

## When NOT to use this skill

- The workload doesn't need network isolation — public-only PaaS with
  network ACLs may be enough.
- AKS-specific networking (Azure CNI Overlay etc.) — see
  [`azure-aks-cluster`](../../compute/azure-aks-cluster/SKILL.md).

## Prerequisites

- A subscription with sufficient address space planning (subnets cannot
  be resized while resources occupy them).

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| Topology | **Hub-and-spoke** | Centralizes shared services (firewall, DNS, gateway) and minimizes peering count. ([Source](https://learn.microsoft.com/azure/architecture/reference-architectures/hybrid-networking/hub-spoke)) |
| **Service endpoints vs Private Link** | **Private endpoints** | Microsoft explicitly recommends Private Link for new builds. Service endpoints are a legacy pattern. ([Source](https://learn.microsoft.com/azure/virtual-network/virtual-network-service-endpoints-overview)) |
| NSG default rules | Built-in `AllowAzureLoadBalancerInBound` (priority 65001) — **do not override** with a deny at lower number | Azure Load Balancer health probes use the `AzureLoadBalancer` service tag. Blocking it silently kills traffic. ([Source](https://learn.microsoft.com/azure/virtual-network/network-security-groups-overview)) |
| `disableBgpRoutePropagation` | `false` (default) | Allows the hub gateway to propagate on-prem routes into the spoke. |
| Subnet headroom | 2× the largest expected fleet | Subnets cannot be resized once resources are deployed. |
| `AzureFirewallSubnet` | name is reserved; minimum **`/26`** | Hard-coded by the platform. ([Source](https://learn.microsoft.com/azure/firewall/firewall-faq)) |
| `GatewaySubnet` | name is reserved (VPN/ExpressRoute gateway) | Don't put App Gateway here. |

## Subnet delegation strings (verified)

| Workload | `serviceName` (delegation) | Min subnet | Source |
| --- | --- | --- | --- |
| App Service VNet integration | `Microsoft.Web/serverFarms` | `/26` recommended (`/27` portal min) | [App Service VNet integration](https://learn.microsoft.com/azure/app-service/overview-vnet-integration#subnet-requirements) |
| Container Apps (workload-profiles env) | `Microsoft.App/environments` | `/27` | [Container Apps networking](https://learn.microsoft.com/azure/container-apps/networking) |
| PostgreSQL Flexible Server | `Microsoft.DBforPostgreSQL/flexibleServers` | `/28` | [PostgreSQL networking](https://learn.microsoft.com/azure/postgresql/flexible-server/concepts-networking-private) |
| Azure Firewall | (no delegation; subnet name `AzureFirewallSubnet`) | `/26` | [Firewall FAQ](https://learn.microsoft.com/azure/firewall/firewall-faq) |
| VPN/ExpressRoute gateway | (no delegation; subnet name `GatewaySubnet`) | `/27` typical | — |

## Recipe — Azure CLI

```bash
RG=rg-network-prod
LOC=eastus
HUB=vnet-hub
SPOKE=vnet-spoke-app

az group create -n "$RG" -l "$LOC"

# 1. Hub VNet (gateway, firewall, shared services)
az network vnet create -g "$RG" -n "$HUB" -l "$LOC" --address-prefixes 10.0.0.0/16
az network vnet subnet create -g "$RG" --vnet-name "$HUB" -n GatewaySubnet         --address-prefixes 10.0.255.0/27
az network vnet subnet create -g "$RG" --vnet-name "$HUB" -n AzureFirewallSubnet    --address-prefixes 10.0.0.0/26   # /26 minimum

# 2. Spoke VNet
az network vnet create -g "$RG" -n "$SPOKE" -l "$LOC" --address-prefixes 10.1.0.0/16

az network vnet subnet create -g "$RG" --vnet-name "$SPOKE" -n snet-app                    --address-prefixes 10.1.1.0/24
az network vnet subnet create -g "$RG" --vnet-name "$SPOKE" -n snet-containerapp           --address-prefixes 10.1.2.0/27 --delegations Microsoft.App/environments
az network vnet subnet create -g "$RG" --vnet-name "$SPOKE" -n snet-postgres               --address-prefixes 10.1.3.0/28 --delegations Microsoft.DBforPostgreSQL/flexibleServers
az network vnet subnet create -g "$RG" --vnet-name "$SPOKE" -n snet-appservice-integration --address-prefixes 10.1.4.0/26 --delegations Microsoft.Web/serverFarms
az network vnet subnet create -g "$RG" --vnet-name "$SPOKE" -n snet-pe                     --address-prefixes 10.1.5.0/27   # for private endpoints
az network vnet subnet update    -g "$RG" --vnet-name "$SPOKE" -n snet-pe --disable-private-endpoint-network-policies true

# 3. Default-deny NSG with explicit HTTPS allow (DO NOT block AzureLoadBalancer)
az network nsg create -g "$RG" -n nsg-app
az network nsg rule create -g "$RG" --nsg-name nsg-app --name AllowHTTPS \
  --priority 100 --direction Inbound --protocol Tcp --destination-port-ranges 443 --access Allow
az network vnet subnet update -g "$RG" --vnet-name "$SPOKE" -n snet-app --network-security-group nsg-app

# 4. Hub-spoke peering (use --use-remote-gateways on the spoke if hub has a gateway)
HUB_ID=$(az network vnet show -g "$RG" -n "$HUB"   --query id -o tsv)
SPOKE_ID=$(az network vnet show -g "$RG" -n "$SPOKE" --query id -o tsv)
az network vnet peering create -g "$RG" --vnet-name "$HUB"   -n hub-to-spoke --remote-vnet "$SPOKE_ID" --allow-vnet-access --allow-forwarded-traffic
az network vnet peering create -g "$RG" --vnet-name "$SPOKE" -n spoke-to-hub --remote-vnet "$HUB_ID"   --allow-vnet-access --allow-forwarded-traffic
# Add --use-remote-gateways above if hub has a VPN/ER gateway

# 5. UDR for forced tunneling (spoke → hub firewall)
az network route-table create -g "$RG" -n rt-spoke-app
az network route-table route create -g "$RG" --route-table-name rt-spoke-app -n default-to-firewall \
  --address-prefix 0.0.0.0/0 --next-hop-type VirtualAppliance --next-hop-ip-address 10.0.0.4
az network vnet subnet update -g "$RG" --vnet-name "$SPOKE" -n snet-app --route-table rt-spoke-app
```

## Recipe — Bicep (spoke VNet)

```bicep
param location string = resourceGroup().location
param spokeVNetPrefix string = '10.1.0.0/16'
param firewallPrivateIp string

resource nsgApp 'Microsoft.Network/networkSecurityGroups@2023-09-01' = {
  name: 'nsg-app'
  location: location
  properties: {
    securityRules: [
      {
        name: 'Allow-HTTPS-Inbound'
        properties: {
          priority: 100
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '443'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: '*'
          access: 'Allow'
          direction: 'Inbound'
        }
      }
    ]
  }
}

resource rtApp 'Microsoft.Network/routeTables@2023-09-01' = {
  name: 'rt-spoke-app'
  location: location
  properties: {
    disableBgpRoutePropagation: false
    routes: [
      {
        name: 'default-to-firewall'
        properties: {
          addressPrefix: '0.0.0.0/0'
          nextHopType: 'VirtualAppliance'
          nextHopIpAddress: firewallPrivateIp
        }
      }
    ]
  }
}

resource spoke 'Microsoft.Network/virtualNetworks@2023-09-01' = {
  name: 'vnet-spoke-app'
  location: location
  properties: {
    addressSpace: { addressPrefixes: [ spokeVNetPrefix ] }
    subnets: [
      {
        name: 'snet-app'
        properties: {
          addressPrefix: '10.1.1.0/24'
          networkSecurityGroup: { id: nsgApp.id }
          routeTable: { id: rtApp.id }
        }
      }
      {
        name: 'snet-containerapp'
        properties: {
          addressPrefix: '10.1.2.0/27'   // /27 min (workload profiles)
          delegations: [ { name: 'd', properties: { serviceName: 'Microsoft.App/environments' } } ]
        }
      }
      {
        name: 'snet-postgres'
        properties: {
          addressPrefix: '10.1.3.0/28'   // /28 min
          delegations: [ { name: 'd', properties: { serviceName: 'Microsoft.DBforPostgreSQL/flexibleServers' } } ]
        }
      }
      {
        name: 'snet-appservice-integration'
        properties: {
          addressPrefix: '10.1.4.0/26'   // /26 recommended
          delegations: [ { name: 'd', properties: { serviceName: 'Microsoft.Web/serverFarms' } } ]
        }
      }
      {
        name: 'snet-pe'
        properties: {
          addressPrefix: '10.1.5.0/27'
          privateEndpointNetworkPolicies: 'Disabled'   // required for PEs
        }
      }
    ]
  }
}
```

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| `The subnet is too small` on resource creation | Azure reserves 5 IPs per subnet; what's left is too small | Plan with 2× headroom; **subnets cannot be resized while resources occupy them** — recreate from scratch. |
| `subnet must be delegated to Microsoft.X/...` | No or wrong delegation | Add the correct `delegations` block before resource creation; cannot be changed in place. |
| Backend health probes fail / load-balanced traffic silently dropped | NSG denies the `AzureLoadBalancer` source service tag | Don't override the built-in rule at priority 65001. ([Source](https://learn.microsoft.com/azure/virtual-network/network-security-groups-overview)) |
| Spoke can't reach on-prem after applying UDR | `disableBgpRoutePropagation: true` blocks gateway routes | Set `false`, or add explicit on-prem CIDR routes via `VirtualNetworkGateway` next-hop. |
| Private endpoint resolves to public IP | Private DNS zone not linked to the consuming VNet | Link the `privatelink.*` zone to every VNet that needs to resolve it. See [`azure-private-endpoint`](azure-private-endpoint/SKILL.md). |
| Cannot put NSG on `AzureFirewallSubnet` | The platform disables NSGs on this subnet by design | Don't try; security is enforced by Firewall rules instead. ([Source](https://learn.microsoft.com/azure/firewall/firewall-faq)) |

## References

- [Virtual networks overview](https://learn.microsoft.com/azure/virtual-network/virtual-networks-overview)
- [Hub-and-spoke reference architecture](https://learn.microsoft.com/azure/architecture/reference-architectures/hybrid-networking/hub-spoke)
- [NSG overview](https://learn.microsoft.com/azure/virtual-network/network-security-groups-overview)
- [Subnet delegation](https://learn.microsoft.com/azure/virtual-network/subnet-delegation-overview)
- [Service endpoints vs Private Link](https://learn.microsoft.com/azure/virtual-network/virtual-network-service-endpoints-overview)
- [User-defined routes](https://learn.microsoft.com/azure/virtual-network/virtual-networks-udr-overview)
- [Manage subnets](https://learn.microsoft.com/azure/virtual-network/virtual-network-manage-subnet)
