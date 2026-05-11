---
name: azure-managed-identity
description: >
  Use Azure Managed Identity to authenticate workloads to Azure services
  without secrets. Covers system- vs user-assigned identity, attaching to
  App Service / Functions / Container Apps, granting RBAC, and federated
  credentials for GitHub Actions OIDC.
version: 0.1.0
azure_services:
  - Microsoft.ManagedIdentity/userAssignedIdentities
  - Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials
tags:
  - identity
  - security-baseline
  - oidc
sources:
  - https://learn.microsoft.com/entra/identity/managed-identities-azure-resources/overview
  - https://learn.microsoft.com/entra/identity/managed-identities-azure-resources/managed-identity-best-practice-recommendations
  - https://learn.microsoft.com/azure/app-service/overview-managed-identity
  - https://learn.microsoft.com/azure/container-apps/managed-identity
  - https://learn.microsoft.com/entra/workload-id/workload-identity-federation-create-trust-user-assigned-managed-identity
  - https://learn.microsoft.com/cli/azure/identity/federated-credential
  - https://learn.microsoft.com/azure/role-based-access-control/role-assignments-cli
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2023-01-31"
last_reviewed: 2026-05-11
---

# Azure Managed Identity

## When to use this skill

- The user is wiring an Azure-hosted workload (App Service, Function App,
  Container App, AKS pod, VM) to talk to another Azure service.
- The user is putting a connection string or API key in an app setting
  and asks "is this secure?". The answer is "use managed identity".
- The user wants GitHub Actions to deploy to Azure without storing a
  client secret.

## When NOT to use this skill

- Authenticating end users (consumers / employees signing in) — that's
  Microsoft Entra ID app registrations + sign-in flows, not MI.
- Workloads running outside Azure (on-prem, other clouds) — use Entra
  workload identity federation with an external IdP instead, not MI.
- Cosmos DB data-plane access uses native RBAC, not MI directly — see
  `azure-rbac-least-privilege` for the wrinkle.

## Prerequisites

- Azure CLI `>= 2.60.0` (`az --version`).
- Logged in: `az login`.
- The deployment principal needs **Managed Identity Contributor** to
  create user-assigned identities and **Managed Identity Operator** to
  attach them to a resource. Source: [How to manage user-assigned identities](https://learn.microsoft.com/entra/identity/managed-identities-azure-resources/how-manage-user-assigned-managed-identities).

## Secure defaults

| Decision | Default | Why |
| --- | --- | --- |
| **System- vs user-assigned** | **User-assigned** for shared workloads, system-assigned for single-resource one-offs | User-assigned is reusable across resources, survives resource recreation, and avoids Entra ID 429 throttling when many system-assigned identities are created in burst. Source: [best-practice recommendations](https://learn.microsoft.com/entra/identity/managed-identities-azure-resources/managed-identity-best-practice-recommendations). |
| **Federated credential `subject`** | `repo:OWNER/REPO:ref:refs/heads/main` or `repo:OWNER/REPO:environment:NAME` | Subject is matched **exactly** against the OIDC `sub` claim — no wildcards. Scope as narrowly as possible. Source: [Workload ID federation trust](https://learn.microsoft.com/entra/workload-id/workload-identity-federation-create-trust-user-assigned-managed-identity). |
| **Federated credential `audiences`** | `api://AzureADTokenExchange` | This is the `aud` claim Entra ID validates. Don't change unless you know why. Source: [federated-credential CLI](https://learn.microsoft.com/cli/azure/identity/federated-credential). |
| **Federated credential `issuer`** | `https://token.actions.githubusercontent.com` for GitHub Actions | Must match the `iss` claim from the external token issuer. |
| **Role assignment `principalType`** | `'ServicePrincipal'` (Bicep) / `--assignee-principal-type ServicePrincipal` (CLI) | Skips the Entra Graph lookup that races with identity creation and fails with insufficient permissions. Source: [role-assignments-cli](https://learn.microsoft.com/azure/role-based-access-control/role-assignments-cli). |

## System-assigned vs user-assigned (decision table)

| You want... | Pick |
| --- | --- |
| One identity tightly bound to one resource; lifecycle = resource lifecycle | System-assigned |
| One identity shared by many resources (e.g., 5 Function Apps + 1 Container App all reading from the same Storage account) | User-assigned |
| Federated credentials for GitHub Actions / external workload | User-assigned (only user-assigned supports FICs) |
| To avoid creating dozens of identities (Entra ID rate-limits SP creation at scale) | User-assigned |

## Recipe — Azure CLI

```bash
RG=rg-app-prod
LOC=eastus
IDENTITY=id-app-prod
WEBAPP=app-app-prod

# 1. Create a user-assigned identity
az identity create --resource-group "$RG" --location "$LOC" --name "$IDENTITY"

PRINCIPAL_ID=$(az identity show -g "$RG" -n "$IDENTITY" --query principalId -o tsv)
CLIENT_ID=$(az identity show -g "$RG" -n "$IDENTITY" --query clientId -o tsv)
IDENTITY_ID=$(az identity show -g "$RG" -n "$IDENTITY" --query id -o tsv)

# 2a. Attach to an App Service / Function App
az webapp identity assign      -g "$RG" -n "$WEBAPP"  --identities "$IDENTITY_ID"
az functionapp identity assign -g "$RG" -n my-funcapp --identities "$IDENTITY_ID"

# 2b. Attach to a Container App (different flag: --user-assigned, not --identities)
az containerapp identity assign -g "$RG" -n my-containerapp --user-assigned "$IDENTITY_ID"

# 3. Grant the identity an RBAC role on a target resource (Key Vault example)
KV_ID=$(az keyvault show -g "$RG" -n my-kv --query id -o tsv)
az role assignment create \
  --assignee-object-id "$PRINCIPAL_ID" \
  --assignee-principal-type ServicePrincipal \
  --role "Key Vault Secrets User" \
  --scope "$KV_ID"

# 4. Add a federated credential for GitHub Actions on `main`
az identity federated-credential create \
  --name github-actions-main \
  --identity-name "$IDENTITY" \
  --resource-group "$RG" \
  --issuer https://token.actions.githubusercontent.com \
  --subject "repo:my-org/my-repo:ref:refs/heads/main" \
  --audiences api://AzureADTokenExchange
```

> Use `--assignee-object-id ... --assignee-principal-type ServicePrincipal`
> instead of `--assignee` so the CLI doesn't have to call Microsoft Graph
> to look up the principal — this avoids both a permission requirement
> and a race condition right after the identity is created.

## Recipe — Bicep

```bicep
param identityName string
param appName string
param location string = resourceGroup().location

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: identityName
  location: location
}

resource webapp 'Microsoft.Web/sites@2023-01-01' = {
  name: appName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identity.id}': {}
    }
  }
  properties: { /* ... */ }
}

// Grant Key Vault Secrets User to the identity, scoped to a vault
var keyVaultSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'
resource roleAssign 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, identity.id, keyVaultSecretsUserRoleId)
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleId)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// Federated identity credential for GitHub Actions on main
resource fic 'Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials@2023-01-31' = {
  parent: identity
  name: 'github-actions-main'
  properties: {
    issuer: 'https://token.actions.githubusercontent.com'
    subject: 'repo:my-org/my-repo:ref:refs/heads/main'
    audiences: [ 'api://AzureADTokenExchange' ]
  }
}
```

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| 403 from Key Vault / Storage seconds after `az role assignment create` | RBAC propagation — documented as "up to 5 minutes," 10–30 min observed | Retry with exponential backoff. Don't assume instant. ([Source](https://learn.microsoft.com/azure/role-based-access-control/best-practices)) |
| Permission change (e.g., add to Entra group) doesn't take effect for hours | Managed identity tokens are cached **per resource URI for up to 24 h**; cannot be force-refreshed | Assign roles **directly to the identity**, not via group membership, when latency matters. ([Source](https://learn.microsoft.com/azure/app-service/overview-managed-identity)) |
| `az identity create` returns HTTP 429 in a deployment loop | Entra ID rate-limits service-principal creation; system-assigned creates a new SP per resource | Switch to **user-assigned** and share. ([Source](https://learn.microsoft.com/entra/identity/managed-identities-azure-resources/managed-identity-best-practice-recommendations)) |
| `AuthorizationFailed` on `Microsoft.ManagedIdentity/userAssignedIdentities/*/assign/action` | Caller lacks **Managed Identity Operator** role on the identity | Grant `Managed Identity Operator` to the deployment principal at the identity's scope. |
| GitHub Actions OIDC: `AADSTS70021: No matching federated identity record found` | The `subject` in the FIC doesn't exactly match the `sub` in the GitHub token (off-by-one on branch name, environment vs ref, missing `refs/heads/`) | Print the token's `sub` claim from the workflow (decode the JWT), copy it verbatim into the FIC's `--subject`. No wildcards supported. |
| App Service slot swap leaves stale identity behind | System-assigned identity is **per-slot** | Configure identity on every slot explicitly; verify `az webapp identity show --slot production` after swap. |

## References

- [Managed identities for Azure resources — overview](https://learn.microsoft.com/entra/identity/managed-identities-azure-resources/overview)
- [Best-practice recommendations](https://learn.microsoft.com/entra/identity/managed-identities-azure-resources/managed-identity-best-practice-recommendations)
- [App Service / Functions managed identity](https://learn.microsoft.com/azure/app-service/overview-managed-identity)
- [Container Apps managed identity](https://learn.microsoft.com/azure/container-apps/managed-identity)
- [Workload identity federation: trust on a user-assigned MI](https://learn.microsoft.com/entra/workload-id/workload-identity-federation-create-trust-user-assigned-managed-identity)
- [`az identity federated-credential` reference](https://learn.microsoft.com/cli/azure/identity/federated-credential)
- [`az role assignment` reference](https://learn.microsoft.com/azure/role-based-access-control/role-assignments-cli)
