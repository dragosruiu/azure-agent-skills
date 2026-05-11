---
name: azure-vpn-gateway
description: >
  Provision an Azure VPN Gateway (Generation 2, zone-redundant AZ SKU)
  for site-to-site / point-to-site / VNet-to-VNet hybrid connectivity.
  Active-Active mode for HA, BGP for dynamic routing, and Microsoft
  Entra ID authentication for P2S using the new (preferred) app ID.
version: 0.1.0
azure_services:
  - Microsoft.Network/virtualNetworkGateways
  - Microsoft.Network/localNetworkGateways
  - Microsoft.Network/connections
  - Microsoft.Network/publicIPAddresses
tags:
  - networking
  - vpn
  - hybrid
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/vpn-gateway/vpn-gateway-about-vpngateways
  - https://learn.microsoft.com/azure/vpn-gateway/vpn-gateway-about-vpn-gateway-settings
  - https://learn.microsoft.com/azure/vpn-gateway/about-zone-redundant-vnet-gateways
  - https://learn.microsoft.com/azure/vpn-gateway/about-active-active-gateways
  - https://learn.microsoft.com/azure/vpn-gateway/vpn-gateway-bgp-overview
  - https://learn.microsoft.com/azure/vpn-gateway/bgp-howto
  - https://learn.microsoft.com/azure/vpn-gateway/vpn-gateway-highlyavailable
  - https://learn.microsoft.com/azure/vpn-gateway/point-to-site-about
  - https://learn.microsoft.com/azure/vpn-gateway/openvpn-azure-ad-tenant
  - https://learn.microsoft.com/azure/vpn-gateway/vpn-gateway-ipsecikepolicy-rm-powershell
  - https://learn.microsoft.com/azure/vpn-gateway/tutorial-create-gateway-portal
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2023-09-01"
last_reviewed: 2026-05-11
---

# Azure VPN Gateway

## When to use this skill

- Connecting on-prem to Azure via IPsec site-to-site (S2S).
- Letting individual end-user devices reach Azure via point-to-site (P2S).
- Connecting two Azure VNets in different regions / subscriptions / tenants.

## When NOT to use this skill

- High-bandwidth / SLA-critical hybrid → **ExpressRoute**.
- > 100 S2S tunnels needed → **Azure Virtual WAN**.
- Pure VNet-to-VNet in the same region with no on-prem → **VNet peering**
  (cheaper, lower latency).

## SKU picker (Generation 2, zone-redundant)

> **Important correction:** there is **no Gen2 VpnGw1AZ**. Gen2 AZ
> SKUs start at `VpnGw2AZ`.

| SKU | Aggregate throughput | S2S tunnels | P2S clients | Zone-redundant |
| --- | --- | --- | --- | --- |
| `VpnGw2AZ` | 1.25 Gbps | 30 | 500 | ✅ |
| `VpnGw3AZ` | 2.5 Gbps | 30 | 1,000 | ✅ |
| `VpnGw4AZ` | 5 Gbps | 100* | 5,000 | ✅ |
| `VpnGw5AZ` | 10 Gbps | 100* | 10,000 | ✅ |

*If you need >100 S2S tunnels, use Virtual WAN.* Basic SKU is dev-only —
no IKEv2, no RADIUS, no OpenVPN, no active-active.

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| Generation | `Generation2` | ~25% better throughput than Gen1. |
| SKU | `VpnGw2AZ` or higher | AZ = zone-redundant. |
| `vpnType` | `'RouteBased'` | Required for BGP, P2S OpenVPN, active-active. PolicyBased is legacy. |
| `gatewayType` | `'Vpn'` | (vs `'ExpressRoute'`.) |
| `enableActiveActive` | `true` | Two public IPs, both in use; needed for max HA. **Cannot use Basic SKU.** |
| Public IP SKU | `Standard` (Static allocation) | Required for Active-Active and zone-redundant. **Two PIPs** for active-active. |
| `enableBgp` | `true` (with custom ASN, not the default `65515` if peering with multiple sites) | Dynamic routing; required for ECMP between active-active tunnels. |
| `GatewaySubnet` (name reserved) | `/27` minimum, `/26` recommended | Allows future ExpressRoute coexistence. **No NSG with `0.0.0.0/0` allowed; no UDR with `0.0.0.0/0` next-hop NVA.** BGP route propagation must be **enabled**. |
| Custom IPsec/IKE policy | only when on-prem device demands it | Once custom, you must specify **all** parameters. |
| P2S Microsoft Entra app | **`c632b3df-fb67-4d84-bdcf-b95ad541b5c8`** (new Microsoft-registered) | Preferred over the legacy `41b23e61-6c1e-4545-b367-cd054e0ed4b4`; supports Linux client; no manual tenant registration needed. |

## P2S authentication picker

| Method | Protocol | Clients | Notes |
| --- | --- | --- | --- |
| Microsoft Entra ID | OpenVPN only | Windows, Mac, Linux (with the new app) | Preferred for end-user devices. |
| Certificate | IKEv2 / SSTP / OpenVPN | All | Upload root CA public key to the gateway. |
| RADIUS | All | All | Gateway forwards to your RADIUS server. |

Basic SKU = SSTP only.

## Recipe — Azure CLI (Active-Active, BGP, S2S)

```bash
RG=rg-vpn-prod
LOC=eastus
VNET=vnet-hub
GW=vpngw-hub
LNG=lng-onprem

az group create -n "$RG" -l "$LOC"

# 1. VNet + GatewaySubnet (/26 recommended)
az network vnet create -g "$RG" -n "$VNET" --address-prefix 10.0.0.0/16
az network vnet subnet create -g "$RG" --vnet-name "$VNET" -n GatewaySubnet \
  --address-prefix 10.0.255.0/26

# 2. Two Standard Static public IPs (for active-active)
az network public-ip create -g "$RG" -n "${GW}-pip1" --sku Standard --allocation-method Static --zone 1 2 3
az network public-ip create -g "$RG" -n "${GW}-pip2" --sku Standard --allocation-method Static --zone 1 2 3

# 3. VPN Gateway (Generation2, VpnGw2AZ, route-based, BGP, active-active) — takes ~30-45 min
az network vnet-gateway create -g "$RG" -n "$GW" -l "$LOC" \
  --vnet "$VNET" \
  --gateway-type Vpn --vpn-type RouteBased \
  --sku VpnGw2AZ --vpn-gateway-generation Generation2 \
  --public-ip-addresses "${GW}-pip1" "${GW}-pip2" \
  --asn 65010 \
  --no-wait
# az network vnet-gateway wait --created -g $RG -n $GW

# 4. Local Network Gateway represents the on-prem device
az network local-gateway create -g "$RG" -n "$LNG" -l "$LOC" \
  --gateway-ip-address 203.0.113.10 \
  --asn 64512 --bgp-peering-address 192.168.1.1 \
  --local-address-prefixes 192.168.0.0/16

# 5. S2S connection with BGP enabled
SHARED_KEY="<pre-shared-key>"
az network vpn-connection create -g "$RG" -n conn-onprem \
  --vnet-gateway1 "$GW" --local-gateway2 "$LNG" \
  --shared-key "$SHARED_KEY" --enable-bgp true
```

## Recipe — Bicep (skeleton; verify API version)

```bicep
// API versions for VPN Gateway resources change frequently.
// Verify against https://learn.microsoft.com/azure/templates/microsoft.network/virtualnetworkgateways

param vpnGwName string
param location string = resourceGroup().location
param gatewaySubnetId string

resource pip1 'Microsoft.Network/publicIPAddresses@2023-09-01' = {
  name: '${vpnGwName}-pip1'
  location: location
  sku: { name: 'Standard' }
  zones: [ '1', '2', '3' ]
  properties: { publicIPAllocationMethod: 'Static' }
}
resource pip2 'Microsoft.Network/publicIPAddresses@2023-09-01' = {
  name: '${vpnGwName}-pip2'
  location: location
  sku: { name: 'Standard' }
  zones: [ '1', '2', '3' ]
  properties: { publicIPAllocationMethod: 'Static' }
}

resource gw 'Microsoft.Network/virtualNetworkGateways@2023-09-01' = {
  name: vpnGwName
  location: location
  properties: {
    gatewayType: 'Vpn'
    vpnType: 'RouteBased'
    vpnGatewayGeneration: 'Generation2'
    sku: { name: 'VpnGw2AZ', tier: 'VpnGw2AZ' }
    activeActive: true
    enableBgp: true
    bgpSettings: {
      asn: 65010
      // bgpPeeringAddresses auto-allocated from the GatewaySubnet
    }
    ipConfigurations: [
      {
        name: 'gwipconfig1'
        properties: {
          subnet: { id: gatewaySubnetId }
          publicIPAddress: { id: pip1.id }
        }
      }
      {
        name: 'gwipconfig2'
        properties: {
          subnet: { id: gatewaySubnetId }
          publicIPAddress: { id: pip2.id }
        }
      }
    ]
  }
}
```

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| Gateway create rejected: subnet not named `GatewaySubnet` | Name is reserved | Rename the subnet exactly. |
| IKEv2 phase-1 mismatch | On-prem device uses non-default cipher / DH group | Configure a custom IPsec/IKE policy on the connection that matches the on-prem device exactly. ([Source](https://learn.microsoft.com/azure/vpn-gateway/vpn-gateway-ipsecikepolicy-rm-powershell)) |
| BGP routes not propagating | `--enable-bgp false` on the connection (not the gateway) | BGP must be enabled on **both** the gateway and on each connection. |
| Active-Active configured but only one tunnel established | On-prem device only configured to peer with one Azure IP | Configure the on-prem device with **both** Azure gateway IPs. ([Source](https://learn.microsoft.com/azure/vpn-gateway/about-active-active-gateways)) |
| P2S Microsoft Entra auth fails | Used the legacy app ID and tenant doesn't have it consented; or didn't use OpenVPN protocol | Use the new app `c632b3df-fb67-4d84-bdcf-b95ad541b5c8`; ensure tunnel type is OpenVPN. |
| `LinuxClient` for Microsoft Entra P2S doesn't connect | Used the **legacy** Entra app (`41b23e61-...`) which doesn't support Linux | Reconfigure the gateway with the new app; reissue client config. |
| BGP transit (spoke→spoke via on-prem) not working | Default-disable on transit; needs explicit BGP config on both connections + matching prefixes | Enable BGP on both connections; review the BGP transit guide. |

## References

- [VPN Gateway overview / SKU table](https://learn.microsoft.com/azure/vpn-gateway/vpn-gateway-about-vpngateways)
- [Gateway settings (GatewaySubnet rules)](https://learn.microsoft.com/azure/vpn-gateway/vpn-gateway-about-vpn-gateway-settings)
- [Zone-redundant gateways](https://learn.microsoft.com/azure/vpn-gateway/about-zone-redundant-vnet-gateways)
- [Active-active gateways](https://learn.microsoft.com/azure/vpn-gateway/about-active-active-gateways)
- [BGP overview](https://learn.microsoft.com/azure/vpn-gateway/vpn-gateway-bgp-overview)
- [BGP how-to](https://learn.microsoft.com/azure/vpn-gateway/bgp-howto)
- [Highly available connectivity](https://learn.microsoft.com/azure/vpn-gateway/vpn-gateway-highlyavailable)
- [Point-to-site overview](https://learn.microsoft.com/azure/vpn-gateway/point-to-site-about)
- [Configure Microsoft Entra tenant for OpenVPN](https://learn.microsoft.com/azure/vpn-gateway/openvpn-azure-ad-tenant)
- [Custom IPsec/IKE policy](https://learn.microsoft.com/azure/vpn-gateway/vpn-gateway-ipsecikepolicy-rm-powershell)
- [Tutorial: create gateway (portal)](https://learn.microsoft.com/azure/vpn-gateway/tutorial-create-gateway-portal)
