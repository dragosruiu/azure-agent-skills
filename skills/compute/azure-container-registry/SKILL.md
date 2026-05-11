---
name: azure-container-registry
description: >
  Provision Azure Container Registry (Premium) with secure defaults:
  admin user disabled, ARM-audience tokens disabled (force ACR-scoped),
  public network access disabled with private endpoint to BOTH
  `privatelink.azurecr.io` and `{region}.data.privatelink.azurecr.io`,
  zone redundancy, soft delete, and AcrPull for managed identities
  pulling images.
version: 0.1.0
azure_services:
  - Microsoft.ContainerRegistry/registries
  - Microsoft.ContainerRegistry/registries/replications
tags:
  - compute
  - containers
  - registry
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/container-registry/container-registry-intro
  - https://learn.microsoft.com/azure/container-registry/container-registry-skus
  - https://learn.microsoft.com/azure/container-registry/container-registry-authentication
  - https://learn.microsoft.com/azure/container-registry/container-registry-disable-authentication-as-arm
  - https://learn.microsoft.com/azure/container-registry/container-registry-private-link
  - https://learn.microsoft.com/azure/container-registry/container-registry-geo-replication
  - https://learn.microsoft.com/azure/container-registry/container-registry-content-trust
  - https://learn.microsoft.com/azure/templates/microsoft.containerregistry/registries
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2025-04-01"
last_reviewed: 2026-05-11
---

# Azure Container Registry (secure baseline)

## When to use this skill

- The user is provisioning a private container registry for AKS,
  Container Apps, App Service, ACI, or local builds.
- The user wants geo-replication or private link to a registry — those
  are Premium-only.
- The user is migrating off Docker Hub for production.

## When NOT to use this skill

- The workload only needs a free public registry — Docker Hub or GHCR
  may be cheaper.
- The user wants to host Helm charts only — OCI artifacts on ACR work
  but check the Helm OCI guide for Helm-specific details.

## Tier picker

| Need | Tier |
| --- | --- |
| Dev / non-prod, < 10 GB, no SLA-critical | Basic |
| Prod, no geo-replication / private link | Standard |
| **Prod with geo-replication / private link / dedicated data endpoints / customer-managed keys / quarantine** | **Premium** |

> **Important:** `disableLocalAuth` is **not** a valid property on
> `Microsoft.ContainerRegistry/registries`. The equivalent ACR controls
> are `adminUserEnabled: false` (default) and the
> `azureADAuthenticationAsArmPolicy` toggle below.

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| `adminUserEnabled` / `--admin-enabled` | `false` (default) | Removes local username + password auth. Easy to leave enabled accidentally — assert it explicitly. |
| `policies.azureADAuthenticationAsArmPolicy.status` / `az acr config authentication-as-arm update --status` | **`'disabled'`** = harden | **Counterintuitive:** `disabled` is the strict setting. It rejects ARM-audience tokens; clients must use ACR-scoped tokens (`https://containerregistry.azure.net/.default`). Default `enabled` accepts both. ([Source](https://learn.microsoft.com/azure/container-registry/container-registry-disable-authentication-as-arm)) |
| `anonymousPullEnabled` | `false` | No anonymous pulls. |
| `publicNetworkAccess` | `'Disabled'` | Pair with PE to **both** `privatelink.azurecr.io` and `{region}.data.privatelink.azurecr.io` (the data endpoint zone). |
| `dataEndpointEnabled` / `--data-endpoint-enabled` | `true` | Premium only. Required when you use private link — gives each region its own data FQDN. |
| `networkRuleSet.defaultAction` | `'Deny'` | Default-deny network ACL. |
| `networkRuleBypassOptions` | `'AzureServices'` | Lets Defender for Cloud reach the private registry to scan it. |
| `zoneRedundancy` | `'Enabled'` | AZ redundancy in supported regions. |
| `policies.softDeletePolicy.status` + `retentionDays` | `'enabled'` + `7` | Recover accidentally deleted manifests. |
| `policies.retentionPolicy.status` + `days` | `'enabled'` + `30` | Auto-clean untagged manifests (Premium, preview). |

> **Docker Content Trust (DCT) is deprecated** — disabled on new
> registries from May 31, 2026 and fully removed March 31, 2028. Use
> Notary Project (OCI referrers) + the `AcrImageSigner` role going
> forward. ([Source](https://learn.microsoft.com/azure/container-registry/container-registry-content-trust))

## RBAC roles

| Role | Use case |
| --- | --- |
| `AcrPull` | Workloads that pull images (AKS kubelet, Container Apps MI, App Service MI). |
| `AcrPush` | CI/CD that pushes images. |
| `AcrDelete` | Cleanup pipelines that delete tags / manifests. |
| `AcrImageSigner` | Sign images via Notary Project. |
| `Container Registry Repository Reader` (ABAC) | Newer per-repo scope where you don't want all repos visible. |

## Recipe — Azure CLI

```bash
RG=rg-acr-prod
LOC=eastus
ACR=acrappprod   # 5–50 chars, alphanumeric only — NO hyphens or underscores

# 1. Premium registry, no admin user, no public network
az acr create -g "$RG" -n "$ACR" --sku Premium \
  --admin-enabled false \
  --public-network-enabled false \
  --zone-redundancy enabled

# 2. Force ACR-scoped tokens (reject ARM-audience tokens) — security hardening
az acr config authentication-as-arm update --registry "$ACR" --status disabled

# 3. Enable dedicated data endpoints (required with private link)
az acr update -n "$ACR" --data-endpoint-enabled true

# 4. Geo-replicate to a second region
az acr replication create --registry "$ACR" --location westus3

# 5. Grant AcrPull to a workload MI (AKS / Container App / Function)
ACR_ID=$(az acr show -n "$ACR" --query id -o tsv)
az role assignment create \
  --assignee-object-id <workload-mi-objectid> \
  --assignee-principal-type ServicePrincipal \
  --role AcrPull --scope "$ACR_ID"

# 6. Build an image inside ACR (no local Docker needed)
az acr build --registry "$ACR" --image myapp:v1 .

# 7. Private endpoint (groupId = registry; data endpoint zone needed too)
az network private-endpoint create -g "$RG" -n "pe-$ACR" \
  --vnet-name vnet-app --subnet snet-pe \
  --private-connection-resource-id "$ACR_ID" \
  --connection-name "pec-$ACR" --group-id registry

az network private-dns zone create -g "$RG" -n privatelink.azurecr.io
az network private-dns zone create -g "$RG" -n "${LOC}.data.privatelink.azurecr.io"
for ZONE in privatelink.azurecr.io "${LOC}.data.privatelink.azurecr.io"; do
  az network private-dns link vnet create -g "$RG" -n "${ZONE}-link" \
    -z "$ZONE" --virtual-network vnet-app --registration-enabled false
done
az network private-endpoint dns-zone-group create -g "$RG" --endpoint-name "pe-$ACR" \
  -n zg-acr \
  --private-dns-zone privatelink.azurecr.io --zone-name registry
```

## Recipe — Bicep

```bicep
param registryName string  // 5-50 chars, alphanumeric only
param location string = resourceGroup().location

resource registry 'Microsoft.ContainerRegistry/registries@2025-04-01' = {
  name: registryName
  location: location
  sku: { name: 'Premium' }
  identity: { type: 'SystemAssigned' }
  properties: {
    adminUserEnabled: false
    anonymousPullEnabled: false
    dataEndpointEnabled: true
    publicNetworkAccess: 'Disabled'
    networkRuleBypassOptions: 'AzureServices'
    networkRuleSet: { defaultAction: 'Deny' }
    zoneRedundancy: 'Enabled'
    policies: {
      azureADAuthenticationAsArmPolicy: {
        status: 'disabled'                  // disabled = REJECT ARM tokens (hardened)
      }
      softDeletePolicy: { retentionDays: 7, status: 'enabled' }
      retentionPolicy:  { days: 30,         status: 'enabled' }   // Premium, preview
      exportPolicy:     { status: 'enabled' }
      quarantinePolicy: { status: 'disabled' }                    // enable to require Defender scan first
    }
  }
}

output loginServer string = registry.properties.loginServer
```

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| Pull from AKS / Container Apps fails 401 after enforcing ACR-scoped tokens | Workload uses an ARM-audience token; registry rejects it | Use `az acr login` (handles scope), or in code use `https://containerregistry.azure.net/.default` as the resource. |
| Admin user enabled in prod by accident | Copy-paste from a dev template | Set `adminUserEnabled: false` explicitly in **every** env Bicep; enforce via Azure Policy. |
| Private-linked registry: client in second region pulls from home region | DNS routes to the home region's PE | Use the **regional endpoint**: `<acr>.{region}.geo.azurecr.io`, or set `--region-endpoint-enabled true`. |
| Defender for Cloud can't scan the private registry | `publicNetworkAccess: 'Disabled'` and no trusted-services bypass | Set `networkRuleBypassOptions: 'AzureServices'`. |
| `docker pull` fails with `remote trust data does not exist` | `DOCKER_CONTENT_TRUST=1` and image isn't DCT-signed | DCT is deprecated. Either unset the env var or migrate signing to Notary Project. |
| Private endpoint created but data plane fails | The data endpoint zone `{region}.data.privatelink.azurecr.io` wasn't created or linked | ACR uses two zones — link the data-endpoint zone too. |

## References

- [ACR overview](https://learn.microsoft.com/azure/container-registry/container-registry-intro)
- [Tier comparison](https://learn.microsoft.com/azure/container-registry/container-registry-skus)
- [Authentication options](https://learn.microsoft.com/azure/container-registry/container-registry-authentication)
- [Disable ARM-audience tokens](https://learn.microsoft.com/azure/container-registry/container-registry-disable-authentication-as-arm)
- [Private Link for ACR](https://learn.microsoft.com/azure/container-registry/container-registry-private-link)
- [Geo-replication](https://learn.microsoft.com/azure/container-registry/container-registry-geo-replication)
- [Content trust (deprecation)](https://learn.microsoft.com/azure/container-registry/container-registry-content-trust)
- [`Microsoft.ContainerRegistry/registries` template](https://learn.microsoft.com/azure/templates/microsoft.containerregistry/registries)
