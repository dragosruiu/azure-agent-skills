---
name: azure-developer-cli
description: >
  Use the Azure Developer CLI (`azd`) to ship a templated end-to-end
  Azure application: `azd init` from a template, `azure.yaml` describing
  services + hooks + IaC provider, per-environment `.azure/<env>/.env`
  state, `azd up` for provision + deploy, and `azd pipeline config` to
  wire up GitHub Actions OIDC.
version: 0.1.0
azure_services:
  - Microsoft.Resources/deployments
tags:
  - devops
  - azd
  - infrastructure-as-code
sources:
  - https://learn.microsoft.com/azure/developer/azure-developer-cli/overview
  - https://learn.microsoft.com/azure/developer/azure-developer-cli/azd-schema
  - https://learn.microsoft.com/azure/developer/azure-developer-cli/manage-environment-variables
  - https://learn.microsoft.com/azure/developer/azure-developer-cli/azd-extensibility
  - https://learn.microsoft.com/azure/developer/azure-developer-cli/configure-devops-pipeline
  - https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd
  - https://learn.microsoft.com/azure/developer/azure-developer-cli/reference
  - https://learn.microsoft.com/azure/developer/azure-developer-cli/troubleshoot
  - https://learn.microsoft.com/azure/azure-resource-manager/bicep/existing-resource
validated_with:
  az_cli: "n/a (azd is its own CLI)"
  api_version: "n/a (template-driven)"
last_reviewed: 2026-05-11
---

# Azure Developer CLI (`azd`)

## When to use this skill

- The user wants a single command (`azd up`) to provision Azure
  infrastructure and deploy app code together.
- The user is starting from one of the AI / web / serverless templates
  on the Azure Samples gallery.
- The user needs the OIDC GitHub Actions workflow generated for them
  (`azd pipeline config`).

## When NOT to use this skill

- The user already has a hand-rolled Bicep + GitHub Actions setup that
  works — `azd` is a productivity tool, not a requirement.
- The IaC is Terraform-heavy with non-Azure providers — `azd` supports
  Terraform but the canonical path is Bicep.

## Prerequisites

- Install: `winget install microsoft.azd` (Windows), `brew install azure/azd/azd` (macOS),
  or `curl -fsSL https://aka.ms/install-azd.sh | bash` (Linux).
- `azd auth login` (browser or device code).
- Bicep is bundled with `azd` (don't need a separate global Bicep install).

## Project layout

```
my-app/
├── azure.yaml                 # the manifest azd reads
├── infra/
│   ├── main.bicep             # entry point — outputs become env vars
│   ├── main.parameters.json   # parameter file (or main.bicepparam)
│   └── modules/...
├── src/
│   ├── web/                   # service "web" — see azure.yaml
│   └── api/                   # service "api"
└── .azure/                    # gitignored — per-env state
    ├── dev/
    │   └── .env               # NEVER commit; NEVER store secrets here
    └── prod/
        └── .env
```

## `azure.yaml` schema

```yaml
name: my-app                    # required; lowercase, digits, hyphens
metadata:
  template: my-app@1.0.0

resourceGroup: rg-${AZURE_ENV_NAME}     # supports env-var substitution

infra:
  provider: bicep               # bicep (default) or terraform
  path: infra
  module: main                  # default = main (main.bicep)

services:
  web:
    project: ./src/web
    language: js                # dotnet | csharp | fsharp | py | python | js | ts | java | docker
    host: appservice            # appservice | containerapp | function | staticwebapp | springapp | aks
    dist: build
  api:
    project: ./src/api
    language: ts
    host: containerapp
    docker:
      path: ./Dockerfile
      context: .

hooks:
  preprovision:
    shell: sh
    run: ./scripts/preprovision.sh
    continueOnError: false
  postprovision:
    windows: { shell: pwsh, run: ./scripts/postprovision.ps1 }
    posix:   { shell: sh,   run: ./scripts/postprovision.sh }
  postdeploy:
    shell: sh
    run: azd env set REACT_APP_API_URL ${SERVICE_API_ENDPOINT_URL}
```

Available hooks: `prerestore`/`postrestore`, `preprovision`/`postprovision`,
`prepackage`/`postpackage`, `predeploy`/`postdeploy`, `prepublish`/`postpublish`,
`preup`/`postup`, `predown`/`postdown`.
([Source](https://learn.microsoft.com/azure/developer/azure-developer-cli/azd-extensibility))

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| Secrets in `.azure/<env>/.env` | **Never.** Use `azd env set-secret` to store a Key Vault reference instead. | Microsoft docs explicitly warn: *"These files can easily be shared or copied into unauthorized locations, or checked into source control."* |
| `.gitignore` | include `.azure/` | Prevents accidental commit of state and `.env`. |
| Pipeline auth | `azd pipeline config` defaults to **OIDC for GitHub Actions** | No client secrets in GitHub. Azure Pipelines still uses client credentials. |
| Pipeline environment | use **separate env names** for local and CI (e.g., `dev-local` vs `dev-ci`) | Prevents one workflow from overwriting another's RBAC. |
| Bicep `existing` keyword | use for any resource the template might re-encounter | Makes deploys idempotent. ([Source](https://learn.microsoft.com/azure/azure-resource-manager/bicep/existing-resource)) |
| Hook `continueOnError` | `false` in CI | Surfaces errors. Use `true` only in local dev iterations. |
| `infra/main.bicep` outputs | export anything subsequent services need | Auto-captured into `.env` after `azd provision`. |

## Standard environment variables `azd` writes

| Variable | When set |
| --- | --- |
| `AZURE_ENV_NAME` | `azd env new` |
| `AZURE_LOCATION` | first provision |
| `AZURE_SUBSCRIPTION_ID` | first provision |
| `AZURE_RESOURCE_GROUP` | provision |
| `AZURE_PRINCIPAL_ID` | provision |
| `AZURE_TENANT_ID` | provision |

Anything you `output` from `infra/main.bicep` becomes an env var with
the output name.

## Recipe

```bash
# Initialize from a template
azd init --template Azure-Samples/todo-nodejs-mongo

# Create environments
azd env new dev
azd env new prod
azd env select dev

# One-shot provision + deploy
azd up

# Or split
azd provision
azd deploy

# Per-env vars
azd env set MY_FEATURE_FLAG true
azd env get-values
azd env refresh         # re-pull outputs from Azure

# Configure CI/CD (OIDC for GitHub by default)
azd pipeline config

# Tear down
azd down

# Update azd itself
azd update
```

`infra/main.parameters.json` (env-var substitution):

```json
{
  "parameters": {
    "environmentName": { "value": "${AZURE_ENV_NAME}" },
    "location":        { "value": "${AZURE_LOCATION}" }
  }
}
```

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| `azd provision` fails on re-run with "resource already exists" | Bicep tries to re-create something every run | Use the `existing` keyword for shared resources; `uniqueString(...)` for deterministic-but-unique names. |
| `.azure/<env>/.env` committed by accident | Repo's `.gitignore` doesn't list `.azure/` | Add `.azure/` to `.gitignore`; rotate any leaked secrets. |
| `azd up` uses a stale Bicep CLI | `azd` bundles its own Bicep within its scope | Set `AZD_BICEP_TOOL_PATH` to a specific Bicep binary. ([Source](https://learn.microsoft.com/azure/developer/azure-developer-cli/troubleshoot)) |
| Hook script silently aborts the workflow | `continueOnError` defaults to `false` | Read the failed hook's logs; consider `windows`/`posix` overrides if it's a cross-platform script. |
| GitHub Actions: `Does not have secrets get permission on key vault` | Same env name used locally and in CI; one ran after the other and overwrote RBAC | Use separate env names per pipeline target. |
| `azd pipeline config` errors on Conditional Access | Device-code login can't satisfy device-platform CA policies | `azd auth login --use-device-code=false` first. |
| Static Web Apps deploy "succeeds" but content didn't update | Known interaction with `azd deploy` | Copy `staticwebapp.config.json` into the build output via a `prepackage` hook. |

## References

- [`azd` overview](https://learn.microsoft.com/azure/developer/azure-developer-cli/overview)
- [`azure.yaml` schema](https://learn.microsoft.com/azure/developer/azure-developer-cli/azd-schema)
- [Manage environment variables](https://learn.microsoft.com/azure/developer/azure-developer-cli/manage-environment-variables)
- [Hooks (extensibility)](https://learn.microsoft.com/azure/developer/azure-developer-cli/azd-extensibility)
- [Configure CI/CD pipeline](https://learn.microsoft.com/azure/developer/azure-developer-cli/configure-devops-pipeline)
- [Install `azd`](https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd)
- [Command reference](https://learn.microsoft.com/azure/developer/azure-developer-cli/reference)
- [Troubleshoot](https://learn.microsoft.com/azure/developer/azure-developer-cli/troubleshoot)
- [Bicep `existing` keyword](https://learn.microsoft.com/azure/azure-resource-manager/bicep/existing-resource)
