---
name: azure-firewall
description: >
  Provision Azure Firewall (Standard / Premium) with Firewall Policy
  (the modern way), zone-redundant deployment, threat-intel set to
  Deny, IDPS on Premium, and the per-rule-type processing order
  (DNAT → Network → Application) that's the most common rule-order
  mistake.
version: 0.1.0
azure_services:
  - Microsoft.Network/azureFirewalls
  - Microsoft.Network/firewallPolicies
  - Microsoft.Network/firewallPolicies/ruleCollectionGroups
  - Microsoft.Network/publicIPAddresses
tags:
  - networking
  - firewall
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/firewall/overview
  - https://learn.microsoft.com/azure/firewall/choose-firewall-sku
  - https://learn.microsoft.com/azure/firewall/features-by-sku
  - https://learn.microsoft.com/azure/firewall/deploy-bicep
  - https://learn.microsoft.com/azure/firewall-manager/quick-firewall-policy
  - https://learn.microsoft.com/azure/firewall/rule-processing
  - https://learn.microsoft.com/azure/firewall/firewall-known-issues
  - https://learn.microsoft.com/azure/firewall/forced-tunneling
  - https://learn.microsoft.com/azure/firewall/firewall-faq
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2022-01-01"
last_reviewed: 2026-05-11
---

# Azure Firewall (secure baseline)

## When to use this skill

- Centralized egress filtering and L7 inspection for a hub VNet.
- TLS inspection / IDPS / URL filtering — Premium-only features.
- Network-wide FQDN allow-listing.

## When NOT to use this skill

- Per-app L7 ingress with WAF — that's
  [`azure-application-gateway`](../azure-application-gateway/SKILL.md) or
  [`azure-front-door`](../azure-front-door/SKILL.md).
- Pure outbound NAT only — Azure NAT Gateway is cheaper.

## SKU picker

| Need | Tier |
| --- | --- |
| Dev / non-prod, small | Basic (250 Mbps fixed; **threat-intel can only Alert, never Deny**; no forced tunneling; no DNS proxy) |
| Prod L4 + L7 with FQDN filtering, autoscale up to 30 Gbps | **Standard** |
| TLS inspection, IDPS (67k+ signatures), URL filtering, Web Categories with TLS, 100 Gbps | **Premium** |

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| `AzureFirewallSubnet` | name reserved; **`/26` minimum** | Hard requirement. |
| **No NSG on `AzureFirewallSubnet`** | platform-disabled | Attaching one can silently break traffic. ([Source](https://learn.microsoft.com/azure/firewall/firewall-faq)) |
| Public IP for the firewall | **Standard SKU**, **Static** allocation, zone-redundant | Required by Standard / Premium tiers. Must exist **before** firewall create. |
| `zones` (firewall + public IP) | `[ '1', '2', '3' ]` | Zone-redundant deployment in supported regions. |
| `firewallPolicy.id` | reference a Firewall Policy | Modern approach. **Don't mix** with inline rule collections on the firewall resource. |
| `threatIntelMode` (on Firewall Policy) | `'Deny'` for prod (default is `'Alert'`) | Block known-bad IPs/FQDNs. **Basic SKU can only Alert.** |
| `intrusionDetection.mode` (Premium) | `'Deny'` (or start `'Alert'` then promote) | IDPS signature-based blocking. |
| `dnsSettings.enableProxy` | `true` | Required for FQDN-based network rules. |
| Diagnostic settings | route `AzureFirewallApplicationRule`, `AzureFirewallNetworkRule`, `AzureFirewallThreatIntelLog` to a LAW | Hunt without one of these = blind. See [`azure-monitor-diagnostic-settings`](../../observability/azure-monitor-diagnostic-settings/SKILL.md). |

## Rule processing order — the trap

Azure Firewall always processes rules **by type**, not by numeric priority:

> **DNAT → Network → Application**

A low-priority *Application* rule does **not** preempt a high-priority
*Network* rule. ([Source](https://learn.microsoft.com/azure/firewall/rule-processing))

For "block this IP/port", use a **Network** rule. For "allow these
FQDNs over HTTP/HTTPS", use an **Application** rule.

## Recipe — Azure CLI

```bash
RG=rg-firewall-prod
LOC=eastus
VNET=vnet-hub
FW=azfw-hub
PIP=pip-azfw

az group create -n "$RG" -l "$LOC"

# 1. Hub VNet with AzureFirewallSubnet (/26 minimum)
az network vnet create -g "$RG" -n "$VNET" --address-prefix 10.0.0.0/16
az network vnet subnet create -g "$RG" --vnet-name "$VNET" -n AzureFirewallSubnet \
  --address-prefix 10.0.0.0/26

# 2. Standard Static public IP (must exist before firewall create)
az network public-ip create -g "$RG" -n "$PIP" --sku Standard \
  --allocation-method Static --zone 1 2 3

# 3. Firewall Policy with threat-intel Deny
az network firewall policy create -g "$RG" -n "${FW}-policy" \
  --sku Standard --threat-intel-mode Deny

# 4. Zone-redundant firewall, attached to policy
az network firewall create -g "$RG" -n "$FW" \
  --tier Standard --firewall-policy "${FW}-policy" --zone 1 2 3

# 5. IP configuration (links subnet + public IP)
az network firewall ip-config create -g "$RG" --firewall-name "$FW" \
  -n ipconfig1 --public-ip-address "$PIP" --vnet-name "$VNET"

# 6. Application rule collection (allow Microsoft Update for app subnet)
az network firewall policy rule-collection-group create -g "$RG" \
  --policy-name "${FW}-policy" -n AppRCG --priority 300
az network firewall policy rule-collection-group collection add-filter-collection -g "$RG" \
  --policy-name "${FW}-policy" --rule-collection-group-name AppRCG \
  --name AllowMSUpdate --collection-priority 200 --action Allow \
  --rule-type ApplicationRule --rule-name allow-msupdate \
  --protocols Http=80 Https=443 \
  --source-addresses "10.1.0.0/16" \
  --target-fqdns "*.windowsupdate.com" "*.update.microsoft.com"

# 7. Diagnostic settings → LAW (see observability/azure-monitor-diagnostic-settings)
LAW_ID=/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.OperationalInsights/workspaces/law-hub
az monitor diagnostic-settings create \
  --resource $(az network firewall show -g "$RG" -n "$FW" --query id -o tsv) \
  -n diag-fw --workspace "$LAW_ID" \
  --logs '[{"categoryGroup":"allLogs","enabled":true}]' \
  --metrics '[{"category":"AllMetrics","enabled":true}]'
```

## Recipe — Bicep

```bicep
param firewallName string
param location string = resourceGroup().location
param subnetId string

resource pip 'Microsoft.Network/publicIPAddresses@2023-09-01' = {
  name: '${firewallName}-pip'
  location: location
  sku: { name: 'Standard' }
  zones: [ '1', '2', '3' ]
  properties: { publicIPAllocationMethod: 'Static', publicIPAddressVersion: 'IPv4' }
}

resource policy 'Microsoft.Network/firewallPolicies@2022-01-01' = {
  name: '${firewallName}-policy'
  location: location
  properties: {
    sku: { tier: 'Standard' }            // must match firewall sku.tier
    threatIntelMode: 'Deny'              // start 'Alert' if rolling out
    dnsSettings: { enableProxy: true }
    // For Premium add:
    // intrusionDetection: { mode: 'Deny' }
  }
}

resource fw 'Microsoft.Network/azureFirewalls@2023-09-01' = {
  name: firewallName
  location: location
  zones: [ '1', '2', '3' ]
  properties: {
    sku: { name: 'AZFW_VNet', tier: 'Standard' }
    firewallPolicy: { id: policy.id }
    ipConfigurations: [
      {
        name: 'ipconfig1'
        properties: {
          subnet: { id: subnetId }       // AzureFirewallSubnet
          publicIPAddress: { id: pip.id }
        }
      }
    ]
  }
}
```

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| `Public IP not found` on firewall create | The Standard / Static public IP must exist **before** the firewall | Create it first. |
| Traffic that "should match an Application rule" hits a Network deny first | Per-type processing order: DNAT → Network → Application | Move the matching logic to a Network rule, or reshape the rule sets. ([Source](https://learn.microsoft.com/azure/firewall/rule-processing)) |
| Threat-intel alerts fire but traffic still flows | Default `threatIntelMode: 'Alert'` (and Basic SKU can never Deny) | Switch to `'Deny'` on Standard / Premium. |
| DNAT inbound rule stops working after enabling forced tunneling | By design — forced tunneling causes asymmetric routing | Don't combine inbound DNAT with forced tunneling on the same firewall. ([Source](https://learn.microsoft.com/azure/firewall/firewall-known-issues)) |
| Child Firewall Policy FQDN rules break DNS resolution | DNS settings are **not** inherited from parent to child policies | Configure `dnsSettings` on each child policy. |
| SNAT port exhaustion | Default ~2,496 ports per public IP per backend instance | Add more public IPs (each adds ports), or attach a NAT Gateway to the subnet. |
| Outbound port 25 blocked | Azure platform blocks port 25 outbound by default — not specific to Firewall | Use authenticated SMTP relay on port 587. |

## References

- [Azure Firewall overview](https://learn.microsoft.com/azure/firewall/overview)
- [Choose a SKU](https://learn.microsoft.com/azure/firewall/choose-firewall-sku)
- [Features by SKU](https://learn.microsoft.com/azure/firewall/features-by-sku)
- [Deploy with Bicep](https://learn.microsoft.com/azure/firewall/deploy-bicep)
- [Firewall Policy quickstart](https://learn.microsoft.com/azure/firewall-manager/quick-firewall-policy)
- [Rule processing order](https://learn.microsoft.com/azure/firewall/rule-processing)
- [Known issues](https://learn.microsoft.com/azure/firewall/firewall-known-issues)
- [Forced tunneling](https://learn.microsoft.com/azure/firewall/forced-tunneling)
- [FAQ](https://learn.microsoft.com/azure/firewall/firewall-faq)
