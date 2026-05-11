---
name: bicep-baseline
description: >
  Bicep repo, parameter-file, and pipeline patterns for Azure IaC. Use
  `.bicepparam` (not parameters.json), gate every PR with `what-if`,
  prefer Azure Verified Modules from `br/public:avm/...`, decorate
  secrets with `@secure()`, and pull secret values via `getSecret()`.
version: 0.1.0
azure_services:
  - Microsoft.Resources/deployments
tags:
  - infrastructure-as-code
  - bicep
sources:
  - https://learn.microsoft.com/azure/azure-resource-manager/bicep/best-practices
  - https://learn.microsoft.com/azure/azure-resource-manager/bicep/parameter-files
  - https://learn.microsoft.com/azure/azure-resource-manager/bicep/bicep-using
  - https://learn.microsoft.com/azure/azure-resource-manager/bicep/modules
  - https://learn.microsoft.com/azure/azure-resource-manager/bicep/deploy-what-if
  - https://learn.microsoft.com/azure/azure-resource-manager/bicep/deploy-to-subscription
  - https://learn.microsoft.com/azure/azure-resource-manager/bicep/deploy-to-resource-group
  - https://learn.microsoft.com/azure/azure-resource-manager/bicep/linter
  - https://learn.microsoft.com/azure/azure-resource-manager/bicep/parameters
  - https://learn.microsoft.com/azure/azure-resource-manager/bicep/bicep-cli
validated_with:
  az_cli: ">=2.76.0"
  api_version: "n/a (Bicep tooling)"
last_reviewed: 2026-05-11
---

# Bicep baseline (repo + pipeline patterns)

## When to use this skill

- The user is bootstrapping a new Azure-only IaC repo.
- The user is migrating from `parameters.json` to `.bicepparam`.
- The user wants a CI workflow that previews changes before applying.

## When NOT to use this skill

- The user has a multi-cloud or non-Azure stack — use Terraform.
- The user is making a one-off ad-hoc resource — `az` CLI is fine.

## Prerequisites

- Azure CLI `>= 2.76.0` for `--validation-level` on what-if; `>= 2.53.0`
  to deploy with `.bicepparam`.
- Bicep CLI `>= 0.22.x` for `.bicepparam` files.
- For `getSecret()` from Key Vault: a vault with the secret already
  populated and the deployment principal granted `Key Vault Secrets User`.

## Repo layout

```
infra/
├── main.bicep                # entry point; targetScope + module orchestration
├── main.dev.bicepparam       # one .bicepparam per environment
├── main.prod.bicepparam
├── bicepconfig.json          # linter rules, registry aliases
└── modules/
    ├── storage.bicep
    ├── keyvault.bicep
    └── network.bicep
```

This layout isn't mandated by Microsoft but is the de facto convention.
The key rule: **one entry point per environment-deployment scope**, with
modules under `modules/` for reuse.

## Secure defaults

| Decision | Default | Why |
| --- | --- | --- |
| Param files | `.bicepparam` (with a `using './main.bicep'` line at top) | Strongly typed, supports expressions, deprecates `parameters.json`. |
| Sensitive params | `@secure()` decorator | Values are never written to deployment history or logs. |
| Sensitive defaults | **No hardcoded default** on `@secure()` params | Linter rule `secure-parameter-default` flags violations. |
| Sensitive outputs | `@secure()` decorator | Same reason. |
| Secrets in `.bicepparam` | `az.getSecret('<sub>', '<rg>', '<vault>', '<secret>')` — never inline | Pulls from Key Vault at deploy time. |
| Public modules | `br/public:avm/res/<type>/<name>:<version>` | Azure Verified Modules — pre-tested, CAF/WAF aligned. ([catalog](https://azure.github.io/Azure-Verified-Modules/indexes/bicep/)) |
| Storage account name | `'${prefix}${uniqueString(resourceGroup().id)}'` | Globally unique, deterministic per RG, ≤ 24 chars if `prefix` ≤ 11. |
| `targetScope` | Explicit at the top of every Bicep file (`'subscription'`, `'resourceGroup'`, `'managementGroup'`, `'tenant'`) | Avoids surprises when modules are deployed cross-scope. |
| What-if before apply | Always run in PR job; in CD use `--confirm-with-what-if` | Catches accidental destroys before they happen. ([Source](https://learn.microsoft.com/azure/azure-resource-manager/bicep/deploy-what-if)) |
| `--validation-level` | `Provider` (default) — full validation incl. RBAC | Use `ProviderNoRbac` only for read-only PR jobs without sufficient role. |

## Recipe — CLI

```bash
# Lint and build (PR gate)
az bicep lint  --file infra/main.bicep
az bicep build --file infra/main.bicep
az bicep build-params --file infra/main.prod.bicepparam

# What-if (PR gate; prints the diff that would be applied)
az deployment group what-if \
  --resource-group rg-app-prod \
  --template-file infra/main.bicep \
  --parameters infra/main.prod.bicepparam \
  --validation-level Provider

# Deploy to a resource group
az deployment group create \
  --name "deploy-$(date +%Y%m%d-%H%M%S)" \
  --resource-group rg-app-prod \
  --template-file infra/main.bicep \
  --parameters infra/main.prod.bicepparam

# Deploy with interactive what-if confirmation (great for human-in-the-loop)
az deployment group create \
  --name "deploy-$(date +%Y%m%d-%H%M%S)" \
  --resource-group rg-app-prod \
  --template-file infra/main.bicep \
  --parameters infra/main.prod.bicepparam \
  --confirm-with-what-if

# Deploy at SUBSCRIPTION scope (requires --location; the deployment itself has a location)
az deployment sub create \
  --name "deploy-sub-$(date +%Y%m%d-%H%M%S)" \
  --location eastus \
  --template-file infra/main.bicep \
  --parameters infra/main.prod.bicepparam

# Deploy at MANAGEMENT GROUP scope
az deployment mg create \
  --name "deploy-mg-$(date +%Y%m%d-%H%M%S)" \
  --management-group-id mg-platform \
  --location eastus \
  --template-file infra/main.bicep \
  --parameters infra/main.prod.bicepparam
```

## Recipe — Bicep templates

```bicep
// ----- main.bicep (subscription-scope orchestrator) -----
targetScope = 'subscription'

@description('Workload name')
param appName string
@allowed([ 'dev', 'test', 'prod' ])
param environment string = 'dev'
param location string = 'eastus'
@secure()
param adminPassword string

var rgName = 'rg-${appName}-${environment}-001'
var tags = {
  application: appName
  environment: environment
  managedBy: 'bicep'
}

resource rg 'Microsoft.Resources/resourceGroups@2025-04-01' = {
  name: rgName
  location: location
  tags: tags
}

module storage 'modules/storage.bicep' = {
  name: 'storageDeploy'
  scope: rg
  params: {
    storagePrefix: appName
    location: location
    tags: tags
  }
}

// Azure Verified Module from the public registry (pin the version)
module kv 'br/public:avm/res/key-vault/vault:0.11.0' = {
  name: 'kvDeploy'
  scope: rg
  params: {
    name: 'kv-${appName}-${environment}'
    location: location
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 90
    enablePurgeProtection: true
    publicNetworkAccess: 'Disabled'
  }
}

output rgId string = rg.id
output storageEndpoint string = storage.outputs.primaryEndpoint
```

```bicep
// ----- modules/storage.bicep (RG-scope; default) -----
@minLength(3) @maxLength(11)
param storagePrefix string
param location string = resourceGroup().location
param tags object = {}

// uniqueString() is deterministic per RG
var storageName = '${storagePrefix}${uniqueString(resourceGroup().id)}'

resource sa 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageName
  location: location
  tags: tags
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    supportsHttpsTrafficOnly: true
  }
}

output primaryEndpoint string = sa.properties.primaryEndpoints.blob
```

```bicep
// ----- main.prod.bicepparam (no JSON — use .bicepparam) -----
using './main.bicep'

param appName     = 'navigator'
param environment = 'prod'
param location    = 'eastus'

// Pull a secret from Key Vault at deploy time — never inline a secret here
param adminPassword = az.getSecret(
  '00000000-0000-0000-0000-000000000000',  // subscriptionId
  'rg-platform-prod',
  'kv-platform-prod',
  'sql-admin-password'
)
```

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| Resources land in the wrong region | Module didn't forward `location`; default kicked in to RG location of a *different* deployment scope | Always pass `location` explicitly to modules; default to `resourceGroup().location` only at the leaf. |
| `Circular dependency detected` | Module A's output is consumed by Module B which Module A depends on | Use the `existing` keyword to look up the resource, or refactor to break the cycle. |
| `.bicepparam`: "no template found" | Missing `using './main.bicep'` line at the top | Add the `using` statement. |
| Subscription deploy: `location is required` | `az deployment sub create` doesn't infer location from a param | Always pass `--location <region>` for sub / mg / tenant scopes. |
| Linter warns `secure-parameter-default` | `@secure()` param has a non-empty hardcoded default | Remove the default or set `''`. |
| What-if shows "Ignore" for nested resources | Hit the 500-nested-template limit or 5-min expansion timeout | Split the deployment into smaller modules / multiple deployments. |
| `--confirm-with-what-if` flag not recognized | Old Azure CLI | Upgrade `az`. |

## References

- [Best practices](https://learn.microsoft.com/azure/azure-resource-manager/bicep/best-practices)
- [Parameter files](https://learn.microsoft.com/azure/azure-resource-manager/bicep/parameter-files)
- [`using` statement](https://learn.microsoft.com/azure/azure-resource-manager/bicep/bicep-using)
- [Modules (incl. Azure Verified Modules)](https://learn.microsoft.com/azure/azure-resource-manager/bicep/modules)
- [`what-if` deployments](https://learn.microsoft.com/azure/azure-resource-manager/bicep/deploy-what-if)
- [Subscription-scope deployments](https://learn.microsoft.com/azure/azure-resource-manager/bicep/deploy-to-subscription)
- [Resource-group-scope deployments](https://learn.microsoft.com/azure/azure-resource-manager/bicep/deploy-to-resource-group)
- [Linter](https://learn.microsoft.com/azure/azure-resource-manager/bicep/linter)
- [Parameters (incl. `@secure()`)](https://learn.microsoft.com/azure/azure-resource-manager/bicep/parameters)
- [Bicep CLI](https://learn.microsoft.com/azure/azure-resource-manager/bicep/bicep-cli)
- [Azure Verified Modules catalog](https://azure.github.io/Azure-Verified-Modules/indexes/bicep/)
