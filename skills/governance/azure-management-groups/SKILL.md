---
name: azure-management-groups
description: >
  Build the management-group hierarchy under the tenant root: CAF
  pattern (intermediate root → Platform / Landing Zones / Sandbox /
  Decommissioned). Set `requireAuthorizationForGroupCreation` and a
  default MG (NOT root) for new subscriptions. Never assign `deny`
  policies at root MG.
version: 0.1.0
azure_services:
  - Microsoft.Management/managementGroups
  - Microsoft.Management/managementGroups/settings
tags:
  - governance
  - management-groups
  - caf
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/governance/management-groups/overview
  - https://learn.microsoft.com/azure/governance/management-groups/manage
  - https://learn.microsoft.com/azure/governance/management-groups/how-to/protect-resource-hierarchy
  - https://learn.microsoft.com/azure/cloud-adoption-framework/ready/landing-zone/design-area/resource-org-management-groups
  - https://learn.microsoft.com/azure/templates/microsoft.management/managementgroups
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2023-04-01"
last_reviewed: 2026-05-12
---

# Azure Management Groups

## When to use this skill

- The user is bootstrapping a new tenant or doing CAF / Azure Landing
  Zone rollout.
- The user wants to assign Policy or RBAC at higher than subscription
  scope.
- The user wants to bound the blast radius of "Tenant Admin" reach.

## When NOT to use this skill

- Resource-group strategy — see [`azure-resource-groups`](azure-resource-groups/SKILL.md).
- Policy assignment patterns — see [`azure-policy-baseline`](azure-policy-baseline/SKILL.md)
  (Management Groups are *where* you typically assign initiatives).

## Hierarchy facts

| Fact | Value |
| --- | --- |
| Max MGs per directory | 10,000 |
| Max depth (excl. root + subscription) | **6 levels** |
| Each MG / sub has exactly one parent | yes |
| Root MG ID | = the Microsoft Entra tenant ID |
| Default root MG display name | "Tenant root group" |
| Can the root MG be deleted or moved? | **No** |
| New subscriptions default to | Root MG (unless a default MG is configured) |
| Who has access to the root MG by default? | **Nobody** — Global Admins must elevate |
| Cache / token refresh after MG move | up to **30 minutes** |

## CAF recommended hierarchy

```
Tenant Root Group
└── Intermediate Root (e.g., "Contoso")
    ├── Platform
    │   ├── Identity
    │   ├── Management
    │   └── Connectivity
    ├── Landing Zones
    │   ├── Corp        (private-network workloads)
    │   └── Online      (internet-facing workloads)
    ├── Sandbox         (experimentation; loose policies)
    └── Decommissioned  (subs being retired)
```

CAF guidance:
- Keep it ≤ 3–4 levels in practice.
- **Don't** create separate MGs for dev/test/prod — use separate
  subscriptions within the same MG.
- **Don't** assign RBAC at MG scope for app teams; use sub/RG scope.
- **Do** assign Policy + RBAC at MG scope for **platform teams** via PIM.

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| `requireAuthorizationForGroupCreation` (root settings) | `true` | Prevents any user from creating MGs under root; only those with `Microsoft.Management/managementGroups/write` on root can create. |
| `defaultManagementGroup` | a **sandbox** / quarantine MG, not root | New subscriptions land somewhere bounded — not under root-level policies. |
| Policy assignments at root | only "must-have" `audit` | A `deny` policy at root breaks **every** subscription in the tenant. |
| RBAC at root | minimal; PIM + just-in-time elevation for `Owner` / `User Access Administrator` | Inheritance is total. |
| Subscription move tokens | account for the **30-min** propagation | Test access expectations after the wait. |

## Recipe — Azure CLI

```bash
# Create an MG under a parent (omit --parent to create under root)
az account management-group create -n mg-platform -d 'Platform' --parent mg-contoso-root

# List
az account management-group list -o table

# Show hierarchy (recursive)
az account management-group show -n mg-contoso-root -e -r

# Move a subscription
az account management-group subscription add -n mg-sandbox --subscription <sub-id>

# Delete (must be empty first)
az account management-group delete -n mg-old

# Hierarchy settings (no native `az` command — use REST)
TENANT=<tenant-id>
TOKEN=$(az account get-access-token --query accessToken -o tsv)
curl -X PUT \
  "https://management.azure.com/providers/Microsoft.Management/managementGroups/${TENANT}/settings/default?api-version=2020-05-01" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{
    "properties": {
      "requireAuthorizationForGroupCreation": true,
      "defaultManagementGroup": "/providers/Microsoft.Management/managementGroups/mg-sandbox"
    }
  }'

# Assign RBAC at MG scope
az role assignment create --role Reader --assignee <principal-id> \
  --scope /providers/Microsoft.Management/managementGroups/mg-platform
```

## Recipe — Bicep (tenant scope)

```bicep
// Deploy with: az deployment tenant create --location eastus --template-file main.bicep
targetScope = 'tenant'

resource mgRoot 'Microsoft.Management/managementGroups@2023-04-01' = {
  name: 'mg-contoso'
  properties: { displayName: 'Contoso' }
  // No parent → child of Tenant Root Group
}

resource mgPlatform 'Microsoft.Management/managementGroups@2023-04-01' = {
  name: 'mg-platform'
  properties: {
    displayName: 'Platform'
    details: { parent: { id: mgRoot.id } }
  }
}

resource mgIdentity 'Microsoft.Management/managementGroups@2023-04-01' = {
  name: 'mg-identity'
  properties: {
    displayName: 'Identity'
    details: { parent: { id: mgPlatform.id } }
  }
}

resource mgSandbox 'Microsoft.Management/managementGroups@2023-04-01' = {
  name: 'mg-sandbox'
  properties: {
    displayName: 'Sandbox'
    details: { parent: { id: mgRoot.id } }
  }
}
```

**RBAC at MG scope:**
```bicep
targetScope = 'managementGroup'

var readerRoleId = 'acdd72a7-3385-48ef-bd42-f606fba81ae7'

resource readerAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(managementGroup().id, readerRoleId, '<principal-id>')
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions', readerRoleId)
    principalId: '<principal-objectid>'
    principalType: 'Group'
  }
}
```

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| `deny` policy at root broke deployments tenant-wide | Policy with `deny` effect at root MG inherits to every resource | Never `deny` at root; use `audit` at root, `deny` at lower MGs (Landing Zones). |
| `AuthorizationFailed` even though the user is a sub Owner | A deny assignment exists at a parent MG that overrides | `az role assignment list --include-deny` at the higher scope; remove or scope the deny. |
| `az account management-group delete` fails | MG still has child MGs / subscriptions | Move children out first. |
| New subscription inherits unwanted policies | Subscription went to root MG by default | Set the `defaultManagementGroup` to a sandbox MG (REST API). |
| Subscription move rejected: "breaking role definition path" | A custom role's `assignableScopes` is on the source MG and the sub has an active assignment | Add the destination MG to the role's `assignableScopes` first, or remove the assignment, then move. |
| RBAC change not visible for ~30 minutes after a move | ARM token / MG cache TTL | Wait or re-auth. |

## References

- [Management groups overview](https://learn.microsoft.com/azure/governance/management-groups/overview)
- [Manage management groups](https://learn.microsoft.com/azure/governance/management-groups/manage)
- [Protect resource hierarchy](https://learn.microsoft.com/azure/governance/management-groups/how-to/protect-resource-hierarchy)
- [CAF: resource org with management groups](https://learn.microsoft.com/azure/cloud-adoption-framework/ready/landing-zone/design-area/resource-org-management-groups)
- [`Microsoft.Management/managementGroups` template](https://learn.microsoft.com/azure/templates/microsoft.management/managementgroups)
