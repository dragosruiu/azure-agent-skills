---
name: azure-content-safety
description: >
  Provision Azure AI Content Safety with `disableLocalAuth: true`,
  custom subdomain (required for Entra), private endpoint. Use it for
  text + image moderation across the four harm categories
  (Hate, Sexual, Violence, SelfHarm), plus Prompt Shields for jailbreak
  / prompt-injection detection on LLM input. Pin REST API to
  `2024-09-01`.
version: 0.1.0
azure_services:
  - Microsoft.CognitiveServices/accounts   # kind: ContentSafety
tags:
  - ai-ml
  - moderation
  - safety
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/ai-services/content-safety/overview
  - https://learn.microsoft.com/azure/ai-services/content-safety/concepts/harm-categories
  - https://learn.microsoft.com/azure/ai-services/content-safety/concepts/jailbreak-detection
  - https://learn.microsoft.com/azure/ai-services/content-safety/concepts/groundedness
  - https://learn.microsoft.com/azure/ai-services/content-safety/concepts/protected-material
  - https://learn.microsoft.com/azure/ai-services/content-safety/how-to/use-blocklist
  - https://learn.microsoft.com/azure/ai-services/disable-local-auth
  - https://learn.microsoft.com/azure/templates/microsoft.cognitiveservices/accounts
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2024-10-01"     # ARM
  rest_api: "2024-09-01"        # data plane
last_reviewed: 2026-05-12
---

# Azure AI Content Safety

## When to use this skill

- Moderating user-generated text or images.
- Pre-flighting LLM inputs for jailbreak / prompt-injection attempts
  (Prompt Shields).
- RAG groundedness checks (preview).
- Detecting protected material (copyright / IP) in model output.

## When NOT to use this skill

- Toxicity / safety filtering of Azure OpenAI itself — Azure OpenAI
  already runs Content Safety as its default content filter; you
  configure custom safety policies via Azure AI Studio / Foundry
  rather than calling Content Safety directly.

## Capabilities

| Feature | Status | Notes |
| --- | --- | --- |
| Analyze Text | GA | Four harm categories, severity 0–7 (or trimmed 0/2/4/6) |
| Analyze Image | GA | Four harm categories, severity 0/2/4/6 only |
| Multimodal (image + text) | Preview | Severity 0–7 |
| **Prompt Shields** (jailbreak + indirect attack) | GA | Use on LLM `userPrompt` and on RAG `documents` |
| **Protected material detection** | GA | Identifies copyrighted text / code in outputs |
| **Groundedness detection** | Preview | Checks RAG output against sources |
| Custom categories (rapid + standard) | Preview | Train your own safety category |

## Harm categories (verified)

| Category | API term |
| --- | --- |
| Hate and Fairness | `Hate` |
| Sexual | `Sexual` |
| Violence | `Violence` |
| Self-Harm | `SelfHarm` |

## Rate + input limits

| Feature | F0 (Free) | S0 (Standard) |
| --- | --- | --- |
| Text + Image moderation, Prompt Shields, Protected material | **5 RPS** | **1000 R/10s** |
| Groundedness (preview) | n/a | 50 RPS |
| Multimodal | 5 RPS | 10 RPS |

| Input | Limit |
| --- | --- |
| Analyze Text | 10 K characters |
| Analyze Image | 4 MB; 50×50 to 7200×7200 px; JPEG / PNG / GIF / BMP / TIFF / WEBP |
| Prompt Shields `userPrompt` | 10 K characters |
| Prompt Shields `documents` | up to 5 docs, 10 K chars total |
| Groundedness | sources 55 K chars/call; text+query 7.5 K chars; min query 3 words |
| Protected material | 10 K chars max, **110 chars min** |

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| `kind` | `'ContentSafety'` | The ARM kind for this service. |
| `sku.name` | `'S0'` (Standard) for prod | F0 is heavily rate-limited and lacks groundedness. |
| `properties.customSubDomainName` | required | Same Entra-auth gotcha as Azure OpenAI / Document Intelligence. |
| `properties.disableLocalAuth` | `true` | Force Entra; reject `Ocp-Apim-Subscription-Key`. |
| `identity.type` | `'SystemAssigned'` | For outbound auth (rare for CS, but useful for chained scenarios). |
| `properties.publicNetworkAccess` | `'Disabled'` | Pair with PE to `privatelink.cognitiveservices.azure.com`. |
| `networkAcls.defaultAction` | `'Deny'` | Default-deny ACL. |
| `networkAcls.bypass` | `'AzureServices'` | Lets the AOAI / Foundry pipeline reach Content Safety as a system component. |
| REST `api-version` | `2024-09-01` | Pin it; don't default to "latest". |

## Recipe — Azure CLI

```bash
RG=rg-cs-prod
LOC=eastus
CS=cs-app-prod-$RANDOM

az cognitiveservices account create -g "$RG" -n "$CS" -l "$LOC" \
  --kind ContentSafety --sku S0 \
  --assign-identity \
  --custom-domain "$CS" \
  --yes

az resource update -g "$RG" -n "$CS" \
  --resource-type Microsoft.CognitiveServices/accounts \
  --set properties.disableLocalAuth=true \
        properties.publicNetworkAccess=Disabled

# Grant the calling app's MI access
CS_ID=$(az cognitiveservices account show -g "$RG" -n "$CS" --query id -o tsv)
az role assignment create \
  --assignee-object-id <app-mi-objectid> --assignee-principal-type ServicePrincipal \
  --role "Cognitive Services User" --scope "$CS_ID"

# Private endpoint
az network private-endpoint create -g "$RG" -n "pe-$CS" \
  --vnet-name vnet-app --subnet snet-pe \
  --private-connection-resource-id "$CS_ID" \
  --connection-name "pec-$CS" --group-id account
az network private-dns zone create -g "$RG" -n privatelink.cognitiveservices.azure.com
```

## Recipe — Bicep

```bicep
param csName string
param customSubDomainName string = csName
param location string = resourceGroup().location

resource cs 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: csName
  location: location
  kind: 'ContentSafety'
  identity: { type: 'SystemAssigned' }
  sku: { name: 'S0' }
  properties: {
    customSubDomainName: customSubDomainName
    disableLocalAuth: true
    publicNetworkAccess: 'Disabled'
    networkAcls: { defaultAction: 'Deny', bypass: 'AzureServices' }
  }
}
```

## REST examples (`api-version=2024-09-01`)

**Analyze text**:
```bash
curl -X POST "https://${CS}.cognitiveservices.azure.com/contentsafety/text:analyze?api-version=2024-09-01" \
  -H "Authorization: Bearer $(az account get-access-token --resource https://cognitiveservices.azure.com --query accessToken -o tsv)" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Suspicious user input...",
    "categories": ["Hate","Sexual","Violence","SelfHarm"],
    "outputType": "FourSeverityLevels"
  }'
```

**Prompt Shields** (call before forwarding to your LLM):
```bash
curl -X POST "https://${CS}.cognitiveservices.azure.com/contentsafety/text:shieldPrompt?api-version=2024-09-01" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{ "userPrompt": "<user input>", "documents": [ "<rag chunk>" ] }'
```

A response with `attackDetected: true` on either `userPromptAnalysis` or any `documentsAnalysis` entry → block / sanitize before sending to the LLM.

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| 401 even with a valid Entra token | `customSubDomainName` missing | Recreate with a custom domain — can't be added in place. |
| Prompt Shield rejects benign content | The model is conservative on role-play / instructions-in-text | Tune severity thresholds; consider a custom blocklist or Custom Categories. |
| F0 returns 429 immediately | F0 is 5 RPS hard cap | Move to S0. |
| Image API rejects file | > 4 MB, < 50 px / > 7200 px, or unsupported format | Pre-process before submission. |
| Groundedness call returns "feature not available" | F0 doesn't support groundedness | Use S0. |
| Mixed v3 + v4 client code | Old `2023-04-30-preview` against new endpoints | Pin `api-version=2024-09-01`. |

## References

- [Content Safety overview](https://learn.microsoft.com/azure/ai-services/content-safety/overview)
- [Harm categories](https://learn.microsoft.com/azure/ai-services/content-safety/concepts/harm-categories)
- [Prompt Shields (jailbreak)](https://learn.microsoft.com/azure/ai-services/content-safety/concepts/jailbreak-detection)
- [Groundedness](https://learn.microsoft.com/azure/ai-services/content-safety/concepts/groundedness)
- [Protected material](https://learn.microsoft.com/azure/ai-services/content-safety/concepts/protected-material)
- [Use a blocklist](https://learn.microsoft.com/azure/ai-services/content-safety/how-to/use-blocklist)
- [Disable local authentication](https://learn.microsoft.com/azure/ai-services/disable-local-auth)
- [`Microsoft.CognitiveServices/accounts` template](https://learn.microsoft.com/azure/templates/microsoft.cognitiveservices/accounts)
