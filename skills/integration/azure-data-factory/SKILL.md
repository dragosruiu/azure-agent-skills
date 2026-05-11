---
name: azure-data-factory
description: >
  Provision an Azure Data Factory V2 with system-assigned MI, linked
  services using MI auth (Storage, Key Vault, Cosmos, SQL), Git
  integration with the collaboration / publish-branch pattern, private
  endpoints to `privatelink.datafactory.azure.net` and
  `privatelink.adf.azure.com`, and the npm-based ADF CI/CD pipeline.
version: 0.1.0
azure_services:
  - Microsoft.DataFactory/factories
  - Microsoft.DataFactory/factories/linkedservices
  - Microsoft.DataFactory/factories/datasets
  - Microsoft.DataFactory/factories/pipelines
  - Microsoft.DataFactory/factories/integrationruntimes
tags:
  - integration
  - data-pipelines
  - etl
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/data-factory/introduction
  - https://learn.microsoft.com/azure/data-factory/quickstart-create-data-factory-bicep
  - https://learn.microsoft.com/azure/data-factory/data-factory-service-identity
  - https://learn.microsoft.com/azure/data-factory/data-factory-private-link
  - https://learn.microsoft.com/azure/data-factory/source-control
  - https://learn.microsoft.com/azure/data-factory/continuous-integration-delivery
  - https://learn.microsoft.com/azure/data-factory/create-self-hosted-integration-runtime
  - https://learn.microsoft.com/azure/data-factory/connector-azure-blob-storage
  - https://learn.microsoft.com/azure/data-factory/store-credentials-in-key-vault
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2018-06-01"
last_reviewed: 2026-05-11
---

# Azure Data Factory (V2)

## When to use this skill

- The user is building data movement pipelines (Storage → SQL, on-prem
  → Cloud, file-share ingestion).
- The user needs scheduled or event-triggered ETL with retry/branching.
- The user wants Git-integrated CI/CD for data pipelines.

## When NOT to use this skill

- The workload is bespoke code that just happens to read & write data —
  use Functions / Container Apps with the SDK directly.
- The user wants Synapse Pipelines (essentially ADF inside Synapse) —
  same engine, different surface.

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| `identity.type` | `'SystemAssigned'` | Auto-created via portal / PowerShell. **CLI behavior not explicitly documented — set it explicitly in IaC.** Trusted-services bypass on Storage works only with system MI, not user-assigned. |
| Linked services auth | use **MI everywhere it's supported** — never connection strings | Storage (system MI: `serviceEndpoint` only; user MI adds `credential`), Key Vault, Cosmos DB, SQL DB, Service Bus all support MI. |
| Linked-service secrets | `AzureKeyVaultSecret` reference; ADF MI granted `Key Vault Secrets User` | Centralizes rotation. |
| `publicNetworkAccess` | `'Disabled'` (after PE provisioned) | **Note:** disabling public network access only restricts **Self-hosted IR** traffic; Azure IR / Azure-SSIS IR are unaffected. |
| Private endpoints | **two**: `groupId: dataFactory` (data plane) → zone `privatelink.datafactory.azure.net`; `groupId: portal` (ADF Studio access from VNet) → zone `privatelink.adf.azure.com` | Studio in browser also needs the portal PE. |
| Git integration | mandatory in prod | **Live mode publishes are unauditable.** Always wire to ADO Repos / GitHub. |
| Collaboration branch | `main` | The branch ADF reads when you click *Publish*. |
| Publish branch | `adf_publish` | ADF writes `ARMTemplateForFactory.json` and `linkedTemplates/` here. |
| Cannot publish from a non-collaboration branch | by design | Merge feature branches into `main` first. |
| Self-hosted IR (SHIR) host | Windows Server 2019/2022/2025, **8 GB RAM, 4 vCPU, 80 GB disk minimum**; JRE 11 if reading Parquet/ORC/Avro | Don't install on a domain controller (unsupported). |
| FIPS-enabled SHIR host | tasks fail | Store credentials in KV (preferred) or disable FIPS via registry. |

## Linked-service MI examples (verified JSON shapes)

**Blob Storage with system MI:**
```json
{
  "name": "AzureBlobStorageLinkedService",
  "properties": {
    "type": "AzureBlobStorage",
    "typeProperties": {
      "serviceEndpoint": "https://stappprod.blob.core.windows.net/",
      "accountKind": "StorageV2"
    }
  }
}
```
Required RBAC for the ADF MI: `Storage Blob Data Reader` (source) /
`Storage Blob Data Contributor` (sink).

**Key Vault linked service:**
```json
{
  "name": "AzureKeyVaultLinkedService",
  "properties": {
    "type": "AzureKeyVault",
    "typeProperties": { "baseUrl": "https://kv-app-prod.vault.azure.net" }
  }
}
```
ADF MI needs `Key Vault Secrets User` (RBAC) on the vault.

**Reference a KV secret inside another linked service:**
```json
"password": {
  "type": "AzureKeyVaultSecret",
  "secretName": "db-password",
  "store": {
    "referenceName": "AzureKeyVaultLinkedService",
    "type": "LinkedServiceReference"
  }
}
```

## Recipe — Azure CLI

```bash
RG=rg-adf-prod
LOC=eastus
ADF=adf-app-prod-$RANDOM

az extension add --name datafactory       # the CLI subcommands are an extension
az group create -n "$RG" -l "$LOC"

# 1. Create the factory (set identity explicitly to be safe)
az datafactory create -g "$RG" -n "$ADF" -l "$LOC"

# Confirm system MI is on (post-create check)
az datafactory show -g "$RG" -n "$ADF" --query identity.type -o tsv

# 2. Wire Git integration (Azure DevOps Repos example)
az datafactory configure-factory-repo -l "$LOC" -n "$ADF" \
  --factory-resource-id $(az datafactory show -g "$RG" -n "$ADF" --query id -o tsv) \
  --repo-configuration '{
    "type": "FactoryVSTSConfiguration",
    "accountName": "myorg",
    "projectName": "myproject",
    "repositoryName": "myrepo",
    "collaborationBranch": "main",
    "rootFolder": "/",
    "tenantId": "<tenantId>"
  }'

# 3. Grant the ADF MI Storage Blob Data Reader on the source SA
ADF_PRINCIPAL=$(az datafactory show -g "$RG" -n "$ADF" --query identity.principalId -o tsv)
SA_ID=$(az storage account show -n stsourceprod --query id -o tsv)
az role assignment create \
  --assignee-object-id "$ADF_PRINCIPAL" --assignee-principal-type ServicePrincipal \
  --role "Storage Blob Data Reader" --scope "$SA_ID"

# 4. Private endpoints — TWO of them: dataFactory + portal
ADF_ID=$(az datafactory show -g "$RG" -n "$ADF" --query id -o tsv)
az network private-endpoint create -g "$RG" -n "pe-$ADF-data" \
  --vnet-name vnet-app --subnet snet-pe \
  --private-connection-resource-id "$ADF_ID" \
  --connection-name "pec-$ADF-data" --group-id dataFactory
az network private-endpoint create -g "$RG" -n "pe-$ADF-portal" \
  --vnet-name vnet-app --subnet snet-pe \
  --private-connection-resource-id "$ADF_ID" \
  --connection-name "pec-$ADF-portal" --group-id portal

# (Create + link both DNS zones: privatelink.datafactory.azure.net and privatelink.adf.azure.com)
```

## Recipe — Bicep

```bicep
param factoryName string
param location string = resourceGroup().location

resource adf 'Microsoft.DataFactory/factories@2018-06-01' = {
  name: factoryName
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    publicNetworkAccess: 'Disabled'   // affects Self-hosted IR only
    repoConfiguration: {
      type: 'FactoryVSTSConfiguration'
      accountName: 'myorg'
      projectName: 'myproject'
      repositoryName: 'myrepo'
      collaborationBranch: 'main'
      rootFolder: '/'
      tenantId: subscription().tenantId
    }
  }
}
```

## CI/CD pipeline pattern

The official approach uses an npm package to build deployable templates
from your collaboration-branch JSON:

```yaml
# Excerpt from azure-pipelines.yml
- task: NodeTool@0
  inputs: { versionSpec: '16.x' }

- task: Npm@1
  inputs:
    command: install
    workingDir: 'build'
    customCommand: 'install @microsoft/azure-data-factory-utilities'

- task: Npm@1
  inputs:
    command: custom
    workingDir: 'build'
    customCommand: 'run build export <factoryResourceId> "ArmTemplateOutput"'

# Then deploy ArmTemplateOutput/ARMTemplateForFactory.json with az deployment group create
```

This avoids needing the legacy `adf_publish` branch in newer setups.

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| Pipeline fails reading from a private Storage account | ADF MI lacks `Storage Blob Data Reader` on the SA, or SA blocks public and ADF doesn't have a managed VNet / PE path | Grant the role; add a managed VNet or PE for the SA. |
| Cannot publish from a feature branch | Publish only works from the **collaboration branch** | Merge to `main` (or your collaboration branch) first. |
| Old `adf_publish` partial templates fail | Partial ARM templates were deprecated November 1, 2021 | Switch to `ARMTemplateForFactory.json` + `linkedTemplates/` or the npm-based build. |
| SHIR copy activity slow / OOM | Host VM under-resourced (default-sized VMs often too small) | 8 GB RAM / 4 vCPU minimum; raise for parallel copy. |
| SHIR tasks fail on a FIPS-enabled host | ADF crypto path doesn't work under FIPS | Use Key Vault for credentials (preferred), or disable FIPS via registry. |
| ADF Studio doesn't open from VNet | Only the `dataFactory` PE was created; portal access needs the `portal` PE too | Add a second PE with `--group-id portal`. |
| `Allow trusted Microsoft services` bypass on Storage doesn't work for ADF | User-assigned MI is in use; only system-assigned MI qualifies as a trusted service | Use system-assigned MI for the trusted-bypass scenario. |

## References

- [ADF introduction](https://learn.microsoft.com/azure/data-factory/introduction)
- [Quickstart: create with Bicep](https://learn.microsoft.com/azure/data-factory/quickstart-create-data-factory-bicep)
- [Service identity](https://learn.microsoft.com/azure/data-factory/data-factory-service-identity)
- [Private Link for ADF](https://learn.microsoft.com/azure/data-factory/data-factory-private-link)
- [Source control / Git integration](https://learn.microsoft.com/azure/data-factory/source-control)
- [CI/CD](https://learn.microsoft.com/azure/data-factory/continuous-integration-delivery)
- [Self-hosted Integration Runtime](https://learn.microsoft.com/azure/data-factory/create-self-hosted-integration-runtime)
- [Blob Storage connector](https://learn.microsoft.com/azure/data-factory/connector-azure-blob-storage)
- [Store credentials in Key Vault](https://learn.microsoft.com/azure/data-factory/store-credentials-in-key-vault)
