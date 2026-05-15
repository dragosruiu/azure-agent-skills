---
name: entra-app-registration
description: >
  Author a Microsoft Entra app registration the secure way: single-tenant,
  no client secrets (use Federated Identity Credentials first, certs second),
  least-privileged Microsoft Graph permissions with explicit admin consent,
  exact-match HTTPS redirect URIs, no implicit flow. Covers app object vs
  service principal vs Enterprise Application, FIC subject patterns for
  GitHub Actions / Azure DevOps / AKS, and the GA Microsoft Graph Bicep
  extension (`Microsoft.Graph/applications@v1.0`).
version: 0.1.0
azure_services:
  - Microsoft.Graph/applications
  - Microsoft.Graph/servicePrincipals
  - Microsoft.Graph/applications/federatedIdentityCredentials
tags:
  - identity
  - entra-id
  - app-registration
  - federated-credentials
  - security-baseline
sources:
  - https://learn.microsoft.com/entra/identity-platform/app-objects-and-service-principals
  - https://learn.microsoft.com/entra/identity-platform/security-best-practices-for-app-registration
  - https://learn.microsoft.com/entra/identity-platform/permissions-consent-overview
  - https://learn.microsoft.com/entra/identity-platform/reply-url
  - https://learn.microsoft.com/entra/identity-platform/configurable-token-lifetimes
  - https://learn.microsoft.com/entra/workload-id/workload-identity-federation-create-trust
  - https://learn.microsoft.com/graph/templates/overview-bicep-templates-for-graph
  - https://learn.microsoft.com/graph/templates/reference/overview
  - https://learn.microsoft.com/cli/azure/ad/app
validated_with:
  az_cli: ">=2.73.0"
  api_version: "Microsoft.Graph @ v1.0"
last_reviewed: 2026-05-15
---

# Microsoft Entra app registration

## When to use this skill

- An agent / pipeline / daemon needs a non-user identity to call
  Azure or Microsoft Graph APIs.
- The user wants OIDC (workload identity federation) from GitHub
  Actions / Azure DevOps / AKS / Kubernetes / generic OIDC IdP.
- Multi-tenant SaaS app registration.

## When NOT to use this skill

- The workload runs inside Azure and can use a Managed Identity — see
  [`azure-managed-identity`](../azure-managed-identity/SKILL.md) instead.
- You only need a federated SC for ADO Pipelines — see
  [`azure-devops-oidc`](../../devops/azure-devops-oidc/SKILL.md).

## Object model

```
Microsoft Entra Tenant (home tenant)
└── App Registration            (Application object — global, lives in HOME tenant only)
    ├── appId        = Client ID (assigned by Entra; globally unique GUID)
    ├── id           = Object ID (object identifier in home tenant)
    ├── credentials  = passwordCredentials (secrets) | keyCredentials (certs) | federated
    ├── requiredResourceAccess (declared permissions; drives consent UX)
    └── Service Principal       (auto-created in home tenant on registration)

Each tenant that consumes a multi-tenant app gets its OWN Service Principal:
  Contoso Tenant   → SP (appId = same; objectId = different)
  Fabrikam Tenant  → SP (appId = same; objectId = different)
```

- **App Registrations** blade = the *application object* you author.
- **Enterprise Applications** blade = the *service principal* (SP) — the
  per-tenant instance.
- When you call the Graph API directly to create an application, you must
  also `POST /servicePrincipals` to create the SP. CLI does it for you.

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| Credential type | **Federated Identity Credential (FIC)** first; certificate (in Key Vault) second; client secret last resort | Eliminates secret rotation. Never use client secrets for production workloads. |
| `signInAudience` | `AzureADMyOrg` (single-tenant) | Anything wider only when needed. |
| Implicit grant | `enableAccessTokenIssuance: false`, `enableIdTokenIssuance: false` | Implicit flow is deprecated; use auth-code + PKCE for SPAs. |
| Redirect URIs | HTTPS only, no wildcards, no `localhost` in production | URI is exact-match (case-sensitive). HTTP allowed for `localhost`/`127.0.0.1` dev only. |
| Access token version | `requestedAccessTokenVersion: 2` (v2) | v1 still works but v2 is the modern default. |
| `groupMembershipClaims` | `SecurityGroup` (or `None`) | `All` includes distribution groups → token bloat → 400 errors. |
| App permissions | absolute minimum; declared permissions ≠ granted permissions | Run `az ad app permission admin-consent` to grant. |
| Permission type | prefer **Delegated** for user flows; **Application (Role)** is required for headless workloads | App-only has bigger blast radius. |
| App instance lock | enabled for multi-tenant apps | Prevents tenant admins from modifying sensitive SP properties in their tenant. |
| Max FICs per app | 20 | Hard limit. Plan FIC granularity (one per env, not one per branch) accordingly. |

## Federated Identity Credential subject patterns

`issuer`, `subject`, `audiences` are **case-sensitive** and exact-match.
Wildcards are not supported. The recommended audience is
`api://AzureADTokenExchange`.

| Scenario | Issuer | Subject |
| --- | --- | --- |
| GitHub Actions — Environment | `https://token.actions.githubusercontent.com` | `repo:<org>/<repo>:environment:<name>` |
| GitHub Actions — Branch | `https://token.actions.githubusercontent.com` | `repo:<org>/<repo>:ref:refs/heads/<branch>` |
| GitHub Actions — Tag | `https://token.actions.githubusercontent.com` | `repo:<org>/<repo>:ref:refs/tags/<tag>` |
| GitHub Actions — Pull request | `https://token.actions.githubusercontent.com` | `repo:<org>/<repo>:pull-request` |
| AKS Workload Identity | `<cluster OIDC issuer URL>` (`az aks show ... oidcIssuerProfile.issuerUrl`) | `system:serviceaccount:<ns>:<sa>` |
| Azure DevOps Pipelines | (managed by ADO when you create the WIF service connection — see [`azure-devops-oidc`](../../devops/azure-devops-oidc/SKILL.md)) | (issued automatically) |
| Generic OIDC | the IdP's OIDC discovery URL | the IdP's `sub` claim value |

## Recipe — Azure CLI

```bash
APP_OBJ_ID=$(az ad app create \
  --display-name "my-build-agent" \
  --sign-in-audience AzureADMyOrg \
  --enable-access-token-issuance false \
  --enable-id-token-issuance false \
  --query id -o tsv)

APP_CLIENT_ID=$(az ad app show --id "$APP_OBJ_ID" --query appId -o tsv)

# Create the SP (CLI auto-creates this; required when going via Graph API)
az ad sp create --id "$APP_CLIENT_ID"

# GitHub Actions — Environment-scoped FIC
az ad app federated-credential create --id "$APP_OBJ_ID" --parameters '{
  "name":"github-actions-prod",
  "issuer":"https://token.actions.githubusercontent.com",
  "subject":"repo:my-org/my-repo:environment:Production",
  "audiences":["api://AzureADTokenExchange"]
}'

# AKS workload identity FIC
AKS_OIDC_ISSUER=$(az aks show -g my-rg -n my-cluster \
  --query "oidcIssuerProfile.issuerUrl" -o tsv)
az ad app federated-credential create --id "$APP_OBJ_ID" --parameters "{
  \"name\":\"aks-workload-identity\",
  \"issuer\":\"${AKS_OIDC_ISSUER}\",
  \"subject\":\"system:serviceaccount:my-namespace:my-sa\",
  \"audiences\":[\"api://AzureADTokenExchange\"]
}"

# Declare a Microsoft Graph application permission (User.Read.All)
GRAPH_APP_ID=00000003-0000-0000-c000-000000000000
USER_READ_ALL_ID=$(az ad sp show --id "$GRAPH_APP_ID" \
  --query "appRoles[?value=='User.Read.All'].id" -o tsv)
az ad app permission add --id "$APP_CLIENT_ID" \
  --api "$GRAPH_APP_ID" --api-permissions "${USER_READ_ALL_ID}=Role"

# Grant admin consent (Global Admin or Privileged Role Admin)
az ad app permission admin-consent --id "$APP_CLIENT_ID"

# Optional: restrict group claims to security groups only (avoid token bloat)
az ad app update --id "$APP_OBJ_ID" --set groupMembershipClaims=SecurityGroup
```

> `az ad app permission add` only **declares** the requirement; nothing is
> granted until you run `admin-consent`.

## Recipe — Bicep (Microsoft Graph extension)

The Microsoft Graph Bicep extension is **GA**. Requires Bicep ≥ `0.36.1`
and Azure CLI ≥ `2.73.0`. Configure your `bicepconfig.json` per
[`graph/templates/quickstart-install-bicep-tools`](https://learn.microsoft.com/graph/templates/quickstart-install-bicep-tools).

```bicep
extension graphV1_0

resource buildAgent 'Microsoft.Graph/applications@v1.0' = {
  uniqueName: 'my-build-agent'              // idempotency key (immutable)
  displayName: 'my-build-agent'
  signInAudience: 'AzureADMyOrg'
  groupMembershipClaims: 'SecurityGroup'
  web: {
    implicitGrantSettings: {
      enableAccessTokenIssuance: false
      enableIdTokenIssuance: false
    }
  }
  requiredResourceAccess: [
    {
      resourceAppId: '00000003-0000-0000-c000-000000000000'   // Microsoft Graph
      resourceAccess: [
        {
          // Look up role IDs at runtime via Graph Explorer or `az ad sp show`
          id: '<User.Read.All-role-id>'
          type: 'Role'                                        // Role = app perm; Scope = delegated
        }
      ]
    }
  ]

  resource githubFic 'federatedIdentityCredentials@v1.0' = {
    name: 'github-actions-prod'
    issuer: 'https://token.actions.githubusercontent.com'
    subject: 'repo:my-org/my-repo:environment:Production'
    audiences: [ 'api://AzureADTokenExchange' ]
  }
}

resource sp 'Microsoft.Graph/servicePrincipals@v1.0' = {
  appId: buildAgent.appId
}

output clientId string = buildAgent.appId
output spObjectId string = sp.id
```

> Standard ARM does **not** have a resource type for app registrations.
> The `Microsoft.AzureActiveDirectory/*` namespace is only for Azure AD B2C.
> Use the Microsoft Graph Bicep extension above.

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| App created in the wrong tenant | CLI was logged into the wrong tenant | `az account show --query tenantId` first; `az login --tenant <id>` |
| RBAC role assign fails: "principal not found" | When using Graph API directly, SP creation is a separate step | `az ad sp create --id <appId>` after creating the app |
| API returns 403 even after permission was added | `permission add` declares; doesn't grant | `az ad app permission admin-consent --id <appId>` (Global / Privileged Role Admin) |
| FIC token exchange fails silently | `subject` doesn't exactly match the IdP's `sub` claim (case-sensitive); using `environment:` when the workflow has none | `az ad app federated-credential list --id <objId>` and compare to the actual token's `sub` |
| `AADSTS50011: reply URL does not match` | Redirect URI exact-match mismatch (case, trailing slash, port) | Register the exact URI; remove `localhost` from prod registrations |
| Token too large / 400 errors | `groupMembershipClaims: All` includes distribution groups | Use `SecurityGroup` or `None`; prefer app roles for authorization |
| 21st FIC fails to create | Hard limit of **20 FICs** per app or per UAMI | Delete unused FICs, or split across multiple apps / a UAMI |
| Confused which blade to use | App Registration = the app object; Enterprise Applications = the SP | Modify the app from "App registrations"; assign roles / SSO from "Enterprise applications" |

## Token lifetime

| Setting | Value |
| --- | --- |
| Default access-token lifetime | 60–90 min (random within range) |
| With Continuous Access Evaluation (CAE) | up to 24–28 h, revoked near-real-time on disable / password change |
| Min / max via policy | 10 min / 23 h 59 min 59 s |
| Configuration surface | **Microsoft Graph API / Microsoft Graph PowerShell only** — no portal UI |
| Refresh tokens | not configurable here; use Conditional Access sign-in frequency instead |

## References

- [App objects vs service principals](https://learn.microsoft.com/entra/identity-platform/app-objects-and-service-principals)
- [Security best practices for app registration](https://learn.microsoft.com/entra/identity-platform/security-best-practices-for-app-registration)
- [Permissions and consent overview](https://learn.microsoft.com/entra/identity-platform/permissions-consent-overview)
- [Reply URL rules](https://learn.microsoft.com/entra/identity-platform/reply-url)
- [Configurable token lifetimes](https://learn.microsoft.com/entra/identity-platform/configurable-token-lifetimes)
- [Workload identity federation — create trust](https://learn.microsoft.com/entra/workload-id/workload-identity-federation-create-trust)
- [Microsoft Graph Bicep templates overview](https://learn.microsoft.com/graph/templates/overview-bicep-templates-for-graph)
- [Microsoft Graph Bicep reference](https://learn.microsoft.com/graph/templates/reference/overview)
