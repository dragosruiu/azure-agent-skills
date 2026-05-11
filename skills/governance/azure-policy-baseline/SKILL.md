---
name: azure-policy-baseline
description: >
  Apply an Azure Policy baseline: assign the built-in Microsoft Cloud
  Security Benchmark initiative at subscription/MG scope, understand the
  effect ladder (audit → auditIfNotExists → deny → deployIfNotExists →
  modify), grant the assignment's MI the right RBAC for remediation, and
  start in `DoNotEnforce` (audit-only) before flipping to enforce.
version: 0.1.0
azure_services:
  - Microsoft.Authorization/policyAssignments
  - Microsoft.Authorization/policySetDefinitions
  - Microsoft.PolicyInsights/remediations
tags:
  - governance
  - policy
  - mcsb
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/governance/policy/concepts/effects
  - https://learn.microsoft.com/azure/governance/policy/samples/azure-security-benchmark
  - https://learn.microsoft.com/azure/governance/policy/assign-policy-bicep
  - https://learn.microsoft.com/azure/governance/policy/concepts/initiative-definition-structure
  - https://learn.microsoft.com/azure/governance/policy/how-to/remediate-resources
  - https://learn.microsoft.com/azure/governance/policy/concepts/effect-deploy-if-not-exists
  - https://learn.microsoft.com/cli/azure/policy/assignment
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2023-04-01"
last_reviewed: 2026-05-11
---

# Azure Policy baseline

## When to use this skill

- The user is bootstrapping a new subscription / management group and
  wants compliance scanning + guardrails.
- The user wants to enforce naming, tagging, allowed locations, or
  service security baselines.
- The user wants to backfill missing config (e.g., diagnostic settings)
  on existing resources.

## When NOT to use this skill

- The user wants resource-level RBAC — that's `Microsoft.Authorization/roleAssignments`,
  not Policy. See [`azure-rbac-least-privilege`](../../identity-and-access/azure-rbac-least-privilege/SKILL.md).
- The user wants Defender-style threat detection — that's Microsoft
  Defender for Cloud (which itself is partly enabled via Policy).

## Effect ladder

| Effect | What it does | MI required? | Backfills existing? |
| --- | --- | --- | --- |
| `audit` | Marks non-compliant; no action | No | No |
| `auditIfNotExists` | Checks for a related/child resource; marks non-compliant if missing | No | No |
| `deny` | Blocks `create`/`update` on the resource | No | No (existing non-compliant resources stay) |
| `deployIfNotExists` ("DINE") | Deploys an ARM template if condition met | **Yes** | **Yes**, via remediation task |
| `modify` | Add / replace / remove tags or specific property aliases | **Yes** | **Yes**, via remediation task |
| `append` | Adds fields to a request | No | No |
| `denyAction` | Blocks specific actions (e.g., delete) | No | No |
| `disabled` | Skips evaluation | No | — |

Evaluation order: `disabled` → `append`/`modify` → `deny` → `audit` →
`manual` → `auditIfNotExists` → `denyAction`. After a successful RP
response, `deployIfNotExists` runs.

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| Initiative | **Microsoft cloud security benchmark** (MCSB) — supersedes Azure Security Benchmark v3 | Microsoft's canonical baseline, auto-mapped into Defender for Cloud's secure score. |
| Assignment scope | Management group (preferred) or subscription | Higher scope = fewer assignments to manage. |
| `enforcementMode` | start with `'DoNotEnforce'` (audit only) for `deny`-effect policies | Avoid breaking pre-existing resources. Switch to `Default` after cleanup. |
| Assignment `identity.type` | `'SystemAssigned'` for any DINE/modify policy | Required to deploy / modify on remediation. |
| Remediation MI RBAC | grant the roles listed in the policy's `details.roleDefinitionIds` at the assignment scope | Portal does this auto; CLI/SDK assignments **do not** — you must do it manually. |
| `notScopes` | exempt break-glass / shared resources explicitly | Cleaner than building exceptions into every policy. |

> **Tag inheritance trap:** the built-in *Inherit a tag from the resource
> group if missing* policy applies **forward only** — it doesn't tag
> pre-existing resources. Run a remediation task to backfill.

## Recipe — Azure CLI

```bash
SUB=$(az account show --query id -o tsv)

# 1. Assign MCSB to a subscription (audit-only initiative — safe by default)
#    Look up the policy set definition ID first:
MCSB_ID=$(az policy set-definition list \
  --query "[?displayName=='Microsoft cloud security benchmark'].id" -o tsv)
az policy assignment create \
  --name assign-mcsb \
  --display-name "Microsoft cloud security benchmark" \
  --policy-set-definition "$MCSB_ID" \
  --scope "/subscriptions/$SUB" \
  --mi-system-assigned \
  --location eastus \
  --role Contributor \
  --identity-scope "/subscriptions/$SUB"

# 2. Assign 'Allowed locations' built-in to a management group with parameters + exclusions
az policy assignment create \
  --name enforce-locations \
  --policy "e56962a6-4747-49cd-b67b-bf8b01975c4f" \
  --scope "/providers/Microsoft.Management/managementGroups/<mgName>" \
  --params '{"listOfAllowedLocations": {"value": ["eastus","westeurope"]}}' \
  --not-scopes "/subscriptions/<exempt-sub-id>"

# 3. Audit-only (DoNotEnforce) for a deny-effect policy you're rolling out
az policy assignment create \
  --name audit-only-rollout \
  --policy <policy-or-set-id> \
  --scope "/subscriptions/$SUB" \
  --enforcement-mode DoNotEnforce

# 4. Trigger a remediation task for DINE/modify policies
az policy remediation create \
  --name remediate-diag-settings \
  --policy-assignment assign-mcsb \
  --scope "/subscriptions/$SUB"

# 5. On-demand evaluation scan (otherwise compliance refreshes ~24h)
az policy state trigger-scan --resource-group <rg>
```

## Recipe — Bicep

```bicep
targetScope = 'subscription'

@description('Built-in Microsoft cloud security benchmark initiative')
param mcsbId string

resource assignment 'Microsoft.Authorization/policyAssignments@2023-04-01' = {
  name: 'assign-mcsb'
  location: 'eastus'                 // required when identity is SystemAssigned
  identity: { type: 'SystemAssigned' }
  properties: {
    policyDefinitionId: mcsbId
    displayName: 'Microsoft cloud security benchmark'
    enforcementMode: 'Default'       // 'DoNotEnforce' for audit-only rollout
    nonComplianceMessages: [
      { message: 'Resource must comply with MCSB.' }
    ]
    notScopes: [
      // exempt scopes (full resource IDs)
    ]
  }
}
```

> Pin policy definitions inside an initiative with `definitionVersion: '1.2.*'`
> if you want stability across patch releases. Omit to always use latest.
> ([Source](https://learn.microsoft.com/azure/governance/policy/concepts/initiative-definition-structure))

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| DINE / modify policy assigned but nothing changes on existing resources | Assignment's MI lacks the roles in `details.roleDefinitionIds`; no remediation task created | Grant the roles at the assignment scope; create a remediation task. ([Source](https://learn.microsoft.com/azure/governance/policy/how-to/remediate-resources)) |
| Brand-new `deny` assignment immediately breaks existing non-compliant resource updates | `deny` blocks all create/update, including legitimate updates to non-compliant resources | Use `audit` first; clean up; then switch to `deny`. Or set `enforcementMode: 'DoNotEnforce'` while triaging. |
| Compliance dashboard still says "Not started" | Initial scan can take up to 24 h | Trigger an on-demand scan with `az policy state trigger-scan`. |
| Remediation task in portal grays out at MG scope | Portal's "create remediation during assignment" wizard is subscription-scope only | Create the task afterwards from the Remediation blade. |
| Parameter type mismatch on assignment | Initiative param is `array` but assignment passed a `string` | Match the type from the initiative's `parameterDefinitions`. |
| `Inherit Tag` policy didn't tag resources I expected | Policy is forward-only; doesn't backfill | Create a remediation task; or `az resource tag` to backfill manually. |

## References

- [Effects](https://learn.microsoft.com/azure/governance/policy/concepts/effects)
- [Microsoft cloud security benchmark initiative](https://learn.microsoft.com/azure/governance/policy/samples/azure-security-benchmark)
- [Assign with Bicep](https://learn.microsoft.com/azure/governance/policy/assign-policy-bicep)
- [Initiative definition structure](https://learn.microsoft.com/azure/governance/policy/concepts/initiative-definition-structure)
- [Remediate resources](https://learn.microsoft.com/azure/governance/policy/how-to/remediate-resources)
- [`deployIfNotExists` effect](https://learn.microsoft.com/azure/governance/policy/concepts/effect-deploy-if-not-exists)
- [`az policy assignment`](https://learn.microsoft.com/cli/azure/policy/assignment)
