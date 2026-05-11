---
name: azure-machine-learning
description: >
  Provision an Azure Machine Learning workspace with system-assigned MI,
  the four required dependencies (Storage, Key Vault, App Insights, ACR
  — same subscription + region), `publicNetworkAccess: Disabled` with
  private endpoints to `privatelink.api.azureml.ms` and
  `privatelink.notebooks.azure.net`, HBI flag for compliance, managed
  VNet for outbound isolation, and serverless compute for jobs.
version: 0.1.0
azure_services:
  - Microsoft.MachineLearningServices/workspaces
  - Microsoft.MachineLearningServices/workspaces/computes
  - Microsoft.MachineLearningServices/workspaces/onlineEndpoints
tags:
  - ai-ml
  - machine-learning
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/machine-learning/concept-workspace
  - https://learn.microsoft.com/azure/machine-learning/how-to-configure-private-link
  - https://learn.microsoft.com/azure/machine-learning/how-to-secure-workspace-vnet
  - https://learn.microsoft.com/azure/machine-learning/concept-hub-workspace
  - https://learn.microsoft.com/azure/machine-learning/how-to-managed-network
  - https://learn.microsoft.com/azure/machine-learning/concept-compute-target
  - https://learn.microsoft.com/azure/machine-learning/how-to-use-serverless-compute
  - https://learn.microsoft.com/azure/machine-learning/how-to-authenticate-online-endpoint
  - https://learn.microsoft.com/azure/machine-learning/concept-data-encryption
  - https://learn.microsoft.com/azure/machine-learning/how-to-create-attach-compute-cluster
  - https://learn.microsoft.com/rest/api/azureml/workspaces/create-or-update
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2026-03-01"
last_reviewed: 2026-05-11
---

# Azure Machine Learning (workspace + compute, secure baseline)

## When to use this skill

- The user is doing classic ML (training, hyperparameter sweep, MLOps).
- The user wants managed online endpoints with autoscale + traffic split.
- The user is wiring Responsible AI dashboards / model monitoring.

## When NOT to use this skill

- The user just wants to call an LLM — see
  [`azure-openai-service`](../azure-openai-service/SKILL.md).
- The user wants the new Foundry agent surface or hub-based RAG —
  see [`azure-ai-foundry`](../azure-ai-foundry/SKILL.md).

## Prerequisites & version pinning

- `az extension add --name ml` (CLI v2). **CLI v1 (`azure-cli-ml`) ended September 30, 2025.**
- Python SDK: `azure-ai-ml` (v2). **SDK v1 deprecated March 31, 2025; end of support June 30, 2026.**
- The four dependencies (Storage, Key Vault, App Insights, ACR) **must
  be in the same subscription and same region** as the workspace.

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| `identity.type` | `'SystemAssigned'` | Default. Used to pull from ACR, write to Storage, fetch secrets from KV. |
| `properties.publicNetworkAccess` | `'Disabled'` | Pair with PEs (see below). |
| `properties.hbiWorkspace` | `true` for compliance / regulated workloads | Encrypts OS+temp disks, restricts diagnostic data, enables IP filtering on Batch pools. **Immutable after creation.** |
| Dependency placement | same subscription + region as the workspace | Cross-subscription requires the workspace's RP to be registered in the dependency subscription. Cross-region not supported. |
| ACR SKU | **Premium** when behind a VNet | Other SKUs don't support private link. |
| App Insights private link | **not supported** | App Insights cannot be placed behind a PE. The other three dependencies can. |
| Private endpoints | **two** PEs on the workspace: `groupId: amlworkspace` (DNS zones `privatelink.api.azureml.ms` + `privatelink.notebooks.azure.net`) | Studio and SDK both rely on private DNS. |
| `properties.managedNetwork.isolationMode` | `'AllowOnlyApprovedOutbound'` for strict; `'AllowInternetOutbound'` for typical prod | `Disabled` = no managed VNet. |
| `properties.imageBuildCompute` | a CPU compute cluster name | **Required when both workspace and ACR are behind PEs** — serverless image builds don't work in that combo. |
| Compute cluster `min_instances` | `0` | Idle = $0; first job has cold-start. |
| Compute cluster identity | system or user-assigned MI | Avoids stored credentials. |
| Online endpoint `auth_mode` | `'aad_token'` for managed online endpoints | Entra-only. **`aad_token` is not supported on Kubernetes endpoints** — use `key` or `aml_token` there. |
| Serverless compute identity | user credential passthrough or **user-assigned MI** | **System-assigned MI is not supported for serverless jobs.** |

## Recipe — Azure CLI (v2 only)

```bash
RG=rg-aml-prod
LOC=eastus
WS=mlw-app-prod
SA=stmlprod$RANDOM
KV=kv-mlw-prod
AI=appi-mlw-prod
ACR=acrmlwprod

az extension add --name ml --upgrade
az group create -n "$RG" -l "$LOC"

# 1. Dependencies (same sub + region; ACR Premium for private link)
az storage account create -g "$RG" -n "$SA" -l "$LOC" --sku Standard_LRS --allow-blob-public-access false
az keyvault create -g "$RG" -n "$KV" -l "$LOC" --enable-rbac-authorization true --enable-purge-protection true
az monitor app-insights component create -g "$RG" -a "$AI" -l "$LOC" --workspace <law-id>
az acr create -g "$RG" -n "$ACR" --sku Premium --admin-enabled false --public-network-enabled false

# 2. Workspace YAML (workspace.yml)
cat > workspace.yml <<EOF
\$schema: https://azuremlschemas.azureedge.net/latest/workspace.schema.json
name: $WS
location: $LOC
storage_account: $(az storage account show -g $RG -n $SA --query id -o tsv)
key_vault: $(az keyvault show -g $RG -n $KV --query id -o tsv)
container_registry: $(az acr show -g $RG -n $ACR --query id -o tsv)
application_insights: $(az monitor app-insights component show -g $RG -a $AI --query id -o tsv)
hbi_workspace: true
public_network_access: Disabled
managed_network:
  isolation_mode: AllowInternetOutbound
EOF

az ml workspace create -g "$RG" -f workspace.yml

# 3. Image-build cluster (required when ACR is also private)
az ml compute create -g "$RG" -w "$WS" --name cpu-build --type AmlCompute \
  --min-instances 0 --max-instances 2 --size Standard_DS3_v2 --idle-time-before-scale-down 300
az ml workspace update -g "$RG" -n "$WS" --image-build-compute cpu-build

# 4. Grant the workspace MI AcrPull on the ACR (needed for online endpoint deploys)
WS_PRINCIPAL=$(az ml workspace show -g "$RG" -n "$WS" --query identity.principal_id -o tsv)
ACR_ID=$(az acr show -g "$RG" -n "$ACR" --query id -o tsv)
az role assignment create \
  --assignee-object-id "$WS_PRINCIPAL" --assignee-principal-type ServicePrincipal \
  --role AcrPull --scope "$ACR_ID"

# 5. Two private endpoints (groupId = amlworkspace)
WS_ID=$(az ml workspace show -g "$RG" -n "$WS" --query id -o tsv)
az network private-endpoint create -g "$RG" -n "pe-$WS" \
  --vnet-name vnet-app --subnet snet-pe \
  --private-connection-resource-id "$WS_ID" \
  --connection-name "pec-$WS" --group-id amlworkspace
# Then create + link both DNS zones (privatelink.api.azureml.ms, privatelink.notebooks.azure.net)
```

## Recipe — Bicep

```bicep
param workspaceName string
param location string = resourceGroup().location
param storageAccountId string
param keyVaultId string
param appInsightsId string
param containerRegistryId string

resource ws 'Microsoft.MachineLearningServices/workspaces@2026-03-01' = {
  name: workspaceName
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    storageAccount: storageAccountId
    keyVault: keyVaultId
    applicationInsights: appInsightsId
    containerRegistry: containerRegistryId
    publicNetworkAccess: 'Disabled'
    hbiWorkspace: true                      // immutable
    managedNetwork: { isolationMode: 'AllowInternetOutbound' }
  }
}
```

## Job submission — serverless compute (preferred)

```python
from azure.ai.ml import command, MLClient
from azure.identity import DefaultAzureCredential

ml_client = MLClient(DefaultAzureCredential(), sub_id, rg, workspace_name)

job = command(
    command="python train.py",
    environment="azureml://registries/azureml/environments/sklearn-1.5/labels/latest",
    # NO compute= parameter -> serverless
)
ml_client.create_or_update(job)
```

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| Workspace create fails: dependency error | A dependency is in a different subscription, or the AML RP isn't registered there | Move to same sub, or `az provider register --namespace Microsoft.MachineLearningServices` in the dependency's sub. |
| Workspace create fails: cross-region | Dependencies in different region | All four must be in the workspace's region. |
| SDK / CLI hang against a private workspace | Client isn't on a network with a path to the PE | Bastion / VPN / VM in the VNet / ExpressRoute. |
| Online endpoint deploy fails | Workspace MI lacks `AcrPull` on the linked ACR | Grant `AcrPull` to `ws.identity.principalId`. |
| Compute cluster stuck "resizing 0→0" | RG-level locks on `*-azurebatch-*` resources | Remove the locks. ([Source](https://learn.microsoft.com/azure/machine-learning/how-to-create-attach-compute-cluster)) |
| Image build task fails | Workspace + ACR both private; serverless image build won't work | Set `imageBuildCompute` to a CPU cluster. |
| `aad_token` auth fails on a Kubernetes endpoint | `aad_token` is managed-online-only | Use `key` or `aml_token` for AKS-based endpoints. |
| Hub workspace has no compute clusters | Compute clusters aren't supported on hubs | Use serverless compute. |

## References

- [Workspace concept](https://learn.microsoft.com/azure/machine-learning/concept-workspace)
- [Configure private link](https://learn.microsoft.com/azure/machine-learning/how-to-configure-private-link)
- [Secure workspace VNet](https://learn.microsoft.com/azure/machine-learning/how-to-secure-workspace-vnet)
- [Hub workspace concept](https://learn.microsoft.com/azure/machine-learning/concept-hub-workspace)
- [Managed VNet](https://learn.microsoft.com/azure/machine-learning/how-to-managed-network)
- [Compute targets](https://learn.microsoft.com/azure/machine-learning/concept-compute-target)
- [Serverless compute](https://learn.microsoft.com/azure/machine-learning/how-to-use-serverless-compute)
- [Online endpoint authentication](https://learn.microsoft.com/azure/machine-learning/how-to-authenticate-online-endpoint)
- [Data encryption / HBI](https://learn.microsoft.com/azure/machine-learning/concept-data-encryption)
- [Compute cluster](https://learn.microsoft.com/azure/machine-learning/how-to-create-attach-compute-cluster)
- [Workspace REST API](https://learn.microsoft.com/rest/api/azureml/workspaces/create-or-update)
