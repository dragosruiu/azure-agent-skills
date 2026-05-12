---
name: azure-batch
description: >
  Provision an Azure Batch account (`Microsoft.Batch/batchAccounts`)
  with system MI, public access disabled, **Entra-ID-only** auth (no
  shared key), `BatchAccountManagedIdentity` for auto-storage, and
  Simplified node communication. Pools and tasks are typically managed
  via the Batch SDK / API, not Bicep.
version: 0.1.0
azure_services:
  - Microsoft.Batch/batchAccounts
  - Microsoft.Batch/batchAccounts/pools
tags:
  - compute
  - batch
  - hpc
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/batch/batch-technical-overview
  - https://learn.microsoft.com/azure/templates/microsoft.batch/batchaccounts
  - https://learn.microsoft.com/azure/batch/batch-account-create-portal
  - https://learn.microsoft.com/azure/batch/security-best-practices
  - https://learn.microsoft.com/azure/batch/simplified-compute-node-communication
  - https://learn.microsoft.com/azure/batch/private-connectivity
  - https://learn.microsoft.com/azure/batch/batch-application-packages
  - https://learn.microsoft.com/azure/batch/batch-automatic-scaling
  - https://learn.microsoft.com/azure/batch/nodes-and-pools
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2025-06-01"
last_reviewed: 2026-05-12
---

# Azure Batch

## When to use this skill

- The user has many independent tasks to run in parallel (rendering,
  monte-carlo, transcode, AI training preprocessing).
- The user wants to use Spot / low-priority VMs for cost.
- The user needs millions of cores of compute for a few hours.

## When NOT to use this skill

- Long-running stateful services — use App Service / Container Apps /
  AKS.
- Event-driven, individual tasks with sub-minute latency — use Azure
  Functions.
- Container orchestration with networking + service discovery — use
  AKS or Container Apps.

## Pool allocation mode picker

| Need | Mode |
| --- | --- |
| Most workloads; Microsoft-managed VMs in a Batch-managed sub | **`BatchService`** (default) |
| You need the VMs visible in your subscription, want to apply Azure Policy / use Reserved Instances / pull from your own Marketplace agreements | `UserSubscription` (more setup; the `Microsoft Azure Batch` service principal needs `Azure Batch Service Orchestration Role` on the sub, plus a linked Key Vault) |

## Node communication mode

| Mode | Status | Direction |
| --- | --- | --- |
| **Classic** | **Retiring 2026-03-31** | Batch → Nodes (needs inbound NSG rules from `BatchNodeManagement.<region>` on ports 29876-29877) |
| **Simplified** (recommended) | Current | Nodes → Batch (no inbound NSG rules; outbound 443 to `BatchNodeManagement.<region>` only) |

> When `publicNetworkAccess: 'Disabled'` and using Simplified, you
> **must** create the `nodeManagement` private endpoint or nodes go
> unusable.

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| `identity.type` | `'SystemAssigned'` | For Storage / KV access via MI. |
| `properties.poolAllocationMode` | `'BatchService'` (or `'UserSubscription'` if needed) | Default. |
| `properties.publicNetworkAccess` | `'Disabled'` | Pair with **two** PEs (`batchAccount` + `nodeManagement`). |
| `properties.allowedAuthenticationModes` | `[ 'AAD' ]` | Disable shared-key auth entirely. |
| `properties.autoStorage.authenticationMode` | `'BatchAccountManagedIdentity'` | Don't store storage keys; let Batch use its MI. |
| `properties.autoStorage.storageAccountId` | a **non-HNS** storage account | **Application packages are incompatible with HNS-enabled storage accounts.** Use a separate plain storage account. |
| `properties.encryption.keySource` | `'Microsoft.Batch'` (default) — switch to CMK if compliance demands | At-rest encryption. |
| `properties.networkProfile.accountAccess.defaultAction` | `'Deny'` | Default-deny for the account API endpoint. |
| `properties.networkProfile.nodeManagementAccess.defaultAction` | `'Deny'` | Default-deny for node management. |
| Pool node-communication mode | **Simplified** | Classic retires 2026-03-31. |
| Pool autoscale | use a formula with `$NodeDeallocationOption = taskcompletion` | Prevents preempting in-progress tasks during scale-down. |

## Recipe — Azure CLI

```bash
RG=rg-batch-prod
LOC=eastus
BATCH=batch-app-prod
SA=stbatchprod$RANDOM

az group create -n "$RG" -l "$LOC"

# Auto-storage SA (NOT HNS — application packages are incompatible with HNS)
az storage account create -g "$RG" -n "$SA" -l "$LOC" \
  --sku Standard_LRS --allow-blob-public-access false

# Batch account (Entra-only, public access off, MI on)
SA_ID=$(az storage account show -n "$SA" -g "$RG" --query id -o tsv)
az batch account create -g "$RG" -n "$BATCH" -l "$LOC" \
  --storage-account "$SA_ID"

# Login to data plane (Entra)
az batch account login -g "$RG" -n "$BATCH"

# Create a pool (Simplified node communication is the default for new pools)
az batch pool create --id pool-app \
  --vm-size Standard_D4s_v3 \
  --target-dedicated-nodes 2 \
  --image canonical:0001-com-ubuntu-server-jammy:22_04-lts:latest \
  --node-agent-sku-id "batch.node.ubuntu 22.04"

# Create a job + task
az batch job create  --id job-app   --pool-id pool-app
az batch task create --job-id job-app --task-id task-1 \
  --command-line "/bin/bash -c 'echo hello from batch'"
```

## Recipe — Bicep (account + two PEs)

```bicep
param batchAccountName string
param storageAccountId string
param subnetId string
param location string = resourceGroup().location

resource batchAccount 'Microsoft.Batch/batchAccounts@2025-06-01' = {
  name: batchAccountName
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    poolAllocationMode: 'BatchService'
    publicNetworkAccess: 'Disabled'
    allowedAuthenticationModes: [ 'AAD' ]
    autoStorage: {
      storageAccountId: storageAccountId
      authenticationMode: 'BatchAccountManagedIdentity'
    }
    encryption: { keySource: 'Microsoft.Batch' }
    networkProfile: {
      accountAccess:        { defaultAction: 'Deny' }
      nodeManagementAccess: { defaultAction: 'Deny' }
    }
  }
}

// Two private endpoints — one per groupId
resource peAccount 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: '${batchAccountName}-pe-account'
  location: location
  properties: {
    subnet: { id: subnetId }
    privateLinkServiceConnections: [
      {
        name: 'plsc-account'
        properties: {
          privateLinkServiceId: batchAccount.id
          groupIds: [ 'batchAccount' ]
        }
      }
    ]
  }
}

resource peNodeMgmt 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: '${batchAccountName}-pe-nodemgmt'
  location: location
  properties: {
    subnet: { id: subnetId }
    privateLinkServiceConnections: [
      {
        name: 'plsc-nodemgmt'
        properties: {
          privateLinkServiceId: batchAccount.id
          groupIds: [ 'nodeManagement' ]
        }
      }
    ]
  }
}
```

> Pools (`Microsoft.Batch/batchAccounts/pools`) are deployable via
> Bicep but most production teams manage them via the Batch SDK so
> autoscale formulas can change without IaC redeploys. The
> [AVM batch-account module](https://github.com/Azure/bicep-registry-modules/tree/main/avm/res/batch/batch-account)
> is a sound starting point.

## Autoscale formula

```text
startingNumberOfVMs = 1;
maxNumberofVMs      = 25;
pendingTaskSamplePercent = $PendingTasks.GetSamplePercent(TimeInterval_Minute * 15);
pendingTaskSamples = pendingTaskSamplePercent < 70
    ? startingNumberOfVMs
    : avg($PendingTasks.GetSample(TimeInterval_Minute * 15));
$TargetDedicatedNodes  = min(maxNumberofVMs, pendingTaskSamples);
$NodeDeallocationOption = taskcompletion;   // wait for running tasks before removing nodes
```

Useful variables: `$PendingTasks`, `$TargetDedicatedNodes`,
`$TargetLowPriorityNodes`, `$NodeDeallocationOption`
(`requeue` (default) / `terminate` / `taskcompletion` / `retaineddata`).

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| Pool stuck "resizing" (UserSubscription mode) | `Microsoft Azure Batch` service principal lacks **Azure Batch Service Orchestration Role** on the sub | Have a sub Owner grant the role. |
| Pool stuck "resizing" (region quota) | No quota for the chosen VM size in the region | `az batch account show --query dedicatedCoreQuota`; request quota increase via Support. |
| Autoscale scales to 0 too aggressively | `$PendingTasks` returns 0 between batches | Use the `GetSamplePercent` guard (the snippet above), and set `$NodeDeallocationOption = taskcompletion`. |
| Spot VM evicted mid-task and the work is lost | No retry on the task; default `$NodeDeallocationOption = requeue` not enough on its own | Set `maxRetryCount` on the task; ensure `requeue` deallocation; idempotent task code. |
| Nodes go unusable in Simplified mode | Public access disabled but no `nodeManagement` PE | Create the `nodeManagement` PE in the pool's VNet and link DNS. |
| Application package install fails | Auto-storage SA has HNS enabled | App packages are incompatible with HNS; use a separate non-HNS storage account. |
| Marketplace VM image fails to allocate (UserSubscription) | Marketplace legal terms not accepted | `Set-AzMarketplaceTerms -Accept` for the offer/publisher/sku. |
| Data-plane API call fails after disabling public access | Caller is outside the VNet that has the `batchAccount` PE | Run from inside the VNet (or add another PE in the caller's VNet). |

## References

- [Batch overview](https://learn.microsoft.com/azure/batch/batch-technical-overview)
- [`Microsoft.Batch/batchAccounts` template](https://learn.microsoft.com/azure/templates/microsoft.batch/batchaccounts)
- [Create a Batch account (portal)](https://learn.microsoft.com/azure/batch/batch-account-create-portal)
- [Security best practices](https://learn.microsoft.com/azure/batch/security-best-practices)
- [Simplified compute node communication](https://learn.microsoft.com/azure/batch/simplified-compute-node-communication)
- [Private connectivity](https://learn.microsoft.com/azure/batch/private-connectivity)
- [Application packages](https://learn.microsoft.com/azure/batch/batch-application-packages)
- [Automatic scaling](https://learn.microsoft.com/azure/batch/batch-automatic-scaling)
- [Nodes and pools](https://learn.microsoft.com/azure/batch/nodes-and-pools)
