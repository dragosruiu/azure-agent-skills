---
name: terraform-azurerm-baseline
description: >
  Terraform `azurerm` provider baseline for Azure: required `features {}`
  block, OIDC-based authentication in CI (no client secret), Entra ID
  auth on the Azure Storage backend (no access keys), `plan -out` /
  `apply <file>` separation, and the `azapi` provider as escape hatch
  for new resource properties AzureRM hasn't caught up to.
version: 0.1.0
azure_services:
  - Microsoft.Resources/deployments
tags:
  - infrastructure-as-code
  - terraform
  - oidc
sources:
  - https://learn.microsoft.com/azure/developer/terraform/store-state-in-azure-storage
  - https://learn.microsoft.com/azure/developer/terraform/authenticate-to-azure-with-managed-identity-for-azure-services
  - https://learn.microsoft.com/azure/developer/terraform/overview-azapi-provider
  - https://developer.hashicorp.com/terraform/language/settings/backends/azurerm
  - https://developer.hashicorp.com/terraform/cli/commands/plan
  - https://developer.hashicorp.com/terraform/language/values/variables
  - https://developer.hashicorp.com/terraform/language/files/dependency-lock
validated_with:
  terraform: ">=1.9.0"
  azurerm_provider: "~> 4.0"
  azapi_provider: "~> 2.0"
last_reviewed: 2026-05-11
---

# Terraform AzureRM provider baseline

## When to use this skill

- The user is bootstrapping a new Terraform repo for Azure-only or
  multi-cloud infra.
- The user is migrating off ARM templates / a hand-rolled IaC.
- The user wants to use AzAPI for resources / properties AzureRM
  doesn't yet expose.

## When NOT to use this skill

- Pure Azure stack and the team already uses Bicep happily — Bicep is
  fine and tracks the ARM API faster. See [`bicep-baseline`](../bicep-baseline/SKILL.md).
- One-off ad-hoc resources — `az` CLI is enough.

## Required scaffolding

```hcl
# providers.tf
terraform {
  required_version = ">= 1.9.0"
  required_providers {
    azurerm = { source = "hashicorp/azurerm", version = "~> 4.0" }
    azapi   = { source = "Azure/azapi",       version = "~> 2.0" }
  }
}

provider "azurerm" {
  features {}     # REQUIRED — omitting causes init errors
  # In CI: set ARM_CLIENT_ID / ARM_TENANT_ID / ARM_SUBSCRIPTION_ID +
  # ARM_USE_OIDC=true env vars instead of hardcoding here
}

provider "azapi" {}
```

## Secure defaults

| Decision | Default | Why |
| --- | --- | --- |
| Provider auth (CI) | **OIDC** via `ARM_USE_OIDC=true` and a federated identity | Hashicorp explicitly recommends OIDC (Workload Identity Federation) over client secrets. ([Source](https://developer.hashicorp.com/terraform/language/settings/backends/azurerm)) |
| Backend | `azurerm` backend with state in Azure Storage | Concurrency-safe via blob lease; out of git history. |
| Backend auth | `use_azuread_auth = true` + `use_oidc = true` (CI) | Avoid storage **access keys** entirely; use Entra ID. The state principal needs `Storage Blob Data Contributor` on the *container* (least privilege). |
| `provider "azurerm" { features {} }` | empty `features` block always present | Required by the provider; init fails without it. |
| Sensitive variables | `sensitive = true` (and `ephemeral = true` on TF 1.10+ to omit from state) | Prevents leakage in `plan` / `apply` output. |
| Plan/apply separation in CI | `terraform plan -out=plan.tfplan` then `terraform apply plan.tfplan` | The reviewed plan is exactly what runs — no race conditions. ([Source](https://developer.hashicorp.com/terraform/cli/commands/plan)) |
| `terraform state` files | **never commit** (`terraform.tfstate*` in `.gitignore`); always use a remote backend | State can contain secrets. |
| `.terraform.lock.hcl` | **commit it** | Ensures everyone resolves the same provider versions. Run `terraform providers lock -platform=linux_amd64 -platform=windows_amd64` if you have mixed-OS contributors. |
| AzAPI escape hatch | use `azapi_resource` / `azapi_update_resource` for resources/properties AzureRM doesn't expose | Don't fork AzureRM. ([Source](https://learn.microsoft.com/azure/developer/terraform/overview-azapi-provider)) |
| Module sources | Pin to exact versions for production (`~> 0.5.0`, not just `~> 0.5`) | Prevents surprise upgrades. |

## Backend configuration (CI with OIDC)

```hcl
# backend.tf  -- or pass via -backend-config flags at init time
terraform {
  backend "azurerm" {
    use_oidc                         = true
    oidc_azure_service_connection_id = "..."   # ARM_OIDC_AZURE_SERVICE_CONNECTION_ID (ADO)
    use_azuread_auth                 = true    # Entra ID, NOT access keys
    tenant_id                        = "..."
    client_id                        = "..."
    storage_account_name             = "tfstate<suffix>"
    container_name                   = "tfstate"
    key                              = "env/prod.terraform.tfstate"
  }
}
```

For local dev:

```hcl
backend "azurerm" {
  use_cli              = true
  use_azuread_auth     = true
  tenant_id            = "..."
  storage_account_name = "tfstatelocal"
  container_name       = "tfstate"
  key                  = "dev.terraform.tfstate"
}
```

## State storage account — Azure CLI

```bash
RG=tfstate
LOC=eastus
SA=tfstate$RANDOM

az group create -n "$RG" -l "$LOC"
az storage account create -g "$RG" -n "$SA" \
  --sku Standard_LRS --encryption-services blob \
  --allow-blob-public-access false \
  --min-tls-version TLS1_2 \
  --public-network-access Disabled
az storage container create -n tfstate --account-name "$SA"

# Then add a private endpoint and grant the deploy principal Storage Blob Data Contributor on the container
```

Microsoft recommends restricting access via firewall, service endpoint,
or private endpoint in production. ([Source](https://learn.microsoft.com/azure/developer/terraform/store-state-in-azure-storage))

## CLI workflow

```bash
# Local
az login
terraform init
terraform validate
terraform plan -out=plan.tfplan
terraform apply plan.tfplan

# Recover from a crashed apply (state lock not released)
terraform force-unlock <LOCK_ID>

# Refresh providers + lock file
terraform init -upgrade
```

## AzAPI escape hatch

Use AzAPI when AzureRM doesn't expose a property (or a whole resource type):

```hcl
# Update a property AzureRM doesn't yet expose
resource "azapi_update_resource" "acr_anonymous_pull" {
  type        = "Microsoft.ContainerRegistry/registries@2020-11-01-preview"
  resource_id = azurerm_container_registry.example.id

  body = {
    properties = { anonymousPullEnabled = false }
  }
}

# Brand-new resource type AzureRM doesn't have yet
resource "azapi_resource" "custom_ip_prefix" {
  type      = "Microsoft.Network/Customipprefixes@2021-03-01"
  name      = "my-ip-prefix"
  parent_id = azurerm_resource_group.example.id
  location  = "westus2"

  body = {
    properties = { cidr = "203.0.113.0/24", signedMessage = "ROA signed" }
  }
}
```

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| `provider not initialized: features` | Missing `features {}` in `provider "azurerm"` | Add the empty block. |
| State lock never released after a crashed apply | Azure Blob lease still held | `terraform force-unlock <LOCK_ID>`. |
| New ARM property silently ignored | AzureRM provider lags behind ARM API | Use AzAPI as escape hatch. |
| `terraform.tfstate` accidentally committed | Local state without `.gitignore` | Add `terraform.tfstate*` to `.gitignore`; migrate to remote backend; rotate any leaked secrets. |
| `init` fails: checksum mismatch | `.terraform.lock.hcl` only locked one platform | `terraform providers lock -platform=linux_amd64 -platform=windows_amd64` and re-commit. |
| Backend uses storage access key | `access_key` / `ARM_ACCESS_KEY` set | Switch to `use_azuread_auth = true` + `use_oidc = true`; grant `Storage Blob Data Contributor` on the container. |
| Race between `plan` and `apply` in CI | `plan` and `apply` ran as separate calls without `-out` | Always `plan -out=plan.tfplan` then `apply plan.tfplan`. |
| Module versions drift | Module source uses a loose constraint like `~> 0.5` | Pin to exact `~> 0.5.0` for prod. |

## Azure Verified Modules for Terraform

There's a parallel AVM ecosystem for Terraform (separate from the
Bicep registry):

- Module sources: `Azure/avm-res-<provider>-<resource>/azurerm` and
  `Azure/avm-ptn-<pattern>/azurerm` (Terraform Registry).
- Catalog: <https://azure.github.io/Azure-Verified-Modules/indexes/terraform/>
- Same WAF-default philosophy as Bicep AVM.

## References

- [Store Terraform state in Azure Storage](https://learn.microsoft.com/azure/developer/terraform/store-state-in-azure-storage)
- [Authenticate with managed identity](https://learn.microsoft.com/azure/developer/terraform/authenticate-to-azure-with-managed-identity-for-azure-services)
- [AzAPI provider overview](https://learn.microsoft.com/azure/developer/terraform/overview-azapi-provider)
- [HashiCorp `azurerm` backend docs](https://developer.hashicorp.com/terraform/language/settings/backends/azurerm)
- [`terraform plan` (`-out`)](https://developer.hashicorp.com/terraform/cli/commands/plan)
- [Variables (`sensitive = true`)](https://developer.hashicorp.com/terraform/language/values/variables)
- [Dependency lock file](https://developer.hashicorp.com/terraform/language/files/dependency-lock)
