---
name: azure-resource-groups
description: >
  Resource group strategy: per-environment, per-application, per-blast-
  radius, or per-lifecycle. CAF naming pattern `rg-<workload>-<env>-<region>`,
  CanNotDelete vs ReadOnly locks (and their gotchas), tag inheritance
  via Azure Policy (forward-only), and which resources can / cannot be
  moved across RGs or subscriptions.
version: 0.1.0
azure_services:
  - Microsoft.Resources/resourceGroups
  - Microsoft.Authorization/locks
tags:
  - governance
  - resource-groups
sources:
  - https://learn.microsoft.com/azure/azure-resource-manager/management/manage-resource-groups-portal
  - https://learn.microsoft.com/azure/azure-resource-manager/management/lock-resources
  - https://learn.microsoft.com/azure/azure-resource-manager/management/move-resource-group-and-subscription
  - https://learn.microsoft.com/azure/azure-resource-manager/management/move-support-resources
  - https://learn.microsoft.com/azure/azure-resource-manager/management/tag-resources
  - https://learn.microsoft.com/azure/azure-resource-manager/management/tag-policies
  - https://learn.microsoft.com/azure/cloud-adoption-framework/ready/azure-best-practices/resource-naming
  - https://learn.microsoft.com/azure/cloud-adoption-framework/ready/azure-best-practices/resource-abbreviations
  - https://learn.microsoft.com/azure/app-service/manage-move-across-regions
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2024-03-01"
last_reviewed: 2026-05-11
---

# Azure resource group strategy

## When to use this skill

- The user is bootstrapping a new subscription / workload and asks
  "how should I group resources?".
- The user accidentally locked themselves out with a `ReadOnly` lock and
  wants to know why VM start now fails.
- The user wants to move resources between RGs or subscriptions.

## When NOT to use this skill

- The user is asking about RG **provisioning** in a Bicep deploy — see
  [`bicep-baseline`](../../infrastructure-as-code/bicep-baseline/SKILL.md).
- The user wants to apply tags to *resources* — see
  [`azure-naming-and-tagging`](../azure-naming-and-tagging/SKILL.md).

## RG strategy decision

| Strategy | Pick when | Risk |
| --- | --- | --- |
| **Per-environment** (`rg-app-dev`, `rg-app-prod`) | You want to delete `dev` without touching `prod` | Cross-env references break |
| **Per-application** (`rg-frontend`, `rg-backend`) | Different teams own different apps; want per-app billing | Must manage cross-RG networking & references |
| **Per-blast-radius** (Tier-0 vs Tier-1 vs sandbox) | You want to bound damage from runaway scripts / policy changes | More RGs to manage |
| **Per-lifecycle** (same RG = same teardown cadence) | Workload deletes/recreates as a unit | Mixing short- and long-lived resources complicates cleanup |

In practice many orgs combine: per-environment **and** per-application,
giving e.g. `rg-frontend-prod-eastus`.

## Secure defaults

| Decision | Default | Why |
| --- | --- | --- |
| Naming | `rg-<workload>-<env>-<region>[-<instance>]` (CAF) | Verified abbreviation: `rg`. |
| RG region | the region the workload lives in (or the primary region for multi-region apps) | RG **metadata** is regional; cannot be changed after creation. |
| Tags on RG | functional, classification, accounting, ownership | They do **not** automatically propagate to children. |
| Tag propagation | assign Azure Policy *Inherit a tag from the resource group [if missing]* (`modify` effect) | Forward-only — does **not** retroactively tag pre-existing resources. Run a remediation task to backfill. |
| Lock for prod RGs | **`CanNotDelete`** (not `ReadOnly`) | `ReadOnly` blocks many POST operations: VM start/stop, storage `listKeys`, App Service scale, RBAC assignments — silently breaking ops. |
| Backup-managed RGs | **don't** apply `CanNotDelete` | Backup needs to delete restore points around the 18-restore-point ceiling. |
| Deployment history | clean periodically (`az deployment group delete`) | RG deployment history caps at ~800 entries; with `CanNotDelete` it can't auto-clean. |
| RG move | check the [move-support matrix](https://learn.microsoft.com/azure/azure-resource-manager/management/move-support-resources) first | Most resources move; some don't (KV with PE, App Service across regions, etc.). |

## Recipe — Bicep

```bicep
// targetScope = 'subscription' to provision the RG itself
targetScope = 'subscription'

param rgName string = 'rg-myapp-prod-eastus'
param location string = 'eastus'

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: rgName
  location: location
  tags: {
    environment: 'prod'
    workload: 'myapp'
    costCenter: 'CC-1234'
    department: 'Engineering'
    businessUnit: 'Platform'
    owner: 'team-platform@contoso.com'
  }
}

// Lock module (deployed at the RG scope)
module rgLock 'lock.bicep' = {
  name: 'rg-delete-lock'
  scope: rg
  params: { lockName: 'rg-delete-lock', lockLevel: 'CanNotDelete' }
}
```

```bicep
// lock.bicep
param lockName string
@allowed([ 'CanNotDelete', 'ReadOnly' ])
param lockLevel string = 'CanNotDelete'

resource lock 'Microsoft.Authorization/locks@2020-05-01' = {
  name: lockName
  properties: {
    level: lockLevel
    notes: 'Prevents accidental deletion of the production resource group'
  }
}
```

## Recipe — Azure CLI

```bash
# Create RG with tags
az group create -n rg-myapp-prod-eastus -l eastus \
  --tags environment=prod workload=myapp costCenter=CC-1234 \
         department=Engineering businessUnit=Platform owner=team-platform

# Lock (CanNotDelete preferred over ReadOnly for prod)
az lock create --name rg-delete-lock \
  --resource-group rg-myapp-prod-eastus --lock-type CanNotDelete \
  --notes "Prevents accidental deletion"

# Move resources between RGs (same subscription)
az resource move --destination-group rg-myapp-prod-eastus-new \
  --ids <resource-id-1> <resource-id-2>

# Move across subscriptions (use --destination-subscription-id)
az resource move \
  --destination-group rg-myapp-prod-eastus \
  --destination-subscription-id <new-sub-id> \
  --ids <resource-id-1>

# Inspect locks blocking a delete
az lock list --resource-group rg-myapp-prod-eastus -o table

# Backfill tags via Azure Policy remediation (after assigning the policy)
az policy remediation create -n rg-tag-backfill \
  --policy-assignment <inherit-tag-assignment-id> \
  --scope /subscriptions/$SUB
```

## Lock cheat sheet

| Lock | Blocks | Doesn't block | Notable side effects |
| --- | --- | --- | --- |
| `CanNotDelete` | Delete | Read, write | Backup auto-cleanup at 18 restore points; deployment history cleanup at ~800 entries |
| `ReadOnly` | Delete + most write/POST | Read | VM start/stop, storage `listKeys`, App Service scale, RBAC assignments, and many service-specific operations all fail. Use sparingly. |

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| Cannot delete RG | A resource inside has a `Delete` lock | `az lock list -g <rg>` and remove blocking locks. |
| Cannot delete RG | A resource is referenced from another RG (subnet delegation, DNS link, etc.) | Delete the referencing resource first. |
| `ReadOnly` causes VM start failure | `ReadOnly` blocks the POST verb VMs use to start | Switch to `CanNotDelete`. |
| `CanNotDelete` breaks Azure Backup | Backup deletes restore points around 18 | Don't lock Backup-managed RGs. |
| Tag isn't on child resources | Tags don't auto-inherit | Assign the Inherit-a-tag Azure Policy + run a remediation task. ([Source](https://learn.microsoft.com/azure/azure-resource-manager/management/tag-policies)) |
| "Region of the RG" can't be changed | RG metadata location is set at creation | Recreate the RG; move resources in. |
| App Service plan + apps move across regions fails | App Service can't move across regions | Recreate in the target region; redeploy. ([Source](https://learn.microsoft.com/azure/app-service/manage-move-across-regions)) |
| Role assignments missing after cross-subscription move | Role assignments don't follow resources across subscriptions | Re-create assignments in the target subscription. |

## References

- [Manage resource groups](https://learn.microsoft.com/azure/azure-resource-manager/management/manage-resource-groups-portal)
- [Lock resources](https://learn.microsoft.com/azure/azure-resource-manager/management/lock-resources)
- [Move resource groups and subscriptions](https://learn.microsoft.com/azure/azure-resource-manager/management/move-resource-group-and-subscription)
- [Move support per resource type](https://learn.microsoft.com/azure/azure-resource-manager/management/move-support-resources)
- [Tag resources](https://learn.microsoft.com/azure/azure-resource-manager/management/tag-resources)
- [Tag policies (inherit-from-RG)](https://learn.microsoft.com/azure/azure-resource-manager/management/tag-policies)
- [CAF naming](https://learn.microsoft.com/azure/cloud-adoption-framework/ready/azure-best-practices/resource-naming)
- [CAF abbreviations](https://learn.microsoft.com/azure/cloud-adoption-framework/ready/azure-best-practices/resource-abbreviations)
- [App Service: move across regions](https://learn.microsoft.com/azure/app-service/manage-move-across-regions)
