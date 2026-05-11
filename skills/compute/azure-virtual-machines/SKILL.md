---
name: azure-virtual-machines
description: >
  Provision Linux VMs with secure defaults: Trusted Launch (Gen2 image,
  Secure Boot, vTPM), Encryption at Host (preferred over the
  retiring-2028 ADE), SSH-key-only auth, no public IP (use Bastion),
  system-assigned MI, accelerated networking, and JIT access via
  Defender for Servers Plan 2.
version: 0.1.0
azure_services:
  - Microsoft.Compute/virtualMachines
  - Microsoft.Network/networkInterfaces
  - Microsoft.Network/bastionHosts
tags:
  - compute
  - vm
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/virtual-machines/trusted-launch
  - https://learn.microsoft.com/azure/virtual-machines/disk-encryption-overview
  - https://learn.microsoft.com/azure/virtual-machines/linux/disk-encryption-key-vault
  - https://learn.microsoft.com/azure/virtual-machines/linux/create-ssh-secured-vm-from-template
  - https://learn.microsoft.com/azure/defender-for-cloud/just-in-time-access-usage
  - https://learn.microsoft.com/azure/bastion/configuration-settings
  - https://learn.microsoft.com/azure/virtual-network/accelerated-networking-overview
  - https://learn.microsoft.com/azure/azure-monitor/agents/azure-monitor-agent-manage
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2024-07-01"
last_reviewed: 2026-05-11
---

# Azure Virtual Machines (Linux, secure baseline)

## When to use this skill

- The workload is lift-and-shift, needs a specific OS / kernel tunable,
  or relies on installed daemons that don't fit App Service / Container
  Apps.
- The user needs Trusted Launch (Secure Boot, vTPM, attestation) — VMs
  are the only Azure compute that exposes those primitives.

## When NOT to use this skill

- Stateless web app — App Service / Container Apps / Functions.
- Containerized microservice — Container Apps or AKS.
- The user just wants "a Linux box for a script" — Container Instances
  or a one-off Container App is cheaper to operate.

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| `--security-type` / `securityProfile.securityType` | `'TrustedLaunch'` | Adds Secure Boot + vTPM + Defender boot integrity. Requires a **Gen2 image** (suffix `-gen2`). The "Trusted Launch as default" behavior is in preview; assert explicitly until GA. |
| `--enable-secure-boot` | `true` | Rejects unsigned boot loaders / kernel modules. |
| `--enable-vtpm` | `true` | Required for Defender boot-integrity monitoring. |
| `securityProfile.encryptionAtHost` | `true` | **Preferred over Azure Disk Encryption (ADE) for new VMs.** Encrypts temp disk + caches + data flows. **ADE retires 2028-09-15** and ADE-encrypted disks won't unlock after that. ([Source](https://learn.microsoft.com/azure/virtual-machines/disk-encryption-overview)) |
| `--authentication-type` | `'ssh'` (and `disablePasswordAuthentication: true`) | SSH key auth only. Cannot be reverted via portal post-creation. |
| Public IP | omit / `--public-ip-address ""` | Use Azure Bastion (subnet `AzureBastionSubnet`, **`/26` minimum**) or a VPN. |
| `--assign-identity` | enabled | System MI for Key Vault / Storage / Monitor without secrets. |
| `--accelerated-networking` | `true` | Cannot be enabled on a running VM — set at create or deallocate first. |
| `--zone` | `1` (or 2/3) | Zonal placement for AZ resilience; spread instances across zones. |
| Azure Monitor Agent | install via VM extension `AzureMonitorLinuxAgent` (publisher `Microsoft.Azure.Monitor`) + a DCR association | Old `OmsAgentForLinux` is deprecated; AMA is the modern path. |
| Customer-managed key (CMK) for OS disk | Disk Encryption Set + Key Vault with **soft-delete + purge protection** | Compliance scenarios. KV must be hardened **before** linking. ([Source](https://learn.microsoft.com/azure/virtual-machines/linux/disk-encryption-key-vault)) |
| Just-In-Time (JIT) VM access | enable Defender for Cloud → **Defender for Servers Plan 2** on the subscription | JIT requires Plan 2 specifically — Plan 1 doesn't include it. ([Source](https://learn.microsoft.com/azure/defender-for-cloud/just-in-time-access-usage)) |

## Recipe — Azure CLI

```bash
RG=rg-vm-prod
LOC=eastus
VM=vm-app-prod
VNET=vnet-app
SUBNET=snet-app
BASTION_PIP=pip-bastion

# 1. Linux VM: Trusted Launch + SSH-only + system MI + no public IP
az vm create -g "$RG" -n "$VM" \
  --image "Canonical:0001-com-ubuntu-minimal-jammy:minimal-22_04-lts-gen2:latest" \
  --size Standard_D2s_v5 \
  --admin-username azureuser \
  --authentication-type ssh --generate-ssh-keys \
  --security-type TrustedLaunch --enable-secure-boot true --enable-vtpm true \
  --assign-identity \
  --accelerated-networking true \
  --public-ip-address "" \
  --zone 1 \
  --vnet-name "$VNET" --subnet "$SUBNET"

# 2. Encryption at Host (deallocate → enable → start)
az vm deallocate -g "$RG" -n "$VM"
az vm update -g "$RG" -n "$VM" --set securityProfile.encryptionAtHost=true
az vm start -g "$RG" -n "$VM"

# 3. Azure Monitor Agent (Linux) with auto-upgrade
az vm extension set \
  --publisher Microsoft.Azure.Monitor \
  --name AzureMonitorLinuxAgent \
  --resource-group "$RG" --vm-name "$VM" \
  --enable-auto-upgrade true
# Then attach a DCR via:
#   az monitor data-collection rule association create ...

# 4. Bastion (subnet name MUST be AzureBastionSubnet, minimum /26)
az network public-ip create -g "$RG" -n "$BASTION_PIP" --sku Standard --allocation-method Static
az network bastion create -g "$RG" -n bastion-app -l "$LOC" \
  --vnet-name "$VNET" --public-ip-address "$BASTION_PIP" --sku Standard

# 5. JIT request (requires Defender for Servers Plan 2)
# az security pricing create -n VirtualMachines --tier Standard  (turns on Defender)
# Then in Defender for Cloud portal: Workload protections → Just-in-time VM access
```

## Recipe — Bicep

```bicep
param vmName string
param sshPublicKey string
param subnetId string
param location string = resourceGroup().location

resource nic 'Microsoft.Network/networkInterfaces@2023-11-01' = {
  name: '${vmName}-nic'
  location: location
  properties: {
    enableAcceleratedNetworking: true   // immutable on running VM
    ipConfigurations: [
      {
        name: 'ipconfig1'
        properties: {
          subnet: { id: subnetId }
          // No publicIPAddress — access via Bastion
        }
      }
    ]
  }
}

resource vm 'Microsoft.Compute/virtualMachines@2024-07-01' = {
  name: vmName
  location: location
  zones: [ '1' ]
  identity: { type: 'SystemAssigned' }
  properties: {
    hardwareProfile: { vmSize: 'Standard_D2s_v5' }
    securityProfile: {
      securityType: 'TrustedLaunch'
      uefiSettings: { secureBootEnabled: true, vTpmEnabled: true }
      encryptionAtHost: true              // preferred over ADE (retires 2028-09-15)
    }
    osProfile: {
      computerName: vmName
      adminUsername: 'azureuser'
      linuxConfiguration: {
        disablePasswordAuthentication: true
        ssh: {
          publicKeys: [
            { path: '/home/azureuser/.ssh/authorized_keys', keyData: sshPublicKey }
          ]
        }
      }
    }
    storageProfile: {
      imageReference: {
        publisher: 'Canonical'
        offer: '0001-com-ubuntu-minimal-jammy'
        sku: 'minimal-22_04-lts-gen2'    // Gen2 required for Trusted Launch
        version: 'latest'
      }
      osDisk: {
        createOption: 'FromImage'
        managedDisk: { storageAccountType: 'Premium_LRS' }
      }
    }
    networkProfile: {
      networkInterfaces: [
        { id: nic.id, properties: { primary: true } }
      ]
    }
  }
}
```

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| Cannot disable password auth post-create | `disablePasswordAuthentication` is a provisioning-time field | Edit `/etc/ssh/sshd_config` inside the OS (`PasswordAuthentication no`) and restart sshd. |
| OS disk CMK setup fails | The Key Vault used for the Disk Encryption Set lacks soft-delete + purge protection | Enable both on the KV first. ([Source](https://learn.microsoft.com/azure/virtual-machines/linux/disk-encryption-key-vault)) |
| JIT button is greyed out | Defender for Servers Plan 2 not enabled | `az security pricing create -n VirtualMachines --tier Standard` then enable Plan 2. |
| Bastion deploy fails / connection rejected | `AzureBastionSubnet` smaller than `/26` | Resize to `/26` (or larger for autoscale). ([Source](https://learn.microsoft.com/azure/bastion/configuration-settings)) |
| `--accelerated-networking` errors enabling on running VM | Immutable on running VMs | Deallocate → enable → start. |
| Trusted Launch VM won't boot after kernel module install | Secure Boot rejects unsigned modules | Sign the module, or temporarily set `secureBootEnabled: false` and investigate. |
| AMA installed but no logs in LAW | Missing Data Collection Rule (DCR) association | Create DCR + association: `az monitor data-collection rule association create ...`. |
| ADE-encrypted VM stops booting after 2028-09-15 | ADE is retired on that date | Migrate to Encryption at Host before then. |

## References

- [Trusted Launch](https://learn.microsoft.com/azure/virtual-machines/trusted-launch)
- [Disk encryption overview](https://learn.microsoft.com/azure/virtual-machines/disk-encryption-overview)
- [CMK with Key Vault](https://learn.microsoft.com/azure/virtual-machines/linux/disk-encryption-key-vault)
- [Create SSH-secured VM (Bicep)](https://learn.microsoft.com/azure/virtual-machines/linux/create-ssh-secured-vm-from-template)
- [Just-in-time VM access](https://learn.microsoft.com/azure/defender-for-cloud/just-in-time-access-usage)
- [Bastion configuration](https://learn.microsoft.com/azure/bastion/configuration-settings)
- [Accelerated networking](https://learn.microsoft.com/azure/virtual-network/accelerated-networking-overview)
- [Manage Azure Monitor Agent](https://learn.microsoft.com/azure/azure-monitor/agents/azure-monitor-agent-manage)
