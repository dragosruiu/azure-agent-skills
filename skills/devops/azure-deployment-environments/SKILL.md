---
name: azure-deployment-environments
description: >
  Provision Azure Deployment Environments (ADE) for self-service
  per-developer / per-feature environments from Bicep / ARM catalogs.
  Hierarchy: Dev Center → Project → Environment Type → Environment.
  Catalog manifest is `environment.yaml` (NOT `manifest.yaml`). The
  deployment identity needs **Contributor + User Access Administrator**
  on the target subscription.
version: 0.1.0
azure_services:
  - Microsoft.DevCenter/devcenters
  - Microsoft.DevCenter/projects
  - Microsoft.DevCenter/devcenters/catalogs
  - Microsoft.DevCenter/devcenters/environmentTypes
  - Microsoft.DevCenter/projects/environmentTypes
tags:
  - devops
  - environments
  - self-service
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/deployment-environments/overview-what-is-azure-deployment-environments
  - https://learn.microsoft.com/azure/deployment-environments/concept-environments-key-concepts
  - https://learn.microsoft.com/azure/deployment-environments/concept-environment-yaml
  - https://learn.microsoft.com/azure/deployment-environments/configure-environment-definition
  - https://learn.microsoft.com/azure/deployment-environments/how-to-configure-managed-identity
  - https://learn.microsoft.com/azure/deployment-environments/how-to-configure-catalog
  - https://learn.microsoft.com/azure/deployment-environments/how-to-create-configure-dev-center
validated_with:
  az_cli: ">=2.60.0 (with `devcenter` extension)"
  api_version: "2025-02-01"
last_reviewed: 2026-05-12
---

# Azure Deployment Environments (ADE)

## When to use this skill

- The user wants developers to spin up ephemeral, policy-controlled
  Azure environments without giving them subscription-level access.
- The user wants a catalog of "blessed" Bicep templates that platform
  controls, and devs only choose parameters.
- The user has a "DevBox + ADE" platform-engineering setup.

## When NOT to use this skill

- The user only deploys infra from CI/CD without per-dev environments —
  use [`azure-pipelines-yaml-baseline`](azure-pipelines-yaml-baseline/SKILL.md)
  or GitHub Actions OIDC.
- The user wants Spinnaker / Argo-style continuous deployment — ADE
  isn't that.

## Hierarchy

```
Dev Center
└── Project (one project, one dev center)
    └── Project Environment Type   (= a target subscription)
        └── Environment            (= an RG of resources, deployed from a catalog definition)

Dev Center
└── Catalog (Git repo or Quick Start)
    └── Environment Definition     (folder w/ environment.yaml + main.bicep)
```

## Catalog folder structure

> **The manifest file is `environment.yaml`** (not `manifest.yaml`).

```
/catalog-root/
  /web-app/
    environment.yaml
    main.bicep
  /web-app-with-storage/
    environment.yaml
    main.bicep
```

`environment.yaml`:

```yaml
# yaml-language-server: $schema=https://github.com/Azure/deployment-environments/releases/download/2022-11-11-preview/manifest.schema.json
name: WebApp
version: 1.0.0
summary: Web app environment
description: A Linux App Service plan + web app
runner: Bicep                # ARM | Bicep | <container-image-path>  (Terraform via custom container)
templatePath: main.bicep
parameters:
  - id: location
    name: location
    type: string
    default: eastus
    required: false
  - id: environmentName
    name: environmentName
    type: string
    required: true
```

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| Dev Center identity | `'SystemAssigned'` (simple) or `'UserAssigned'` per-project (best for blast-radius separation) | If both system and user-assigned are attached, **only user-assigned is used**. |
| Deployment identity RBAC on the target sub | `Contributor` **AND** `User Access Administrator` | UA-Admin is required because ADE grants the env creator a role on the new RG. |
| Dev Center MI Key Vault role | `Key Vault Secrets Officer` (RBAC model preferred) | For storing the GitHub PAT used by catalog connections. |
| Catalog `syncType` | `Scheduled` | Auto-pick-up of definition changes; `Manual` is for tightly controlled platforms only. |
| Project-level catalogs | enable both `catalogItemSyncEnableStatus: Enabled` on dev center *and* `catalogItemSyncTypes: [EnvironmentDefinition]` on project | Disabled by default. |
| Pin catalog source | tag (e.g., `branch: refs/tags/v1.2.0`) for prod | Avoids surprise breakage. |
| Cost limits + auto-delete | configure per environment type | Stops abandoned environments. |

## Recipe — Azure CLI

```bash
RG=rg-ade-prod
DC=dc-platform
PROJECT=proj-app-team
TARGET_SUB=<target-subscription-id>

az extension add --name devcenter --upgrade
az group create -n "$RG" -l eastus

# 1. Dev Center with system MI
az devcenter admin devcenter create -g "$RG" -n "$DC"
az devcenter admin devcenter update -g "$RG" -n "$DC" --identity-type SystemAssigned

# 2. Grant Contributor + User Access Administrator on the target sub
DC_MI=$(az devcenter admin devcenter show -g "$RG" -n "$DC" --query identity.principalId -o tsv)
az role assignment create --role Contributor               --assignee "$DC_MI" --scope "/subscriptions/$TARGET_SUB"
az role assignment create --role "User Access Administrator" --assignee "$DC_MI" --scope "/subscriptions/$TARGET_SUB"

# 3. Catalog from GitHub (PAT stored in KV; KV uses RBAC mode)
KV=kv-ade-prod
az keyvault create -g "$RG" -n "$KV" --enable-rbac-authorization true
az role assignment create --role "Key Vault Secrets Officer" --assignee "$DC_MI" \
  --scope "$(az keyvault show -g "$RG" -n "$KV" --query id -o tsv)"
az keyvault secret set --vault-name "$KV" --name GHPAT --value <github-pat>
SECRET_ID=$(az keyvault secret show --vault-name "$KV" --name GHPAT --query id -o tsv)

az devcenter admin catalog create -g "$RG" -d "$DC" -n my-catalog \
  --git-hub path=/Environments branch=main \
            secret-identifier="$SECRET_ID" \
            uri=https://github.com/myorg/my-ade-catalog

# 4. Environment type on the dev center
az devcenter admin environment-type create -g "$RG" -d "$DC" -n sandbox

# 5. Project + project-level env type binding to target subscription
az devcenter admin project create -g "$RG" -d "$DC" -n "$PROJECT"
az devcenter admin project-environment-type create -g "$RG" \
  --project "$PROJECT" -n sandbox \
  --deployment-target-id "/subscriptions/$TARGET_SUB" \
  --status Enabled --identity-type SystemAssigned

# 6. Grant developers `Deployment Environments User` on the project
PROJ_ID=$(az devcenter admin project show -g "$RG" -n "$PROJECT" --query id -o tsv)
az role assignment create --role "Deployment Environments User" \
  --assignee <user-or-group-objectid> --scope "$PROJ_ID"
```

## Recipe — Bicep (Dev Center + Project + Catalog)

```bicep
param devCenterName string
param projectName string
param location string = resourceGroup().location
@secure()
param githubPatSecretId string  // /subscriptions/.../vaults/<kv>/secrets/<secret>/<ver>

resource dc 'Microsoft.DevCenter/devcenters@2025-02-01' = {
  name: devCenterName
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    projectCatalogSettings: { catalogItemSyncEnableStatus: 'Enabled' }
  }
}

resource catalog 'Microsoft.DevCenter/devcenters/catalogs@2025-02-01' = {
  parent: dc
  name: 'my-catalog'
  properties: {
    syncType: 'Scheduled'
    gitHub: {
      uri: 'https://github.com/myorg/my-ade-catalog'
      branch: 'main'
      path: '/Environments'
      secretIdentifier: githubPatSecretId
    }
  }
}

resource envType 'Microsoft.DevCenter/devcenters/environmentTypes@2025-02-01' = {
  parent: dc
  name: 'sandbox'
}

resource project 'Microsoft.DevCenter/projects@2025-02-01' = {
  name: projectName
  location: location
  properties: {
    devCenterId: dc.id
    catalogSettings: { catalogItemSyncTypes: [ 'EnvironmentDefinition' ] }
  }
}

resource projEnvType 'Microsoft.DevCenter/projects/environmentTypes@2025-02-01' = {
  parent: project
  name: 'sandbox'
  identity: { type: 'SystemAssigned' }
  properties: {
    deploymentTargetId: '/subscriptions/<target-sub-id>'
    status: 'Enabled'
  }
}
```

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| Catalog won't sync | The Git connection's PAT is missing / expired, or the dev-center MI lacks `Key Vault Secrets User/Officer` on the KV holding the PAT | Rotate the PAT; ensure the MI has KV access. |
| Environment fails to provision | Project env type's deployment identity lacks `Contributor` (or `Owner`) on the target subscription | Grant the role; remember **also `User Access Administrator`** so ADE can grant the env creator a role on the new RG. |
| User can see project but not the env type | Developer isn't in the Entra group bound to the project env type | Grant `Deployment Environments User` on the project (and ensure they're in any required group). |
| Manifest file ignored | Filename is `manifest.yaml` (the wrong name) | Rename to `environment.yaml`. |
| Terraform definition fails | ADE doesn't have a built-in Terraform `runner` | Use a custom container image as the `runner` value to wrap Terraform. |
| Both system + user MIs attached, only one used | If both, **only user-assigned is used** | Pick one explicitly; don't attach both unless that's intentional. |

## References

- [What is ADE](https://learn.microsoft.com/azure/deployment-environments/overview-what-is-azure-deployment-environments)
- [Key concepts](https://learn.microsoft.com/azure/deployment-environments/concept-environments-key-concepts)
- [environment.yaml schema](https://learn.microsoft.com/azure/deployment-environments/concept-environment-yaml)
- [Configure environment definition](https://learn.microsoft.com/azure/deployment-environments/configure-environment-definition)
- [Configure managed identity](https://learn.microsoft.com/azure/deployment-environments/how-to-configure-managed-identity)
- [Configure catalog](https://learn.microsoft.com/azure/deployment-environments/how-to-configure-catalog)
- [Create + configure dev center](https://learn.microsoft.com/azure/deployment-environments/how-to-create-configure-dev-center)
