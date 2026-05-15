---
name: azure-bastion
description: >
  Azure Bastion = secure RDP/SSH to VMs without public IPs. Subnet
  MUST be named exactly `AzureBastionSubnet` (case-sensitive), /26 or
  larger, no UDR, no delegations. Standard SKU+ unlocks the native
  client (`az network bastion ssh|rdp|tunnel`), shareable links, IP-
  based connection, and custom inbound ports. Premium adds session
  recording and private-only (no public IP) deployment.
version: 0.1.0
azure_services:
  - Microsoft.Network/bastionHosts
  - Microsoft.Network/virtualNetworks/subnets (AzureBastionSubnet)
  - Microsoft.Network/publicIPAddresses
tags:
  - networking
  - bastion
  - secure-vm-access
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/bastion/bastion-overview
  - https://learn.microsoft.com/azure/bastion/bastion-sku-comparison
  - https://learn.microsoft.com/azure/bastion/configuration-settings
  - https://learn.microsoft.com/azure/bastion/bastion-nsg
  - https://learn.microsoft.com/azure/bastion/create-host-cli
  - https://learn.microsoft.com/azure/bastion/connect-vm-native-client-windows
  - https://learn.microsoft.com/azure/bastion/connect-ip-address
  - https://learn.microsoft.com/azure/bastion/session-recording
  - https://learn.microsoft.com/azure/bastion/bastion-faq
validated_with:
  az_cli: ">=2.32.0 (with `bastion` extension for native client)"
  api_version: "2024-05-01"
last_reviewed: 2026-05-15
---

# Azure Bastion

## When to use this skill

- VMs should not have public IPs but operators still need RDP/SSH.
- The user wants Entra-authenticated RDP/SSH (Standard+).
- Premium: session recording for audit, or private-only Bastion (no
  public IP at all).

## When NOT to use this skill

- VMs that need automated agent-style access — use a managed identity +
  Azure RBAC and skip interactive sign-in entirely.
- One-off short-lived JIT access — Defender for Cloud's
  Just-in-Time VM access is a separate feature; see
  [`microsoft-defender-for-cloud`](../../security/microsoft-defender-for-cloud/SKILL.md).

## SKU comparison

| Feature | Developer | Basic | Standard | Premium |
| --- | --- | --- | --- | --- |
| Cost | free | hourly | hourly | hourly |
| AzureBastionSubnet required | no | yes (/26+) | yes (/26+) | yes (/26+) |
| Public IP required | no | yes (Std Static) | yes (Std Static) | **no** (private-only available) |
| Concurrent VMs | 1 | many | many | many |
| Host scaling (instances) | 1 | 2 | **2–50** | 2–50 |
| Native client (`az network bastion ...`) | ❌ | ❌ | **✅** | ✅ |
| Shareable link | ❌ | ❌ | **✅** | ✅ |
| IP-based connection (peered VNet, on-prem) | ❌ | ❌ | **✅** | ✅ |
| Custom inbound port | ❌ | ❌ | **✅** | ✅ |
| File transfer (native client) | ❌ | ❌ | **✅** | ✅ |
| Connect Linux via RDP / Windows via SSH | ❌ | ❌ | **✅** | ✅ |
| **Session recording** | ❌ | ❌ | ❌ | **✅** |
| **Private-only (no public IP)** | ❌ | ❌ | ❌ | **✅** |
| VNet peering | no | yes | yes | yes |

> Upgrading Basic → Standard → Premium is supported in-place.
> **Downgrade is not** — delete and recreate.

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| `AzureBastionSubnet` name | exactly `AzureBastionSubnet` (case-sensitive) | Any other name → deployment fails. |
| Subnet size | **/26** or larger | /27 was deprecated 2021-11-02 for new deployments. |
| UDR on AzureBastionSubnet | **none** | UDR breaks Bastion. Force-tunneling 0.0.0.0/0 also breaks it. |
| Subnet delegations | none | Don't delegate this subnet. |
| Public IP | Standard SKU, Static, same region (Std/Basic only — Premium can be private-only) | Mismatch → deploy fails. |
| Host SKU | **Standard** minimum for production | Basic lacks native client / shareable link / IP connect / session recording. |
| `enableTunneling` | `true` (Standard+) | Enables `az network bastion ssh|rdp|tunnel`. |
| `enableShareableLink` | only when needed; user must confirm | Web-based VM access without portal. |
| `disableCopyPaste` | `true` for high-sec workloads | Disables clipboard sharing in browser session. |
| Target VM NSG | inbound 22 / 3389 from `AzureBastionSubnet` only — NOT from internet | Bastion is the only path. |
| Session recording (Premium) | enable for prod / audited environments | All sessions are recorded; cannot be selective. |

## Required NSG rules on AzureBastionSubnet

If you place an NSG on the subnet, **all** of these are required.
Missing any one breaks platform updates or VM connectivity.

**Inbound:**

| Rule | Source | Destination | Port | Protocol |
| --- | --- | --- | --- | --- |
| AllowHttpsInbound | Internet | * | 443 | TCP |
| AllowGatewayManagerInbound | GatewayManager | * | 443 | TCP |
| AllowBastionHostCommunication | VirtualNetwork | VirtualNetwork | 8080, 5701 | * |
| AllowAzureLoadBalancerInbound | AzureLoadBalancer | * | 443 | TCP |

**Outbound:**

| Rule | Source | Destination | Port | Protocol |
| --- | --- | --- | --- | --- |
| AllowSshRdpOutbound | * | VirtualNetwork | 22, 3389 | * |
| AllowAzureCloudOutbound | * | AzureCloud | 443 | TCP |
| AllowBastionCommunication | VirtualNetwork | VirtualNetwork | 8080, 5701 | * |
| AllowHttpOutbound | * | Internet | 80 | * |

## Recipe — Azure CLI

```bash
RG=bastion-rg
LOC=eastus
VNET=hub-vnet
BASTION=hub-bastion

az group create -n "$RG" -l "$LOC"

az network vnet create -g "$RG" -n "$VNET" \
  --address-prefix 10.1.0.0/16 --subnet-name workload --subnet-prefix 10.1.0.0/24

# AzureBastionSubnet — exact name, /26 minimum
az network vnet subnet create -g "$RG" --vnet-name "$VNET" \
  -n AzureBastionSubnet --address-prefix 10.1.1.0/26

# Standard, Static public IP for Bastion frontend
az network public-ip create -g "$RG" -n "${BASTION}-pip" \
  --sku Standard --allocation-method Static -l "$LOC"

# Standard SKU Bastion (≈10 min to provision)
az network bastion create -g "$RG" -n "$BASTION" -l "$LOC" \
  --vnet-name "$VNET" --public-ip-address "${BASTION}-pip" \
  --sku Standard --scale-units 2

# Connect via native client (requires Standard+, az ext bastion >= 2.32)
az network bastion ssh -g "$RG" -n "$BASTION" \
  --target-resource-id "/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Compute/virtualMachines/<vm>" \
  --auth-type ssh-key --username azureuser --ssh-key ~/.ssh/id_rsa

# Open a tunnel for non-CLI clients (e.g. SCP, custom RDP client)
az network bastion tunnel -g "$RG" -n "$BASTION" \
  --target-resource-id "/subscriptions/<sub>/.../virtualMachines/<vm>" \
  --resource-port 22 --port 2222
# Then: ssh azureuser@127.0.0.1 -p 2222
```

## Recipe — Bicep (Standard SKU)

```bicep
param location string = resourceGroup().location
param bastionName string = 'myBastion'
param vnetName string = 'myVNet'

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: vnetName
  location: location
  properties: { addressSpace: { addressPrefixes: [ '10.1.0.0/16' ] } }
}

resource bastionSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' = {
  parent: vnet
  name: 'AzureBastionSubnet'                  // EXACT name required
  properties: { addressPrefix: '10.1.1.0/26' }   // /26 minimum
}

resource bastionPip 'Microsoft.Network/publicIPAddresses@2024-05-01' = {
  name: '${bastionName}-pip'
  location: location
  sku: { name: 'Standard', tier: 'Regional' }
  properties: {
    publicIPAllocationMethod: 'Static'
    publicIPAddressVersion: 'IPv4'
  }
}

resource bastion 'Microsoft.Network/bastionHosts@2024-05-01' = {
  name: bastionName
  location: location
  sku: { name: 'Standard' }                   // Basic | Standard | Premium | Developer
  properties: {
    scaleUnits: 2                             // 2–50 for Standard/Premium
    enableTunneling: true                     // native client
    enableShareableLink: true
    enableIpConnect: true                     // peered/on-prem VMs
    enableFileCopy: true
    disableCopyPaste: false
    enableKerberos: false
    // Premium only:
    // enableSessionRecording: true
    // enablePrivateOnlyBastion: true   // omit publicIPAddress below
    ipConfigurations: [
      {
        name: 'bastionIpConfig'
        properties: {
          publicIPAddress: { id: bastionPip.id }
          subnet: { id: bastionSubnet.id }
          privateIPAllocationMethod: 'Dynamic'
        }
      }
    ]
  }
}

output bastionFqdn string = bastion.properties.dnsName
```

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| Deploy fails: subnet error | Subnet not named exactly `AzureBastionSubnet` (case-sensitive) | Recreate with the correct name |
| Deploy fails: subnet too small | /27 or smaller | Use /26 or larger; pre-existing /27 still works but isn't recommended |
| Bastion connectivity breaks after adding UDR | UDR is **not supported** on `AzureBastionSubnet` | Remove UDR; Bastion-to-VM is private and doesn't need a firewall hop |
| Bastion breaks after enabling default route via VPN/ER | Force-tunneling 0.0.0.0/0 into the Bastion VNet breaks it | Disable default-route propagation on the VNet connection |
| Platform updates blocked or sessions broken | NSG on AzureBastionSubnet missing one of the 8 required rules | Configure all 8 rules exactly as in the docs |
| `az network bastion ssh|rdp` fails: "feature not supported" | Native client requires **Standard SKU** | Upgrade to Standard via portal, or redeploy |
| Session recording UI absent | Session recording requires **Premium SKU** | Upgrade to Premium |
| Can't redeploy: "resource still exists" | Bastion deletion is async (several minutes) | Wait for full delete; also delete Bastion before moving its VNet to a new RG |
| Bastion fails to resolve internal endpoints | VNet linked to a private DNS zone whose name conflicts with `management.azure.com`, `*.core.windows.net`, `*.azure.net` etc. | Unlink the conflicting zones; `privatelink.*` zones are fine |
| Developer SKU can't reach peered VNet VMs | Developer doesn't support VNet peering | Move to Basic+ |

## API versions

| Resource | Recommended | Latest |
| --- | --- | --- |
| `Microsoft.Network/bastionHosts` | `2024-05-01` | `2025-05-01` |
| `Microsoft.Network/publicIPAddresses` | `2024-05-01` | `2025-05-01` |
| `Microsoft.Network/virtualNetworks/subnets` | `2024-05-01` | `2025-05-01` |

## References

- [Bastion overview](https://learn.microsoft.com/azure/bastion/bastion-overview)
- [SKU comparison](https://learn.microsoft.com/azure/bastion/bastion-sku-comparison)
- [Configuration settings](https://learn.microsoft.com/azure/bastion/configuration-settings)
- [NSG rules](https://learn.microsoft.com/azure/bastion/bastion-nsg)
- [Create via CLI](https://learn.microsoft.com/azure/bastion/create-host-cli)
- [Native client (Windows)](https://learn.microsoft.com/azure/bastion/connect-vm-native-client-windows)
- [IP-based connection](https://learn.microsoft.com/azure/bastion/connect-ip-address)
- [Session recording](https://learn.microsoft.com/azure/bastion/session-recording)
- [Bastion FAQ](https://learn.microsoft.com/azure/bastion/bastion-faq)
