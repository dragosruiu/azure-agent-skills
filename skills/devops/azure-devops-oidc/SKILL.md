---
name: azure-devops-oidc
description: >
  Wire Azure DevOps Pipelines to deploy to Azure using Workload Identity
  Federation (WIF) — no client secrets stored in the service connection.
  Replaces the legacy service-principal-with-secret pattern; the
  `subject` claim is `sc://<org>/<project>/<service-connection-name>`
  and the issuer is the Entra tenant URL `https://login.microsoftonline.com/<tenant-id>/v2.0`.
version: 0.1.0
azure_services:
  - Microsoft.ManagedIdentity/userAssignedIdentities
  - Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials
tags:
  - devops
  - azure-devops
  - oidc
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/devops/pipelines/library/connect-to-azure
  - https://learn.microsoft.com/azure/devops/pipelines/release/troubleshoot-workload-identity
  - https://learn.microsoft.com/azure/devops/pipelines/release/automate-service-connections
  - https://learn.microsoft.com/azure/devops/pipelines/tasks/reference/azure-cli-v2
  - https://learn.microsoft.com/entra/workload-id/workload-identity-federation
validated_with:
  az_cli: ">=2.30.0"
  api_version: "n/a (ADO pipeline + Entra)"
last_reviewed: 2026-05-11
---

# Azure DevOps Pipelines OIDC (Workload Identity Federation)

## When to use this skill

- The user has an `AzureRM` service connection with a client secret /
  cert and wants to remove the rotation burden.
- New ADO project deploying to Azure — start here.
- Compliance / no-secret-in-vault mandate.

## When NOT to use this skill

- The CI is **GitHub Actions**, not Azure DevOps — see
  [`github-actions-oidc-to-azure`](github-actions-oidc-to-azure/SKILL.md).
- The CI runs entirely outside Microsoft (Jenkins, CircleCI, GitLab) —
  general workload-identity federation patterns apply but the subject
  format differs.

## Decision: managed identity vs app registration

| You want... | Pick |
| --- | --- |
| Simplest setup; no Entra app permissions needed | **User-assigned managed identity** |
| Need Microsoft Graph / Entra app permissions | App registration |

User-assigned MI is preferred unless you specifically need Graph perms.

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| Service connection auth | **`scheme: "WorkloadIdentityFederation"`** (no client secret / cert) | Removes the secret-rotation surface entirely. |
| Underlying principal | **user-assigned managed identity** | Preferred over app registration unless you need Graph perms. |
| FIC `issuer` | `https://login.microsoftonline.com/<tenant-id>/v2.0` (new) — **not** the legacy `https://vstoken.dev.azure.com/<org-id>` | New service connections use the Entra issuer. |
| FIC `subject` | `sc://<org>/<project>/<service-connection-name>` | Matched **exactly** — renaming the project / connection breaks it. |
| Audience | `api://AzureADTokenExchange` | Default; don't change. |
| Service connection creation in automation | `creationMode: Manual` | `Automatic` is **not supported** for non-user principals. |
| Order of operations | service connection first, **then** federated credential (using the issuer/subject the SC returned) | Reverse order doesn't have the right subject. |
| RBAC | scope at the smallest target (RG, not subscription); role = least required (often `Contributor` on one RG) | Same blast-radius hygiene as anywhere else. |
| Pipeline tasks | use **WIF-supported task major versions** (see matrix below) | Older versions silently fall back to the legacy SP flow. |
| `addSpnToEnvironment` | enable when you need the federated token for Terraform / custom tooling | Exposes `$idToken`, `$servicePrincipalId`, `$tenantId` in the script scope. |
| Self-hosted agent Azure CLI | **>= 2.30** | Older versions don't support `--federated-token`. |

## Issuer / subject (the fields that catch people)

> **Important:** new ADO service connections use the **Entra issuer**,
> not the legacy `vstoken` issuer.

| Field | Old (vstoken) | **New (Entra)** |
| --- | --- | --- |
| Issuer | `https://vstoken.dev.azure.com/<organization-id>` | **`https://login.microsoftonline.com/<entra-tenant-id>/v2.0`** |
| Subject | `sc://<org>/<project>/<service-connection-name>` | `sc://<org>/<project>/<service-connection-name>` (same) |

When automating, get the live `workloadIdentityFederationIssuer` and
`workloadIdentityFederationSubject` from the create-service-endpoint
response and use them verbatim. ([Source](https://learn.microsoft.com/azure/devops/pipelines/release/automate-service-connections))

## Recipe — end-to-end CLI (verified)

```bash
TENANT_ID=<your-tenant>
SUBSCRIPTION_ID=<your-sub>
RG=rg-cicd-prod
LOC=eastus
MI=id-ado-deploy

az login --tenant "$TENANT_ID"
az group create -n "$RG" -l "$LOC"

# 1. User-assigned managed identity
az identity create -g "$RG" -n "$MI" -l "$LOC"
CLIENT_ID=$(az identity show -g "$RG" -n "$MI" --query clientId -o tsv)
PRINCIPAL_ID=$(az identity show -g "$RG" -n "$MI" --query principalId -o tsv)

# 2. Create the ADO service connection in Manual mode (required in automation;
#    Automatic mode isn't supported for non-user principals).
cat > sc.json <<EOF
{
  "data": {
    "subscriptionId": "$SUBSCRIPTION_ID",
    "subscriptionName": "<sub display name>",
    "environment": "AzureCloud",
    "scopeLevel": "Subscription",
    "creationMode": "Manual"
  },
  "name": "MyAzureWifConnection",
  "type": "AzureRM",
  "url": "https://management.azure.com/",
  "authorization": {
    "parameters": { "tenantid": "$TENANT_ID", "serviceprincipalid": "$CLIENT_ID" },
    "scheme": "WorkloadIdentityFederation"
  },
  "isShared": false,
  "isReady": false,
  "serviceEndpointProjectReferences": [
    {
      "projectReference": { "id": "<project-id>", "name": "<project-name>" },
      "name": "MyAzureWifConnection"
    }
  ]
}
EOF
az devops service-endpoint create --service-endpoint-configuration ./sc.json
# Note the workloadIdentityFederationIssuer + workloadIdentityFederationSubject in the output

# 3. Federated credential on the MI (after the service connection exists — order matters)
az identity federated-credential create \
  -g "$RG" --identity-name "$MI" --name "fic-ado-${PROJECT}" \
  --issuer "https://login.microsoftonline.com/${TENANT_ID}/v2.0" \
  --subject "<workloadIdentityFederationSubject from step 2>" \
  --audiences "api://AzureADTokenExchange"

# 4. Assign Azure RBAC at the smallest scope
az role assignment create \
  --assignee-object-id "$PRINCIPAL_ID" \
  --assignee-principal-type ServicePrincipal \
  --role Contributor \
  --scope "/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/rg-app-prod"
```

Then in your `azure-pipelines.yml`:

```yaml
trigger: [ main ]

pool: { vmImage: 'ubuntu-latest' }

variables:
  serviceConnection: 'MyAzureWifConnection'

steps:
  - task: AzureCLI@2
    displayName: 'Deploy with WIF'
    inputs:
      azureSubscription: $(serviceConnection)
      scriptType: bash
      scriptLocation: inlineScript
      addSpnToEnvironment: true       # exposes $idToken / $servicePrincipalId / $tenantId
      inlineScript: |
        echo "Tenant: $tenantId"
        az account show
        # Pass the federated token to Terraform if needed:
        #   export ARM_USE_OIDC=true
        #   export ARM_OIDC_TOKEN=$idToken
        #   export ARM_CLIENT_ID=$servicePrincipalId
        #   ...
```

## Converting existing service connections

- **One connection (UI):** Project Settings → Service Connections →
  select connection → **Convert** button. Reversible within **7 days**.
- **Bulk (PowerShell):** the [`connect-to-azure` doc](https://learn.microsoft.com/azure/devops/pipelines/library/connect-to-azure)
  ships a verified script. Requires PowerShell 7.3+, `az` CLI, and that
  the connection was originally created by ADO (manually-created
  connections can't be auto-converted because ADO can't modify its own
  credentials).
- Cross-project connections cannot be converted by the tool — recreate.

## Task-version compatibility (the gotcha matrix)

> Older task major versions silently fall back to the legacy SP flow.

| Task | WIF supported? |
| --- | --- |
| `AzureCLI@2`, `AzureCLI@1` | ✅ |
| `AzurePowerShell@5` (and @2/3/4) | ✅ |
| `AzureWebApp@1` | ✅ |
| `AzureKeyVault@1`, `@2` | ✅ |
| `AzureResourceManagerTemplateDeployment@3` | ✅ |
| `AzureFileCopy@1`–`@5` | ❌ — use **`@6`** |
| `KubernetesManifest@0` | ❌ — use **`@1`** |
| `Kubernetes@0` | ❌ — use **`@1`** |
| `AzureCloudPowerShellDeployment@1` | ❌ — use **`@2`** |
| `Docker@1` (with Docker Registry conn) | ❌ — switch to a Docker Registry service connection |
| Marketplace tasks | ❓ ask the publisher |

Always pin task major versions in YAML to avoid surprise upgrades.

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| `AADSTS70021: No matching federated identity record found` | Project, org, or service connection was renamed; subject no longer matches the FIC | Edit + save the service connection — ADO will regenerate the federated credential. |
| `AADSTS700223` / `AADSTS700238` | Tenant Conditional Access disallows WIF | Tenant admin must allow WIF, or use Managed Identity which has different rules. |
| `AADSTS7000215: Invalid client secret provided` | Connection still uses an expired client secret | Convert the connection to WIF — that's the whole point. |
| `AADSTS700024: Client assertion is not within its valid time range` | App registration token lifetime issue late in a long pipeline | Switch to a managed identity (longer lived). |
| `AADSTS70025: Client application has no configured federated identity credentials` | FIC was never created | Create the FIC on the MI / app reg with the correct subject. |
| `unrecognized arguments: --federated-token` | Self-hosted agent has Azure CLI < 2.30 | Upgrade to Azure CLI 2.30+. |
| `cannot request token: Get … unsupported protocol scheme` | Task version doesn't support WIF | Bump to a WIF-compatible major version (see matrix). |

## Why WIF (the secret-rotation problem it solves)

> *"These credentials [client secrets/certificates] pose a security
> risk and have to be stored securely and rotated regularly. You also
> run the risk of service downtime if the credentials expire."* —
> [Workload identity federation overview](https://learn.microsoft.com/entra/workload-id/workload-identity-federation)

WIF replaces the secret with a trust relationship: ADO mints a
short-lived JWT signed by Entra ID; the MI / app reg has a federated
credential trusting tokens with that issuer + subject; Entra exchanges
the JWT for an Azure access token. **No secret stored, no rotation
needed.**

## References

- [Connect to Azure (service connections)](https://learn.microsoft.com/azure/devops/pipelines/library/connect-to-azure)
- [Troubleshoot WIF (task matrix + error table)](https://learn.microsoft.com/azure/devops/pipelines/release/troubleshoot-workload-identity)
- [Automate service connections](https://learn.microsoft.com/azure/devops/pipelines/release/automate-service-connections)
- [`AzureCLI@2` task reference](https://learn.microsoft.com/azure/devops/pipelines/tasks/reference/azure-cli-v2)
- [Workload identity federation overview](https://learn.microsoft.com/entra/workload-id/workload-identity-federation)
