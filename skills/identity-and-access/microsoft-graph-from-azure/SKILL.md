---
name: microsoft-graph-from-azure
description: >
  Call Microsoft Graph from an Azure-hosted workload using its Managed
  Identity: app-only access only (`Role` type), token requested with
  `https://graph.microsoft.com/.default` as the scope, app role granted
  via `az rest` or Microsoft Graph PowerShell (no Azure portal UI for
  this), least-privileged permissions (Sites.Selected over Sites.Read.All),
  honor 429 + `Retry-After`, expect up to 24 h MI-token cache delay after
  permission changes.
version: 0.1.0
azure_services:
  - Microsoft.Graph (data plane)
  - Managed Identity service principal
tags:
  - identity
  - microsoft-graph
  - managed-identity
  - security-baseline
sources:
  - https://learn.microsoft.com/graph/auth/auth-concepts
  - https://learn.microsoft.com/graph/permissions-overview
  - https://learn.microsoft.com/graph/permissions-reference
  - https://learn.microsoft.com/entra/identity/managed-identities-azure-resources/how-to-assign-app-role-managed-identity
  - https://learn.microsoft.com/azure/app-service/scenario-secure-app-access-microsoft-graph-as-app
  - https://learn.microsoft.com/graph/throttling
  - https://learn.microsoft.com/graph/throttling-limits
  - https://learn.microsoft.com/graph/templates/reference/overview
validated_with:
  az_cli: ">=2.60.0"
  graph_api: "v1.0"
last_reviewed: 2026-05-15
---

# Microsoft Graph from Azure (Managed Identity)

## When to use this skill

- An Azure App Service / Functions / Container App / VM / AKS pod with
  a managed identity needs to read Entra users, groups, audit logs, or
  send mail / interact with SharePoint / Teams via Graph.
- Pipelines / agents calling Graph for directory automation.

## When NOT to use this skill

- Interactive user-context apps — those use **Delegated** scopes; this
  skill is for app-only workloads.
- App registrations themselves — see
  [`entra-app-registration`](../entra-app-registration/SKILL.md).

## App-only vs delegated

| | App-only (Application permission / `Role`) | Delegated (`Scope`) |
| --- | --- | --- |
| Signed-in user | not required | required |
| Correct for managed identities | ✅ | ❌ MI has no user context |
| Who consents | Global Admin / Privileged Role Admin | user (low-priv) or admin |
| Token-flow scope | `https://graph.microsoft.com/.default` | a specific scope (`User.Read`) |
| Grant object | `appRoleAssignment` | `oauth2PermissionGrant` |

## The `.default` scope

For client credentials / managed identity flows, ask for:

```
https://graph.microsoft.com/.default
```

`.default` means *all consented application permissions on Microsoft
Graph for this principal* — it's not a specific permission. Common
mistakes:

- Passing the **resource URI** `https://graph.microsoft.com` as a
  *scope* in v2 → `AADSTS70011: invalid scope`.
- Acquiring a token for `https://management.azure.com/.default` and then
  trying to call Graph with it → `AADSTS500011: resource principal not
  found in tenant`.

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| Permission type | **Application (`Role`)** | MI has no user context. |
| Permission breadth | **scoped** wherever possible — e.g. `Sites.Selected` over `Sites.Read.All` | Minimal blast radius. |
| Audience | `https://graph.microsoft.com/.default` (v2) | Don't pass the resource URI as a scope. |
| Grant surface | `az rest` POST or `New-MgServicePrincipalAppRoleAssignment` | **There is no Azure portal UI** to grant Graph application permissions to a system-assigned MI. |
| Caller authorization | `AppRoleAssignment.ReadWrite.All` or Global Admin | Required to write `appRoleAssignments`. |
| Throttle handling | honor `Retry-After`; use `$select` / `$filter` / paging | Graph throttles per-app and per-app-and-tenant. |
| Bulk extraction | use [Microsoft Graph Data Connect](https://learn.microsoft.com/graph/data-connect-concept-overview) | Avoid throttle storms. |

## Recipe — granting a Graph permission to a managed identity (`az rest`)

> **There is no portal UI for this on a system-assigned MI.**
> *"Currently, there's no option to assign such permissions through the
> Microsoft Entra admin center."*
> — [App Service / Graph as app](https://learn.microsoft.com/azure/app-service/scenario-secure-app-access-microsoft-graph-as-app)

```bash
# 1. Get the MI's service-principal object ID
MI_OBJ_ID=$(az webapp identity show -g my-rg -n my-app --query principalId -o tsv)
# (For a UAMI: az identity show -g my-rg -n my-uami --query principalId -o tsv)

# 2. Get Microsoft Graph's SP in this tenant (well-known appId)
GRAPH_APP_ID=00000003-0000-0000-c000-000000000000
GRAPH_SP_ID=$(az ad sp list --filter "appId eq '$GRAPH_APP_ID'" --query '[0].id' -o tsv)

# 3. Look up the app-role ID for the permission you want
APP_ROLE_ID=$(az ad sp show --id "$GRAPH_APP_ID" \
  --query "appRoles[?value=='User.Read.All'].id" -o tsv)

# 4. Assign the role
az rest --method POST \
  --uri "https://graph.microsoft.com/v1.0/servicePrincipals/${MI_OBJ_ID}/appRoleAssignments" \
  --body "{
    \"principalId\":\"${MI_OBJ_ID}\",
    \"resourceId\":\"${GRAPH_SP_ID}\",
    \"appRoleId\":\"${APP_ROLE_ID}\"
  }"

# 5. Verify
az rest --method GET \
  --uri "https://graph.microsoft.com/v1.0/servicePrincipals/${MI_OBJ_ID}/appRoleAssignments"
```

## Recipe — same thing in PowerShell

```powershell
Connect-AzAccount -Tenant $TenantId
$miObjectId = (Get-AzWebApp -ResourceGroupName 'my-rg' -Name 'my-app').identity.principalid

Connect-MgGraph -TenantId $TenantId `
  -Scopes 'Application.Read.All','AppRoleAssignment.ReadWrite.All'

$graphSp   = Get-MgServicePrincipal -Filter "DisplayName eq 'Microsoft Graph'"
$appRoleId = ($graphSp.AppRoles | Where-Object Value -eq 'User.Read.All').Id

New-MgServicePrincipalAppRoleAssignment `
  -ServicePrincipalId $miObjectId `
  -PrincipalId        $miObjectId `
  -ResourceId         $graphSp.Id `
  -AppRoleId          $appRoleId
```

## Common application permissions for build scenarios

| Permission | Use case | Notes |
| --- | --- | --- |
| `User.Read.All` | List / read users | App permission; admin consent required |
| `Group.Read.All` | List groups + memberships | App permission |
| `Application.Read.All` | List app registrations + SPs | Useful for inventory tooling |
| `RoleManagement.Read.Directory` | Read Entra directory roles | Inventory / compliance |
| `AuditLog.Read.All` | Read sign-in + audit logs | SIEM ingestion |
| `Sites.Selected` | Per-site SharePoint access | **Preferred** over `Sites.Read.All`; needs an extra per-site grant via `POST /sites/{id}/permissions` |
| `Sites.Read.All` | All SharePoint sites | Broad; avoid unless tenant-wide is truly required |

App role IDs are GUIDs; look up at runtime:

```bash
az ad sp show --id 00000003-0000-0000-c000-000000000000 \
  --query "appRoles[?value=='<PermissionName>'].id" -o tsv
```

## `Sites.Selected` — scoped SharePoint access

`Sites.Selected` alone grants **zero** site access. After granting the
app role, you must additionally grant per-site permission via Graph:

```http
POST https://graph.microsoft.com/v1.0/sites/{site-id}/permissions
Content-Type: application/json

{
  "roles": [ "read" ],
  "grantedToIdentities": [
    { "application": { "id": "<your-app-client-id>", "displayName": "my-build-agent" } }
  ]
}
```

| | `Sites.Selected` | `Sites.Read.All` |
| --- | --- | --- |
| Scope | only sites explicitly granted | every site in the tenant |
| Per-site grant step | required | not required |
| Recommended? | ✅ for any scoped scenario | ⚠️ only if truly tenant-wide |

## Throttling

- HTTP `429 Too Many Requests` with `Retry-After: <seconds>`.
- **Honor `Retry-After`** — retrying earlier delays your recovery.
- Use `$select`, `$filter`, `$top` + paging, delta queries, change
  notifications.
- Global ceiling: **130,000 requests / 10 s** per app across all tenants.
- Per app-and-tenant identity-and-access limits (token bucket): S/M/L
  tier each have separate read RU and write quotas.
- For batches: each request inside `/$batch` is evaluated against the
  throttle limits independently.

## Bicep (Graph extension) — granting an app role on the MI's SP

```bicep
extension graphV1_0

// ⚠️ Schema for `appRoleAssignedTo` — verify at:
// https://learn.microsoft.com/graph/templates/reference/overview
resource graphAppRoleGrant 'Microsoft.Graph/appRoleAssignedTo@v1.0' = {
  principalId: '<MI-SP-object-id>'           // the managed identity's SP objectId
  resourceId:  '<Microsoft-Graph-SP-object-id-in-this-tenant>'
  appRoleId:   '<app-role-id-for-the-permission>'
}
```

For most production scenarios the `az rest` approach (above) is the
verified and most-used path; the Bicep variant requires the deploying
identity to hold `AppRoleAssignment.ReadWrite.All`.

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| Can't find Graph permissions UI for the MI | Azure portal doesn't expose this | Use `az rest` or `Connect-MgGraph` |
| `AADSTS70011: invalid scope` | Used `https://graph.microsoft.com` as a v2 *scope* | Use `https://graph.microsoft.com/.default` |
| `AADSTS500011: resource principal not found` | Token was acquired for the wrong audience (e.g. ARM) and used against Graph | Acquire token specifically for Graph |
| 403 even after granting permission | MI token is cached up to **24 h** at the resource backend | Restart the App Service / VM to force token refresh |
| `Authorization_RequestDenied` for `Sites.Selected` | App role granted but no per-site grant exists | `POST /sites/{id}/permissions` to grant per-site access |
| Delegated permission granted to MI does nothing | MI cannot use delegated (`Scope`) permissions | Switch to application (`Role`) permission |
| Bursts of 429 with no graceful degradation | Client ignores `Retry-After` | Use Graph SDK (handles automatically), or implement `Retry-After`-aware backoff |
| Sudden token-size or token-validation failures | App registration's `groupMembershipClaims: 'All'` causes massive tokens | Switch to `SecurityGroup` or `None` (see [`entra-app-registration`](../entra-app-registration/SKILL.md)) |

## References

- [Graph auth concepts](https://learn.microsoft.com/graph/auth/auth-concepts)
- [Permissions overview](https://learn.microsoft.com/graph/permissions-overview)
- [Permissions reference](https://learn.microsoft.com/graph/permissions-reference)
- [Assign app role to a managed identity](https://learn.microsoft.com/entra/identity/managed-identities-azure-resources/how-to-assign-app-role-managed-identity)
- [App Service: access Graph as app](https://learn.microsoft.com/azure/app-service/scenario-secure-app-access-microsoft-graph-as-app)
- [Throttling](https://learn.microsoft.com/graph/throttling)
- [Throttling limits](https://learn.microsoft.com/graph/throttling-limits)
- [Microsoft Graph Bicep reference](https://learn.microsoft.com/graph/templates/reference/overview)
