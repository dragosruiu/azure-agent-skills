---
name: azure-verified-modules
description: >
  Consume Microsoft's Azure Verified Modules (AVM) for Bicep — the
  current standard for reusable Azure IaC. Covers the
  `br/public:avm/res/...` and `br/public:avm/ptn/...` path syntax,
  Resource vs Pattern modules, version pinning at semver, and what
  defaults AVM sets vs what you still must configure.
version: 0.1.0
azure_services:
  - Microsoft.Resources/deployments
tags:
  - infrastructure-as-code
  - bicep
  - avm
sources:
  - https://azure.github.io/Azure-Verified-Modules/
  - https://azure.github.io/Azure-Verified-Modules/indexes/bicep/
  - https://azure.github.io/Azure-Verified-Modules/specs/shared/module-classifications/
  - https://azure.github.io/Azure-Verified-Modules/resources/faq/
  - https://learn.microsoft.com/azure/azure-resource-manager/bicep/modules
validated_with:
  az_cli: ">=2.60.0"
  api_version: "n/a (module-driven)"
last_reviewed: 2026-05-11
---

# Azure Verified Modules (Bicep)

## When to use this skill

- The user is writing Bicep and there's an AVM module for the resource
  they need.
- The user is migrating away from CARML or hand-rolled wrappers.
- The user wants WAF-aligned defaults (TLS, RBAC) without building them.

## When NOT to use this skill

- The resource type has no AVM module yet — write your own and consider
  proposing one at <https://aka.ms/avm/moduleproposal>.
- You need a property AVM doesn't expose, and forking is too costly —
  write your own thin wrapper.

## Module path syntax

```bicep
// Resource module (single Azure resource + its children)
module storage 'br/public:avm/res/storage/storage-account:0.18.0' = { ... }

// Pattern module (multi-resource solution)
module aiFoundry 'br/public:avm/ptn/ai-ml/ai-foundry:0.1.0' = { ... }
```

`br/public` is a built-in alias for `mcr.microsoft.com/bicep`. The full
form `br:mcr.microsoft.com/bicep/avm/res/.../...:<version>` is also
valid. Override the alias in `bicepconfig.json` if you need to.

## Module class picker

| Class | Path prefix | Purpose | Examples |
| --- | --- | --- | --- |
| **RES** (Resource) | `avm/res/` | One Azure resource (and its child / extension resources) | `avm/res/storage/storage-account`, `avm/res/key-vault/vault`, `avm/res/cognitive-services/account` |
| **PTN** (Pattern) | `avm/ptn/` | A multi-resource architectural pattern | `avm/ptn/ai-ml/ai-foundry`, `avm/ptn/aca-lza/hosting-environment`, `avm/ptn/authorization/role-assignment`, `avm/ptn/azd/aks` |
| **UTL** (Utility) | `avm/utl/` | Shared helpers — *emerging, subject to change* | (treat as unstable) |

> **PTN modules deploy multiple resources (sometimes including private
> endpoints, DNS zones, VNets).** Always read the module's README and
> top-level `main.bicep` before using one in production.

## Secure defaults

These aren't security knobs in the usual sense, but they're how to use
AVM safely:

| Decision | Default | Why |
| --- | --- | --- |
| Module path | `br/public:avm/res/...` (RES) or `br/public:avm/ptn/...` (PTN) | The current canonical syntax. CARML paths (`br/public:modules/...`) are deprecated. |
| Version | **always pinned to an exact semver** (`:0.11.3`, not omitted) | Module path requires a tag. Omit at your peril — and AVM modules below `1.0.0` may break in minor versions. |
| RES vs PTN | RES for single-resource wrappers; PTN only after reading what it deploys | PTN modules can spin up many resources (PEs, DNS, VNets) — that surprise will hit your bill or your blast radius. |
| RBAC | use the module's `roleAssignments` array, not a separate `Microsoft.Authorization/roleAssignments` resource | Cleaner; assignment lifecycle ties to the resource. |
| Don't trust AVM for everything | Container Registry → Private Link, API Management → VNet, etc. are **not** set by default | Compose those yourself or use a PTN that includes them. |
| `bicep restore` | run after pulling new modules / switching versions | Cached modules can lag. |

## What AVM sets by default

Verified from the [AVM FAQ](https://azure.github.io/Azure-Verified-Modules/resources/faq/):
AVM applies **high-impact WAF security/reliability defaults only**.
Sample defaults you can rely on:

| Setting | AVM default? |
| --- | --- |
| TLS minimum → latest supported | ✅ |
| Key Vault → RBAC over access policies | ✅ |
| Storage `supportsHttpsTrafficOnly: true`, `minimumTlsVersion: 'TLS1_2'` | ✅ (verified in `avm/res/storage/storage-account`) |
| Container Registry → private link | ❌ (you add the PE module separately) |
| API Management → VNet integration | ❌ (network resources separate) |

In short: AVM does the *boring* security defaults so you can focus on
the wiring. Anything that requires extra resources (PEs, VNets, DNS
zones) is **out of scope** for the resource module — compose them
yourself or use a PTN.

## Version pinning

```bicep
// CORRECT — pin to exact version (recommended for prod)
module kv 'br/public:avm/res/key-vault/vault:0.11.3' = { ... }

// WRONG — module path requires a tag/version; no tag is invalid
```

- Versions follow **semver** (`MAJOR.MINOR.PATCH`).
- AVM modules below `1.0.0` may make breaking changes between **minor**
  versions (per pre-1.0 semver convention).
- Look up the current version per module on the
  [AVM Bicep index](https://azure.github.io/Azure-Verified-Modules/indexes/bicep/).
- `bicep restore` (run automatically by VS Code Bicep) caches modules
  locally. Delete `.bicep` cache + re-run to pick up a new tag.

## Recipe — Bicep (multi-module example)

```bicep
targetScope = 'resourceGroup'

param location string = resourceGroup().location
param keyVaultName string
param storageAccountName string
param principalId string

module kv 'br/public:avm/res/key-vault/vault:0.11.3' = {
  name: 'kvDeploy'
  params: {
    name: keyVaultName
    location: location
    enableRbacAuthorization: true       // AVM default
    enableSoftDelete: true              // AVM default
    softDeleteRetentionInDays: 90       // AVM default
    enablePurgeProtection: true
    publicNetworkAccess: 'Disabled'
    roleAssignments: [
      {
        roleDefinitionIdOrName: 'Key Vault Secrets User'
        principalId: principalId
        principalType: 'ServicePrincipal'
      }
    ]
  }
}

module sa 'br/public:avm/res/storage/storage-account:0.18.0' = {
  name: 'storageDeploy'
  params: {
    name: storageAccountName
    location: location
    skuName: 'Standard_LRS'
    allowBlobPublicAccess: false        // AVM default
    minimumTlsVersion: 'TLS1_2'         // AVM default
    requireInfrastructureEncryption: true
    publicNetworkAccess: 'Disabled'
    networkAcls: { defaultAction: 'Deny', bypass: 'AzureServices' }
  }
}

output keyVaultId string = kv.outputs.resourceId
output storageId  string = sa.outputs.resourceId
```

> Most AVM RES modules expose a `roleAssignments` array — use it instead
> of writing separate `Microsoft.Authorization/roleAssignments` resources.

## Decision: AVM vs writing your own

| Scenario | Recommendation |
| --- | --- |
| AVM RES exists and a recent version exposes the props you need | **Use AVM.** |
| AVM module is stale and missing a recent ARM property | Open a feature request; for now, fork or write a thin wrapper. |
| AVM PTN deploys exactly the architecture you want | **Use PTN** — but verify the resource list first. |
| AVM PTN deploys *almost* what you want | Compose RES modules yourself instead of fighting the PTN. |
| No AVM module exists | Write your own; submit a proposal. |

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| `Module not found` / pulled version yanked | The pinned version was removed from the registry | Pick a current version from the [AVM index](https://azure.github.io/Azure-Verified-Modules/indexes/bicep/); `bicep restore`. |
| PTN module deploys unexpected resources (PEs, DNS zones, VNets) | PTN modules are opinionated multi-resource solutions | Read the module's README and top-level Bicep before using. |
| Module doesn't expose the property you need | RES modules curate their param surface | File a feature request; fork; or wrap with a thin custom module. |
| `bicep restore` returns stale module after upgrading version | Local `.bicep` cache | Delete `.bicep` cache directory (`~/.bicep` or workspace `.bicep`); `bicep restore`. |
| Minor-version bump broke deployment on a `0.x.y` module | Pre-1.0 modules can break in minor versions | Read the changelog; pin to exact version; test in non-prod before rolling forward. |
| Old `br/public:modules/...` path doesn't resolve | CARML is deprecated; modules moved to AVM | Switch to `br/public:avm/res/...` paths from the AVM index. |

## References

- [Azure Verified Modules home](https://azure.github.io/Azure-Verified-Modules/)
- [AVM Bicep module index](https://azure.github.io/Azure-Verified-Modules/indexes/bicep/)
- [Module classifications (RES / PTN / UTL)](https://azure.github.io/Azure-Verified-Modules/specs/shared/module-classifications/)
- [AVM FAQ](https://azure.github.io/Azure-Verified-Modules/resources/faq/)
- [Bicep `module` syntax (public registry)](https://learn.microsoft.com/azure/azure-resource-manager/bicep/modules)
