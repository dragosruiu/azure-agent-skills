---
name: azure-ai-foundry
description: >
  Provision Azure AI Foundry — both the **new Foundry** model
  (`Microsoft.CognitiveServices/accounts` kind=`AIServices`, with
  Foundry projects as child resources) and the **classic Hub** model
  (`Microsoft.MachineLearningServices/workspaces` kind=`Hub` with
  hub-based projects). Includes the Agents Standard setup that requires
  Foundry projects, BYO Storage / Cosmos DB / AI Search, and MI-based
  connections.
version: 0.1.0
azure_services:
  - Microsoft.CognitiveServices/accounts          # new Foundry resource (kind=AIServices)
  - Microsoft.CognitiveServices/accounts/projects # Foundry project (child)
  - Microsoft.MachineLearningServices/workspaces  # classic Hub / hub-based project
tags:
  - ai-ml
  - foundry
  - agents
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/foundry/what-is-foundry
  - https://learn.microsoft.com/azure/foundry/concepts/architecture
  - https://learn.microsoft.com/azure/ai-studio/concepts/ai-resources
  - https://learn.microsoft.com/azure/ai-studio/concepts/rbac-ai-studio
  - https://learn.microsoft.com/azure/ai-studio/how-to/create-secure-ai-hub
  - https://learn.microsoft.com/azure/ai-studio/how-to/configure-private-link
  - https://learn.microsoft.com/azure/ai-studio/how-to/connections-add
  - https://learn.microsoft.com/azure/ai-services/agents/overview
  - https://learn.microsoft.com/azure/ai-services/agents/environment-setup
  - https://learn.microsoft.com/azure/ai-studio/how-to/develop/create-hub-project-sdk
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2026-03-01 (workspaces); CognitiveServices version verify per service"
last_reviewed: 2026-05-11
---

# Azure AI Foundry

> **Naming notice — read first.** Microsoft is mid-rebrand and
> documentation uses overlapping names. There are *two distinct
> resource models* both called "Foundry" depending on context:
>
> | Model | ARM resource | Portal toggle |
> | --- | --- | --- |
> | **New Foundry** (current; recommended for new builds) | `Microsoft.CognitiveServices/accounts` (kind=`AIServices`) with `accounts/projects` children | ai.azure.com — "New Foundry" toggle ON |
> | **Foundry (classic)** / Azure AI Studio | `Microsoft.MachineLearningServices/workspaces` (kind=`Hub`) with kind=`project` children | ai.azure.com — toggle OFF |
>
> The new model uses the **CognitiveServices RP**; the classic model
> uses the **MachineLearningServices RP** (i.e., it's an extension of
> the AML workspace). They are separate resource trees.

## When to use which

| Scenario | Pick |
| --- | --- |
| New project; Agents Service Standard setup; new Responses API | **New Foundry** (Foundry resource + Foundry project) |
| Existing AI Studio / Hub investments | Stay on **Hub + hub-based projects** for now; migrate strategically |
| You need compute clusters / classic ML jobs alongside AI | Hub model (compute clusters not on Foundry projects) |
| Multi-tenant project tenancy with shared networking | Hub model |

> Important: **hub-based projects cannot be used with the Standard
> Agent setup.** Standard agents require **Foundry projects**.

## Prerequisites

- For Standard Agent setup: `Azure AI Account Owner` + `Role Based
  Access Administrator` (you'll grant RBAC on Storage, Cosmos, AI Search).
- All Foundry connections / dependencies should be in the **same
  subscription**. Cross-subscription connections for model deployment
  (Azure OpenAI, Foundry) are **not supported**.
- See [`azure-machine-learning`](../azure-machine-learning/SKILL.md) for
  the underlying workspace / private-link plumbing if you choose the
  Hub model.

## Secure defaults — new Foundry resource

| Setting | Value | Why |
| --- | --- | --- |
| `kind` | `'AIServices'` | The Foundry resource kind; child `projects` inherit. |
| `disableLocalAuth` | `true` (where exposed) | Force Entra ID. The CognitiveServices base supports it. |
| `publicNetworkAccess` | `'Disabled'` (after PE) | Pair with PE to the relevant `privatelink.*` zones. |
| Connections to Azure OpenAI / AI Search / Storage / Cosmos | use **MI** (`api_key=None` in the SDK) | Eliminates stored API keys. |
| Foundry project per use case | one Foundry project per workload | Security boundary; data isolation. |

## Secure defaults — Hub (classic)

| Setting | Value | Why |
| --- | --- | --- |
| `kind` | `'Hub'` (workspace) and `'project'` (child workspace) | The classic AI Studio shape. |
| `properties.publicNetworkAccess` | `'Disabled'` | Pair with PEs (same as AML workspace). |
| `properties.managedNetwork.isolationMode` | `'AllowOnlyApprovedOutbound'` (strict) or `'AllowInternetOutbound'` (typical) | Managed VNet isolates outbound. |
| `properties.hbiWorkspace` | `true` for compliance | Same semantics as AML; immutable. |
| Dependencies | Storage, KV in same sub + region; ACR + App Insights optional | Same constraints as AML workspace. |

## Agent setup picker

Verified from [agents/environment-setup](https://learn.microsoft.com/azure/ai-services/agents/environment-setup):

| | Basic | Standard | Standard + BYO VNet |
| --- | --- | --- | --- |
| Agent data | Microsoft-managed | **Your** Azure resources | Your resources |
| Required BYO | — | Storage, Cosmos DB, AI Search | + VNet |
| CMK | ❌ | ✅ | ✅ |
| Private isolation | ❌ | ❌ (public networking) | ✅ |
| Project type | Foundry | **Foundry only** | **Foundry only** |

## Recipe — new Foundry (CLI sketch)

```bash
RG=rg-foundry-prod
LOC=eastus
FOUNDRY=foundry-app-prod
PROJECT=fp-app-prod

# 1. Foundry resource (Cognitive Services account, kind=AIServices)
az cognitiveservices account create -g "$RG" -n "$FOUNDRY" -l "$LOC" \
  --kind AIServices --sku S0 \
  --custom-domain "$FOUNDRY" \
  --yes

# 2. Disable key auth, then disable public network
az resource update -g "$RG" -n "$FOUNDRY" \
  --resource-type Microsoft.CognitiveServices/accounts \
  --set properties.disableLocalAuth=true \
        properties.publicNetworkAccess=Disabled

# 3. Foundry project (child resource) — see Microsoft Foundry docs for the current
#    `az foundry project` or REST API verb; CLI surface is evolving.
#    The portal at ai.azure.com (with "New Foundry" toggle ON) is the most reliable
#    interactive path for project creation today. Verify the CLI verb in your
#    `az --version`.

# 4. For Standard Agent setup: BYO Storage, Cosmos DB, AI Search.
#    Grant the Foundry MI:
#      - Storage Blob Data Contributor on the Storage account
#      - Cosmos DB Built-in Data Contributor on the Cosmos account
#      - Search Index Data Contributor + Search Service Contributor on the search service
```

## Recipe — Hub (classic, Bicep)

```bicep
// Hub workspace (classic AI Hub)
param hubName string
param location string = resourceGroup().location
param storageAccountId string
param keyVaultId string

resource hub 'Microsoft.MachineLearningServices/workspaces@2026-03-01' = {
  name: hubName
  location: location
  kind: 'Hub'
  identity: { type: 'SystemAssigned' }
  properties: {
    storageAccount: storageAccountId
    keyVault: keyVaultId
    publicNetworkAccess: 'Disabled'
    hbiWorkspace: true
    managedNetwork: { isolationMode: 'AllowOnlyApprovedOutbound' }
  }
}

// Hub-based project
resource project 'Microsoft.MachineLearningServices/workspaces@2026-03-01' = {
  name: '${hubName}-project'
  location: location
  kind: 'Project'                        // hub-based project
  identity: { type: 'SystemAssigned' }
  properties: {
    hubResourceId: hub.id
    publicNetworkAccess: 'Disabled'
  }
}
```

## RBAC roles

Verified from [rbac-ai-studio](https://learn.microsoft.com/azure/ai-studio/concepts/rbac-ai-studio):

- `Azure AI Account Owner`
- `Azure AI Project Manager`
- `Azure AI User`
- (Plus the underlying CognitiveServices roles like `Cognitive Services OpenAI User`.)

## Connections (the modern, MI-based way)

```python
from azure.ai.ml.entities import AzureAIServicesConnection

conn = AzureAIServicesConnection(
    name="my-foundry-connection",
    endpoint="https://oai-app-prod.openai.azure.com/",
    api_key=None,                            # None = use MI / Entra
    ai_services_resource_id="/subscriptions/.../accounts/<name>",
)
ml_client.connections.create_or_update(conn)
```

Connection types verified from [connections-add](https://learn.microsoft.com/azure/ai-studio/how-to/connections-add):
Azure OpenAI, AI Search, Storage, Cosmos DB, Bing Search, Foundry
(cross-Foundry), Azure AI Services, custom API key.

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| Hub create fails on dependency | Storage / KV in different subscription or region | Same sub, same region. |
| Standard Agent setup fails / unavailable | You're on a **hub-based project**; Standard Agents need a **Foundry project** | Recreate the project under a Foundry resource (new model). |
| Connection auth fails 401 | Connection was created with `api_key=<value>` instead of `api_key=None` | Recreate with `api_key=None` and grant the Foundry MI the role on the target (e.g., `Cognitive Services OpenAI User` on the AOAI). |
| Cross-subscription model deployment fails | Cross-subscription connections aren't supported for model deployment | Move the model resource to the same sub, or use a connection-via-API-key (not preferred). |
| Hub-based project missing compute clusters | Hub workspaces support compute clusters; **hub-based projects don't expose them** | Use serverless compute, or attach the cluster to the hub. |
| Naming confusion: docs show `kind=Hub` but the portal calls it "Foundry" | The classic model is in mid-rebrand | Confirm by inspecting the resource type: `Microsoft.MachineLearningServices/workspaces` = classic hub; `Microsoft.CognitiveServices/accounts` (kind=AIServices) = new Foundry. |

## References

- [What is Foundry?](https://learn.microsoft.com/azure/foundry/what-is-foundry)
- [Foundry architecture concepts](https://learn.microsoft.com/azure/foundry/concepts/architecture)
- [AI resources (Hub model)](https://learn.microsoft.com/azure/ai-studio/concepts/ai-resources)
- [RBAC roles](https://learn.microsoft.com/azure/ai-studio/concepts/rbac-ai-studio)
- [Create a secure AI Hub](https://learn.microsoft.com/azure/ai-studio/how-to/create-secure-ai-hub)
- [Configure private link](https://learn.microsoft.com/azure/ai-studio/how-to/configure-private-link)
- [Connections (add)](https://learn.microsoft.com/azure/ai-studio/how-to/connections-add)
- [Agents Service overview](https://learn.microsoft.com/azure/ai-services/agents/overview)
- [Agent environment setup](https://learn.microsoft.com/azure/ai-services/agents/environment-setup)
- [Create hub project (SDK)](https://learn.microsoft.com/azure/ai-studio/how-to/develop/create-hub-project-sdk)
