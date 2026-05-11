---
name: azure-openai-service
description: >
  Provision Azure OpenAI Service with secure defaults: custom subdomain
  (required for Entra ID), `disableLocalAuth: true`, public network
  access disabled with private endpoint, and a model deployment using
  `Cognitive Services OpenAI User` for inference (NOT `Contributor`).
version: 0.1.0
azure_services:
  - Microsoft.CognitiveServices/accounts
  - Microsoft.CognitiveServices/accounts/deployments
tags:
  - ai-ml
  - openai
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/ai-services/openai/how-to/create-resource
  - https://learn.microsoft.com/azure/ai-services/openai/how-to/managed-identity
  - https://learn.microsoft.com/azure/ai-services/openai/how-to/role-based-access-control
  - https://learn.microsoft.com/azure/ai-services/openai/how-to/deployment-types
  - https://learn.microsoft.com/azure/ai-services/openai/how-to/content-filters
  - https://learn.microsoft.com/azure/ai-services/openai/reference
  - https://learn.microsoft.com/azure/ai-services/disable-local-auth
  - https://learn.microsoft.com/azure/ai-services/openai/how-to/network
  - https://learn.microsoft.com/azure/ai-services/openai/quotas-limits
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2025-06-01"
last_reviewed: 2026-05-11
---

# Azure OpenAI Service (secure baseline)

## When to use this skill

- The user is creating a new Azure OpenAI account to host GPT / embedding
  model deployments for an application.
- The user is migrating from key-based to Entra ID auth.
- The user is hitting `429` and needs the quota / SKU picker.

## When NOT to use this skill

- The user wants the OpenAI public API directly (not Azure-hosted) — out
  of scope.
- The user wants Azure AI Search (RAG retrieval) — see `azure-ai-search`
  (planned).
- The user wants the multi-service Cognitive Services account (vision,
  speech, language) — same Bicep type but `kind: 'CognitiveServices'`.

## Prerequisites

- Azure CLI `>= 2.60.0`.
- Permission to register `Microsoft.CognitiveServices` in the subscription.
- A region where the model + SKU you want is available — check the
  [model availability table](https://learn.microsoft.com/azure/ai-foundry/openai/concepts/models)
  before choosing region.

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| `kind` / `--kind` | `'OpenAI'` | Selects the Azure OpenAI sub-type. |
| `sku.name` / `--sku` | `'S0'` | Only available pricing tier currently. |
| `properties.customSubDomainName` / `--custom-domain` | unique string | **REQUIRED for Entra ID auth**. Cannot be added retroactively without recreating. |
| `properties.disableLocalAuth` | `true` | Disables API-key auth. **No verified `az` CLI flag** — use Bicep, ARM, or `Set-AzCognitiveServicesAccount -DisableLocalAuth $true`. |
| `properties.publicNetworkAccess` | `'Disabled'` | Force private endpoint to `privatelink.openai.azure.com` (and the other AI service zones — see `azure-private-endpoint`). |
| Deployment `sku.name` | `'GlobalStandard'` (highest default quota) or `'Standard'` (single-region for residency) | Avoid `Provisioned` (PTU) unless capacity is committed. |
| Deployment `sku.capacity` | start at `1` and scale | TPM units; 1 unit = model-specific TPM. |
| Inference RBAC | **`Cognitive Services OpenAI User`** for the calling MI | `Cognitive Services Contributor` does **NOT** grant inference permissions — common 401 trap. ([Source](https://learn.microsoft.com/azure/ai-services/openai/how-to/role-based-access-control)) |
| Content filter | Default applies; create a custom policy in Foundry portal for prod | Lowering thresholds requires Microsoft approval (the "Allowed list" / "Modified content filters" form). |
| Inference `api-version` | Pin to `2024-10-21` (current stable GA) — do not default to "latest" | Preview API versions can change without warning. |

## Recipe — Azure CLI

```bash
RG=rg-oai-prod
LOC=eastus
ACCOUNT=oai-app-prod
CUSTOM_DOMAIN=oai-app-prod-$RANDOM
PRINCIPAL_ID=<objectId-of-app-managed-identity>

az group create -n "$RG" -l "$LOC"

# 1. Create the OpenAI account (custom-domain is REQUIRED for Entra auth)
az cognitiveservices account create \
  -g "$RG" -n "$ACCOUNT" -l "$LOC" \
  --kind OpenAI --sku s0 \
  --custom-domain "$CUSTOM_DOMAIN" \
  --yes

# 2. Disable local (key) auth — no verified `az` CLI flag, so use a property update
az resource update \
  -g "$RG" -n "$ACCOUNT" \
  --resource-type Microsoft.CognitiveServices/accounts \
  --set properties.disableLocalAuth=true

# 3. Disable public network access (then add a private endpoint — see azure-private-endpoint)
az resource update \
  -g "$RG" -n "$ACCOUNT" \
  --resource-type Microsoft.CognitiveServices/accounts \
  --set properties.publicNetworkAccess=Disabled

# 4. Grant the calling MI inference rights (NOT Contributor)
ACCOUNT_ID=$(az cognitiveservices account show -g "$RG" -n "$ACCOUNT" --query id -o tsv)
az role assignment create \
  --assignee-object-id "$PRINCIPAL_ID" \
  --assignee-principal-type ServicePrincipal \
  --role "Cognitive Services OpenAI User" --scope "$ACCOUNT_ID"

# 5. Deploy a model (GlobalStandard for highest default quota)
az cognitiveservices account deployment create \
  -g "$RG" -n "$ACCOUNT" \
  --deployment-name gpt-4o \
  --model-name gpt-4o --model-version "2024-11-20" --model-format OpenAI \
  --sku-name GlobalStandard --sku-capacity 1
```

## Recipe — Bicep

```bicep
param name string
param location string = resourceGroup().location
@description('Globally unique custom subdomain (required for Entra ID auth)')
param customSubDomainName string
param modelDeploymentName string = 'gpt-4o'
param modelVersion string = '2024-11-20'
@allowed([ 'GlobalStandard', 'Standard', 'ProvisionedManaged', 'GlobalBatch' ])
param deploymentSkuName string = 'GlobalStandard'
param skuCapacity int = 1

resource openai 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: name
  location: location
  kind: 'OpenAI'
  sku: { name: 'S0' }
  properties: {
    disableLocalAuth: true
    publicNetworkAccess: 'Disabled'
    customSubDomainName: customSubDomainName
  }
}

resource modelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: openai
  name: modelDeploymentName
  sku: { name: deploymentSkuName, capacity: skuCapacity }
  properties: {
    model: { format: 'OpenAI', name: 'gpt-4o', version: modelVersion }
  }
}

output endpoint string = openai.properties.endpoint
```

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| Entra ID auth: 401 with a valid token | `customSubDomainName` not set on the account | **Recreate** the account with `--custom-domain` — cannot be added in place. ([Source](https://learn.microsoft.com/azure/ai-services/openai/how-to/managed-identity)) |
| MI gets 401 on inference even with `Cognitive Services Contributor` | That role manages the resource (keys, deployments) but does **not** include inference data actions | Use `Cognitive Services OpenAI User` (inference) or `Cognitive Services OpenAI Contributor` (inference + deployment mgmt). ([Source](https://learn.microsoft.com/azure/ai-services/openai/how-to/role-based-access-control)) |
| `model-not-found` on deployment create | Model not available in the chosen region/SKU | Check the model + region matrix; pick a different region or model version. |
| 429 on inference | TPM/RPM quota exhausted | Reduce traffic, add deployments in additional regions, or request quota at https://aka.ms/oai/stuquotarequest. |
| Content filter blocks benign content | Default medium-severity threshold | Create a custom content filter in Foundry portal → Guardrails + controls; reduce per-category severity. Disabling categories outright requires Microsoft approval. |
| Preview model deployed to prod stops responding | Preview models can be retired without SLA | Pin to GA model versions in production. |

## References

- [Create an Azure OpenAI resource](https://learn.microsoft.com/azure/ai-services/openai/how-to/create-resource)
- [Use Microsoft Entra ID for authentication](https://learn.microsoft.com/azure/ai-services/openai/how-to/managed-identity)
- [Role-based access control](https://learn.microsoft.com/azure/ai-services/openai/how-to/role-based-access-control)
- [Deployment types](https://learn.microsoft.com/azure/ai-services/openai/how-to/deployment-types)
- [Content filtering](https://learn.microsoft.com/azure/ai-services/openai/how-to/content-filters)
- [API reference (versions)](https://learn.microsoft.com/azure/ai-services/openai/reference)
- [Disable local authentication](https://learn.microsoft.com/azure/ai-services/disable-local-auth)
- [Configure virtual networks (private endpoints)](https://learn.microsoft.com/azure/ai-services/openai/how-to/network)
- [Quotas and limits](https://learn.microsoft.com/azure/ai-services/openai/quotas-limits)
