# infrastructure-as-code/

Skills for declaring Azure infrastructure declaratively, with previews
and policy enforcement before deploy.

## In scope

- Bicep baseline (repo layout, parameter files, what-if, scopes)
- Azure Verified Modules (planned)
- Terraform with the AzureRM and AzAPI providers (planned)
- Pulumi for Azure (planned)

## Default posture

- Prefer **Bicep** for greenfield Azure-only stacks (first-class ARM
  support, fastest to new API versions).
- Use **AzAPI** in Terraform for Azure-only resources that AzureRM
  hasn't caught up on.
- Always run `what-if` (Bicep) or `plan` (Terraform) in a PR job before
  apply.
- Parameter files (`.bicepparam`) live alongside the module, one per
  environment.
- Secrets stay in Key Vault and are pulled via `getSecret(...)` /
  Terraform `azurerm_key_vault_secret`, not embedded in the file.
