---
name: azure-pipelines-yaml-baseline
description: >
  Azure DevOps Pipelines YAML baseline — `trigger` + `pr: none` to
  avoid double-trigger, stages → jobs → steps, deployment jobs against
  Environments (with manual approvals), variable groups (incl.
  Key-Vault-linked), service connections via WIF (no client secrets),
  and the `extends:` template pattern for centralizing security.
version: 0.1.0
azure_services:
  - n/a (Azure DevOps service)
tags:
  - devops
  - azure-devops
  - pipelines
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/devops/pipelines/yaml-schema/pipeline
  - https://learn.microsoft.com/azure/devops/pipelines/process/template-expressions
  - https://learn.microsoft.com/azure/devops/pipelines/process/resources
  - https://learn.microsoft.com/azure/devops/pipelines/process/environments
  - https://learn.microsoft.com/azure/devops/pipelines/process/templates
  - https://learn.microsoft.com/azure/devops/pipelines/security/templates
  - https://learn.microsoft.com/azure/devops/pipelines/library/variable-groups
  - https://learn.microsoft.com/azure/devops/pipelines/library/link-variable-groups-to-key-vaults
  - https://learn.microsoft.com/azure/devops/pipelines/library/connect-to-azure
validated_with:
  ado_organization: "any (cloud)"
  api_version: "n/a (YAML schema)"
last_reviewed: 2026-05-12
---

# Azure DevOps Pipelines YAML baseline

## When to use this skill

- The user is in Azure DevOps (not GitHub) and writing pipelines.
- The user is centralizing security policy across many pipelines via
  templates.
- The user is wiring KV-backed secrets into pipelines via variable
  groups.

## When NOT to use this skill

- GitHub-hosted CI — see [`github-actions-oidc-to-azure`](github-actions-oidc-to-azure/SKILL.md).
- Service-connection setup itself — see [`azure-devops-oidc`](azure-devops-oidc/SKILL.md).

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| Service connection | **`scheme: WorkloadIdentityFederation`** | No stored secrets. See [`azure-devops-oidc`](azure-devops-oidc/SKILL.md). |
| "Grant access permission to all pipelines" on the SC | **off** | Authorize each pipeline individually. |
| Variable group "Open access" | off (authorize each pipeline) | Only acceptable for non-secret groups. |
| Production environments | `environment: <name>` with **manual approvers** + business-hours check | Forces deployment-job gating. |
| Cross-repo template `ref:` | a **tag** (`refs/tags/v1.2.0`), never a moving branch | Otherwise upstream changes can break pipelines silently. |
| `trigger` and `pr` | always declare both explicitly (`trigger: { branches: { include: [main] } }` + `pr: none` for CI-only pipelines) | Prevents double-firing on PR open. |
| Secret variables | pass via `env:` block on a step — **never echo** | Echoing leaks; pipeline log redaction is best-effort. |
| KV-linked variable group + private endpoint | use **vault access policy** model on the KV (RBAC + PE doesn't trust ADO at this writing) | Otherwise the SC can't fetch secrets. |
| KV SC role | `Key Vault Secrets User` (read) or `Secrets Officer` (rotate) | Read-only is enough for variable groups. |

## Pipeline structure

```yaml
# azure-pipelines.yml
trigger:
  branches: { include: [ main ] }
pr: none                                # avoid double-fire if PR triggers same branch

pool:
  vmImage: ubuntu-latest

variables:
  - group: my-kv-variable-group         # KV-linked variable group
  - group: my-plain-variable-group
  - name: standaloneVar
    value: hello

stages:
  - stage: Build
    jobs:
      - job: BuildJob
        steps:
          - checkout: self
          - script: echo "Building..."

  - stage: Deploy
    condition: and(succeeded(), eq(variables['Build.SourceBranch'], 'refs/heads/main'))
    jobs:
      - deployment: DeployToProduction
        environment: 'production'       # ADO Environment with approvals + checks
        strategy:
          runOnce:
            deploy:
              steps:
                - script: echo "Deploying..."
```

## Templates: same-repo + `extends:` security pattern

**Same-repo step template:**
```yaml
# azure-pipelines.yml
steps:
  - template: templates/build-steps.yml
    parameters:
      solution: '**/*.sln'
```

**Cross-repo `extends:` template** (centralized security wrapper):
```yaml
# azure-pipelines.yml in app repo
resources:
  repositories:
    - repository: central-templates
      type: git
      name: Platform/PipelineTemplates
      ref: refs/tags/v2.1.0           # PIN to a tag

extends:
  template: security/base-pipeline.yml@central-templates
  parameters:
    usersteps:
      - script: echo "App build step"
      - script: echo "App test step"
```

```yaml
# central-templates/security/base-pipeline.yml
parameters:
  - name: usersteps
    type: stepList
    default: []

steps:
  - script: echo "Pre-approved security scan first"
  - ${{ each step in parameters.usersteps }}:
    - ${{ step }}
  - script: echo "Compliance check last"
```

## Variable expansion: `${{ }}` vs `$()` vs `$[ ]`

| Syntax | When evaluated | Use for |
| --- | --- | --- |
| `${{ ... }}` | **Compile time** (pipeline initialization) | Template parameters, conditional inclusion, type-checked values |
| `$( ... )` | **Runtime macro** (when the step actually runs) | Pipeline variables, secrets, normal env-var-style references |
| `$[ ... ]` | **Runtime expression** | Variable assignment, conditions evaluated against runtime state |

```yaml
variables:
  - name: isMain
    value: $[ eq(variables['Build.SourceBranch'], 'refs/heads/main') ]   # runtime expr

steps:
  - ${{ if eq(parameters.environment, 'prod') }}:                        # compile-time
    - script: echo "Only present in prod pipeline"

  - script: echo "On main"
    condition: eq(variables['Build.SourceBranch'], 'refs/heads/main')    # runtime
```

## Variable groups + Key Vault

```yaml
variables:
  - group: my-kv-linked-group        # secrets pulled at runtime

steps:
  - script: |
      echo "calling tool..."
      some-tool --token "$MY_KV_SECRET"
    env:
      MY_KV_SECRET: $(myKvSecretName)   # secrets MUST be passed via env, never echoed
```

## Recipe — Azure CLI (`azure-devops` extension)

```bash
az extension add --name azure-devops --upgrade
az devops configure --defaults organization=https://dev.azure.com/myOrg project=myProject

# Plain variable group
az pipelines variable-group create --name my-group --variables FOO=bar

# Pipeline from existing YAML
az pipelines create --name my-pipeline \
  --yml-path azure-pipelines.yml --repository my-repo --branch main --repository-type tfsgit

# Run it
az pipelines run --name my-pipeline
```

> KV-linked variable groups can't be created via CLI today — use the
> portal UI or the REST API (`PUT https://dev.azure.com/{org}/{project}/_apis/distributedtask/variablegroups`).

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| Variable resolves to empty string at runtime | Used `${{ variables.X }}` (compile-time) for a runtime variable | Switch to `$(X)`. Use `${{ }}` only for template params. |
| KV-linked variable group fails | SC lacks `Get` + `List` on the KV — or the KV is RBAC + PE which ADO can't trust | Grant `Key Vault Secrets User`; for private KV use vault access policies model. |
| PR pipeline fires twice | `trigger` matches the PR's source branch and the `pr` trigger also fires | Add `pr: none` (or vice versa). |
| Pipeline blocked: "resource not authorized" | A new variable group / SC / template repo wasn't authorized for this pipeline | Authorize from the failure screen, or in Library → Pipeline Permissions. |
| Secret leaks in logs / can't be read | Secret variables aren't auto-injected as env vars | Pass via `env:` block on the step; ADO redacts known secret values from logs but only by string match. |
| Cross-repo template fails to load | Template repo not authorized as a `resource` | Add to `resources.repositories` with an authorized service connection. |
| `extends:` template suddenly broke | Template repo's branch moved | Always pin `ref:` to a tag. |

## References

- [Pipeline schema](https://learn.microsoft.com/azure/devops/pipelines/yaml-schema/pipeline)
- [Template expressions](https://learn.microsoft.com/azure/devops/pipelines/process/template-expressions)
- [Resources (cross-repo)](https://learn.microsoft.com/azure/devops/pipelines/process/resources)
- [Environments](https://learn.microsoft.com/azure/devops/pipelines/process/environments)
- [Templates](https://learn.microsoft.com/azure/devops/pipelines/process/templates)
- [Security templates (`extends:` pattern)](https://learn.microsoft.com/azure/devops/pipelines/security/templates)
- [Variable groups](https://learn.microsoft.com/azure/devops/pipelines/library/variable-groups)
- [KV-linked variable groups](https://learn.microsoft.com/azure/devops/pipelines/library/link-variable-groups-to-key-vaults)
- [Connect to Azure (service connections)](https://learn.microsoft.com/azure/devops/pipelines/library/connect-to-azure)
