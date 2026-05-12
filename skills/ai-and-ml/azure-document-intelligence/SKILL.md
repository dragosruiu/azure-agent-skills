---
name: azure-document-intelligence
description: >
  Provision Azure AI Document Intelligence (formerly Form Recognizer)
  with `disableLocalAuth: true`, custom subdomain (required for Entra
  ID), private endpoint to `privatelink.cognitiveservices.azure.com`.
  Use the **new** SDK packages (`azure-ai-documentintelligence`,
  `Azure.AI.DocumentIntelligence`, `@azure-rest/ai-document-intelligence`)
  against REST API `2024-11-30` (v4.0). The legacy `azure-ai-formrecognizer`
  packages are deprecated.
version: 0.1.0
azure_services:
  - Microsoft.CognitiveServices/accounts   # kind: FormRecognizer (unchanged after rebrand)
tags:
  - ai-ml
  - document-ai
  - ocr
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/ai-services/document-intelligence/overview
  - https://learn.microsoft.com/azure/ai-services/document-intelligence/quickstarts/get-started-sdks-rest-api
  - https://learn.microsoft.com/azure/ai-services/document-intelligence/sdk-overview-v4-0
  - https://learn.microsoft.com/azure/ai-services/document-intelligence/concept-model-overview
  - https://learn.microsoft.com/azure/ai-services/disable-local-auth
  - https://learn.microsoft.com/azure/ai-services/cognitive-services-virtual-networks
  - https://learn.microsoft.com/azure/templates/microsoft.cognitiveservices/accounts
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2024-10-01"
last_reviewed: 2026-05-12
---

# Azure AI Document Intelligence (formerly Form Recognizer)

## When to use this skill

- The user wants to extract structured data from PDFs / scans / images
  (invoices, receipts, contracts, IDs, tax forms).
- The user wants to train a custom model on their own document layouts.

## When NOT to use this skill

- The user wants free-text language understanding without document
  layout — see Azure AI Language services.
- The user wants generic image understanding (objects, scenes) — see
  Azure AI Vision (separate `kind: 'ComputerVision'` resource).

## Naming + SDK migration (the most-bitten gotcha)

- **Service rebrand:** Form Recognizer → **Azure AI Document Intelligence**
  (part of "Foundry Tools").
- The Bicep `kind` is **still `FormRecognizer`** — the ARM resource
  type didn't change.
- **Use the NEW SDK packages**; the old ones are deprecated.

| Language | New (use this) | Old (deprecated) |
| --- | --- | --- |
| .NET | `Azure.AI.DocumentIntelligence` v1.0+ | `Azure.AI.FormRecognizer` 4.x |
| Java | `azure-ai-documentintelligence` v1.0+ | `azure-ai-formrecognizer` |
| JS/TS | `@azure-rest/ai-document-intelligence` v1.0+ | `@azure/ai-form-recognizer` |
| Python | `azure-ai-documentintelligence` v1.0+ | `azure-ai-formrecognizer` |

The new packages target REST API **`2024-11-30`** (v4.0 GA). The old
packages target `2023-07-31` (v3.1).

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| `kind` | `'FormRecognizer'` | The ARM kind hasn't changed despite the rebrand. |
| `sku.name` | `'S0'` for prod; `'F0'` only for tinkering | Free tier has tight limits. |
| `properties.customSubDomainName` | unique | **Required** for Entra ID auth. Cannot be added later without recreating. |
| `properties.disableLocalAuth` | `true` | Disables key auth; forces Entra. |
| `identity.type` | `'SystemAssigned'` | For Storage / KV access during custom-model training. |
| `properties.publicNetworkAccess` | `'Disabled'` | Pair with PE to `privatelink.cognitiveservices.azure.com`. |
| `properties.networkAcls.defaultAction` | `'Deny'` | Default-deny network ACL. |
| `properties.networkAcls.bypass` | `'AzureServices'` | Lets Document Intelligence Studio reach the resource. |
| RBAC | `Cognitive Services User` for callers; `Storage Blob Data Reader/Contributor` for the DI MI on training data Storage | Studio needs Contributor on Storage to label. |
| REST API version | pin to **`2024-11-30`** (v4.0) | Don't drift to "latest". |

## Recipe — Azure CLI

```bash
RG=rg-docint-prod
LOC=eastus
DI=docint-app-prod-$RANDOM       # used as both name and customSubDomainName

az cognitiveservices account create -g "$RG" -n "$DI" -l "$LOC" \
  --kind FormRecognizer --sku S0 \
  --custom-domain "$DI" \
  --assign-identity \
  --yes

# Disable key auth (no dedicated CLI flag — use az resource update)
az resource update -g "$RG" -n "$DI" \
  --resource-type Microsoft.CognitiveServices/accounts \
  --set properties.disableLocalAuth=true \
        properties.publicNetworkAccess=Disabled

# Grant the calling app's MI inference rights
DI_ID=$(az cognitiveservices account show -g "$RG" -n "$DI" --query id -o tsv)
az role assignment create \
  --assignee-object-id <app-mi-objectid> --assignee-principal-type ServicePrincipal \
  --role "Cognitive Services User" --scope "$DI_ID"

# Grant DI's own MI access to the training Storage account (custom models)
DI_PRINCIPAL=$(az cognitiveservices account show -g "$RG" -n "$DI" --query identity.principalId -o tsv)
SA_ID=$(az storage account show -g "$RG" -n stdocintraining --query id -o tsv)
az role assignment create \
  --assignee-object-id "$DI_PRINCIPAL" --assignee-principal-type ServicePrincipal \
  --role "Storage Blob Data Reader" --scope "$SA_ID"
# Add 'Storage Blob Data Contributor' if Studio needs to write labels back

# Private endpoint (groupId = account)
az network private-endpoint create -g "$RG" -n "pe-$DI" \
  --vnet-name vnet-app --subnet snet-pe \
  --private-connection-resource-id "$DI_ID" \
  --connection-name "pec-$DI" --group-id account
az network private-dns zone create -g "$RG" -n privatelink.cognitiveservices.azure.com
# (link zone + create DNS zone group on the PE)
```

## Recipe — Bicep

```bicep
param diName string
param customSubDomainName string = diName
param location string = resourceGroup().location

resource docIntel 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: diName
  location: location
  kind: 'FormRecognizer'                    // ARM kind unchanged after rebrand
  identity: { type: 'SystemAssigned' }
  sku: { name: 'S0' }
  properties: {
    customSubDomainName: customSubDomainName
    disableLocalAuth: true
    publicNetworkAccess: 'Disabled'
    networkAcls: { defaultAction: 'Deny', bypass: 'AzureServices' }
  }
}

output endpoint string = docIntel.properties.endpoint
```

## Prebuilt models (v4.0 GA)

`prebuilt-read`, `prebuilt-layout`, `prebuilt-invoice`, `prebuilt-receipt`,
`prebuilt-businessCard`, `prebuilt-idDocument`, `prebuilt-contract`,
`prebuilt-tax.us.w2`, `prebuilt-tax.us.1098`, `prebuilt-tax.us.1099*`,
`prebuilt-healthInsuranceCard.us`. Custom models: template, neural,
classifier.

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| Code throws "method not found" / unknown class | Mixed old + new SDK packages, or used the old SDK against a new endpoint | Use the new SDK package matching `2024-11-30` (v4.0). Remove the old package. |
| 401 with a valid Entra token | `customSubDomainName` not set on the resource | **Recreate** with `--custom-domain` — cannot be added in place. |
| Custom-model training fails with 403 reading Storage | DI MI lacks `Storage Blob Data Reader` on the SA | Grant the role to the DI account's principal (not the calling app's MI). |
| Studio can't write labels back | DI MI has Reader but not Contributor on Storage | Add `Storage Blob Data Contributor` for label/auto-label workflows. |
| Throughput cap on F0 | Free tier rate-limited | Move to S0. |
| Hit a model that doesn't exist | Used old API version syntax against the v4.0 endpoint | Pin `api-version=2024-11-30` and align the model name. |

## References

- [Document Intelligence overview](https://learn.microsoft.com/azure/ai-services/document-intelligence/overview)
- [Get started with SDKs / REST](https://learn.microsoft.com/azure/ai-services/document-intelligence/quickstarts/get-started-sdks-rest-api)
- [SDK overview (v4.0)](https://learn.microsoft.com/azure/ai-services/document-intelligence/sdk-overview-v4-0)
- [Model overview / prebuilt models](https://learn.microsoft.com/azure/ai-services/document-intelligence/concept-model-overview)
- [Disable local authentication (Cognitive Services)](https://learn.microsoft.com/azure/ai-services/disable-local-auth)
- [Cognitive Services + virtual networks](https://learn.microsoft.com/azure/ai-services/cognitive-services-virtual-networks)
- [`Microsoft.CognitiveServices/accounts` template](https://learn.microsoft.com/azure/templates/microsoft.cognitiveservices/accounts)
