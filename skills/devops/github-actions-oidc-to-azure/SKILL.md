---
name: github-actions-oidc-to-azure
description: >
  Wire GitHub Actions to deploy to Azure using OIDC federated identity —
  no client secrets stored in GitHub. Uses a user-assigned managed
  identity (preferred) or an Entra app registration with a federated
  credential whose `subject` is scoped to a specific repo + branch /
  environment.
version: 0.1.0
azure_services:
  - Microsoft.ManagedIdentity/userAssignedIdentities
  - Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials
  - Microsoft.Authorization/roleAssignments
tags:
  - devops
  - github-actions
  - oidc
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/developer/github/connect-from-azure-openid-connect
  - https://learn.microsoft.com/entra/workload-id/workload-identity-federation-create-trust
  - https://learn.microsoft.com/entra/workload-id/workload-identity-federation-create-trust-user-assigned-managed-identity
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2023-01-31"
last_reviewed: 2026-05-11
---

# GitHub Actions OIDC → Azure (federated identity)

## When to use this skill

- The user has `AZURE_CREDENTIALS` JSON or a client secret in GitHub
  secrets — replace it with OIDC.
- The user is bootstrapping CI/CD for a new repo against Azure.
- The user wants per-environment pinning (production deploys only from a
  specific branch / GitHub Environment).

## When NOT to use this skill

- The CI runner is **not** GitHub Actions — for Azure DevOps Pipelines
  use the `Workload Identity Federation` service-connection variant
  (planned skill).
- The federated identity needs to be a **system-assigned** MI — that's
  not supported. Use **user-assigned**.

## Prerequisites

- A GitHub repo where you can edit workflow files.
- One of:
  - Permission to create an Entra app registration (needs
    `Application.ReadWrite.OwnedBy` or admin consent), **OR**
  - Permission to create a user-assigned MI (just `Contributor` on a
    resource group).

## Decision: app registration vs user-assigned MI

| You want... | Pick |
| --- | --- |
| Simplest setup; no Entra app permissions needed | **User-assigned managed identity** |
| Federated identity that needs Microsoft Graph / Entra app permissions (e.g., to call Graph API) | **App registration** |
| Multi-tenant scenarios | **App registration** |

[Source](https://learn.microsoft.com/entra/workload-id/workload-identity-federation-create-trust-user-assigned-managed-identity).

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| `issuer` | `https://token.actions.githubusercontent.com` | GitHub's OIDC issuer. Match exactly. |
| `audiences` | `[ 'api://AzureADTokenExchange' ]` (public cloud) / `api://AzureADTokenExchangeUSGov` (USGov) | The `aud` claim Entra validates. |
| `subject` | `repo:OWNER/REPO:ref:refs/heads/main` for branch, `repo:OWNER/REPO:environment:NAME` for environment, `repo:OWNER/REPO:pull_request` for PR jobs, `repo:OWNER/REPO:ref:refs/tags/<tag>` for tag | Matched **exactly** against GitHub's `sub` claim. **No wildcards.** |
| Workflow `permissions` | `id-token: write` + `contents: read` (job-level scope) | `id-token: write` is required to mint the OIDC token. Job-level scoping is safer than workflow-level. |
| `azure/login` action | `@v2` | Current stable. |
| Azure RBAC role | Smallest role at the smallest scope (`Contributor` on the target RG, **not** subscription) | Don't grant subscription-wide Contributor for an app deploy. |
| Federated credentials per identity | ≤ 20 (hard limit) | Plan accordingly; consolidate or use multiple identities. |

## Recipe — Azure CLI (user-assigned MI, recommended)

```bash
RG=rg-cicd-prod
LOC=eastus
MI=id-github-myrepo
GH_OWNER=my-org
GH_REPO=my-repo

az group create -n "$RG" -l "$LOC"

# 1. Create user-assigned MI
az identity create -g "$RG" -n "$MI" -l "$LOC"
CLIENT_ID=$(az identity show -g "$RG" -n "$MI" --query clientId -o tsv)
PRINCIPAL=$(az identity show -g "$RG" -n "$MI" --query principalId -o tsv)
TENANT=$(az account show --query tenantId -o tsv)
SUB=$(az account show --query id -o tsv)

# 2. Federated credentials (one per "subject" pattern you need)
# Branch-based (push to main)
az identity federated-credential create \
  -g "$RG" --identity-name "$MI" --name fic-main \
  --issuer https://token.actions.githubusercontent.com \
  --subject "repo:${GH_OWNER}/${GH_REPO}:ref:refs/heads/main" \
  --audiences api://AzureADTokenExchange

# Environment-based (deploy to GitHub Environment 'production')
az identity federated-credential create \
  -g "$RG" --identity-name "$MI" --name fic-env-production \
  --issuer https://token.actions.githubusercontent.com \
  --subject "repo:${GH_OWNER}/${GH_REPO}:environment:production" \
  --audiences api://AzureADTokenExchange

# Pull-request CI jobs (read-only / what-if)
az identity federated-credential create \
  -g "$RG" --identity-name "$MI" --name fic-pull-request \
  --issuer https://token.actions.githubusercontent.com \
  --subject "repo:${GH_OWNER}/${GH_REPO}:pull_request" \
  --audiences api://AzureADTokenExchange

# 3. Assign RBAC at the deployment target scope (NOT subscription)
APP_RG_ID="/subscriptions/$SUB/resourceGroups/rg-app-prod"
az role assignment create \
  --assignee-object-id "$PRINCIPAL" \
  --assignee-principal-type ServicePrincipal \
  --role Contributor --scope "$APP_RG_ID"

# 4. Add these to the GitHub repo (Settings → Secrets and variables → Actions):
#    AZURE_CLIENT_ID       = $CLIENT_ID
#    AZURE_TENANT_ID       = $TENANT
#    AZURE_SUBSCRIPTION_ID = $SUB
echo "AZURE_CLIENT_ID=$CLIENT_ID"
echo "AZURE_TENANT_ID=$TENANT"
echo "AZURE_SUBSCRIPTION_ID=$SUB"
```

## Recipe — Azure CLI (app registration, alternative)

```bash
APP_ID=$(az ad app create --display-name gha-${GH_REPO} --query appId -o tsv)
az ad sp create --id "$APP_ID"
OBJ_ID=$(az ad app show --id "$APP_ID" --query id -o tsv)

az ad app federated-credential create --id "$OBJ_ID" --parameters '{
  "name": "fic-main",
  "issuer": "https://token.actions.githubusercontent.com",
  "subject": "repo:'"${GH_OWNER}/${GH_REPO}"':ref:refs/heads/main",
  "audiences": ["api://AzureADTokenExchange"]
}'

az role assignment create --assignee "$APP_ID" --role Contributor \
  --scope "/subscriptions/$SUB/resourceGroups/rg-app-prod"
```

## GitHub Actions workflow

```yaml
name: Deploy to Azure
on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: production    # gates the job AND scopes the OIDC `sub` claim
    permissions:
      id-token: write          # REQUIRED: mints the OIDC token
      contents: read

    steps:
      - uses: actions/checkout@v4

      - name: Azure login (OIDC)
        uses: azure/login@v2
        with:
          client-id: ${{ secrets.AZURE_CLIENT_ID }}
          tenant-id: ${{ secrets.AZURE_TENANT_ID }}
          subscription-id: ${{ secrets.AZURE_SUBSCRIPTION_ID }}

      - name: Deploy
        uses: azure/cli@v2
        with:
          azcliversion: latest
          inlineScript: |
            az account show
            # az deployment group create ... etc.
```

> For Azure US Gov, add `environment: AzureUSGovernment` and
> `audience: api://AzureADTokenExchangeUSGov` to the `azure/login` step,
> and make sure your federated credential's `audiences` matches.

## Subject claim cheatsheet

| Trigger | `subject` value |
| --- | --- |
| Push to branch `main` | `repo:OWNER/REPO:ref:refs/heads/main` |
| Tag `v2.1.0` | `repo:OWNER/REPO:ref:refs/tags/v2.1.0` |
| Pull request (any) | `repo:OWNER/REPO:pull_request` |
| GitHub Environment `production` | `repo:OWNER/REPO:environment:production` |

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| `AADSTS70021: No matching federated identity record found` | The `sub` claim from GitHub doesn't exactly match the FIC `subject` | Print the OIDC token's `sub` claim from the workflow (decode the JWT) and copy verbatim into the FIC. No wildcards. ([Source](https://learn.microsoft.com/entra/workload-id/workload-identity-federation-create-trust)) |
| Login works on `push` but fails on `environment`-gated jobs | The `sub` for env jobs is `repo:O/R:environment:NAME`, not `:ref:refs/heads/...` | Create a separate FIC for the environment. |
| OIDC token request fails with `not enough permissions` | Missing `permissions: id-token: write` in the workflow / job | Add it (job-level preferred). |
| Hit the **20-FIC-per-identity limit** | Too many narrowly scoped FICs on one MI/app | Use multiple identities, or consolidate (e.g., one for all branch pushes — but FIC subject doesn't accept wildcards, so this means fewer scopes). |
| Federated credential created on a **system-assigned** MI silently doesn't work | System-assigned MIs don't support FICs | Use a user-assigned MI. ([Source](https://learn.microsoft.com/entra/workload-id/workload-identity-federation-create-trust-user-assigned-managed-identity)) |
| `Contributor` works for everything in CI but feels too broad | It is | Scope to the smallest RG; create separate identities per stage if their permissions differ. |

## References

- [Connect from GitHub Actions to Azure (OpenID Connect)](https://learn.microsoft.com/azure/developer/github/connect-from-azure-openid-connect)
- [Workload identity federation: create trust](https://learn.microsoft.com/entra/workload-id/workload-identity-federation-create-trust)
- [Workload identity federation on a user-assigned MI](https://learn.microsoft.com/entra/workload-id/workload-identity-federation-create-trust-user-assigned-managed-identity)
