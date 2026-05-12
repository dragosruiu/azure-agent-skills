---
name: microsoft-sentinel
description: >
  Provision Microsoft Sentinel on a Log Analytics workspace via the
  modern `Microsoft.SecurityInsights/onboardingStates@2025-09-01`
  resource. Sentinel and its LAW must be in the same subscription;
  workspace cannot be moved after onboarding. Network security
  perimeters are not supported.
version: 0.1.0
azure_services:
  - Microsoft.OperationalInsights/workspaces
  - Microsoft.SecurityInsights/onboardingStates
  - Microsoft.SecurityInsights/dataConnectors
  - Microsoft.SecurityInsights/alertRules
tags:
  - security
  - siem
  - sentinel
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/sentinel/overview
  - https://learn.microsoft.com/azure/sentinel/prerequisites
  - https://learn.microsoft.com/azure/sentinel/quickstart-onboard
  - https://learn.microsoft.com/azure/sentinel/detect-threats-built-in
  - https://learn.microsoft.com/azure/sentinel/automation/create-playbooks
  - https://learn.microsoft.com/azure/sentinel/enroll-simplified-pricing-tier
  - https://learn.microsoft.com/azure/azure-monitor/logs/cost-logs
  - https://learn.microsoft.com/azure/templates/microsoft.securityinsights/onboardingstates
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2025-09-01"
last_reviewed: 2026-05-12
---

# Microsoft Sentinel (SIEM)

## When to use this skill

- The user needs a SIEM that ingests Azure + on-prem + 3rd-party logs.
- The user wants automated incident response via playbooks (Logic Apps).
- The user wants Microsoft-built analytics rules and Fusion ML
  detection on top of their security data.

## When NOT to use this skill

- Posture / vulnerability / runtime threat detection on Azure resources
  themselves — that's [`microsoft-defender-for-cloud`](../microsoft-defender-for-cloud/SKILL.md).
- Plain log search / observability dashboards — see
  [`azure-log-analytics-workspace`](../../observability/azure-log-analytics-workspace/SKILL.md).

## Prerequisites

- A Log Analytics workspace **in the same subscription** as Sentinel,
  in a **PerGB2018 (PAYG)** or commitment tier (legacy "Per Node" is
  unsupported).
- The LAW must have **no resource lock** at onboarding.
- **Network security perimeters are not supported** — analytics rules
  auto-disable if one is applied.
- Roles: `Contributor` on the subscription to enable Sentinel;
  `Microsoft Sentinel Contributor` / `Reader` on the RG to use it.

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| LAW SKU | `'PerGB2018'` (PAYG) or a commitment tier | Legacy SKUs (`PerNode`, etc.) are unsupported. |
| LAW retention | `90` days minimum | Sentinel-enabled LAWs get the **first 90 days free** — use them. |
| LAW `disableLocalAuth` | `true` (workspace `features` block) | Force Entra ID ingestion. |
| RG | dedicated for Sentinel + its LAW | Easier locks, RBAC, and life-cycle separation. |
| Sentinel onboarding resource | `Microsoft.SecurityInsights/onboardingStates@2025-09-01` named `default` | The modern resource. (Legacy `Microsoft.OperationsManagement/solutions` `SecurityInsights` solution still works but is the older path.) |
| Pricing | **simplified pricing** (combined LAW + Sentinel meter, default since July 2023) | Older workspaces opt in via "Switch to new pricing". |
| Commitment tier changes | locked **31 days** | Increase restarts the 31-day window; **decrease blocked** until period ends. |

## Analytics rule types

| Type | When |
| --- | --- |
| **Scheduled** | Most common; KQL run on a schedule. |
| **Near-Real-Time (NRT)** | ~once-per-minute — for low-latency detection. |
| **Anomaly** | ML baseline; results land in `Anomalies` (no alert). |
| **Microsoft Security Rules** | Forward alerts from other Microsoft products. **Auto-disabled if Defender XDR incident integration is on**. |
| **Fusion** | Multi-stage attack ML; one instance only; not customizable. |
| **Threat Intelligence** | Match Microsoft TI against your data. |
| **ML Behavior Analytics** | SSH/RDP anomaly (preview). |

## Recipe — Azure CLI

```bash
RG=rg-sentinel
LOC=eastus
LAW=law-sentinel

# 1. LAW (must be in the same subscription as Sentinel)
az monitor log-analytics workspace create -g "$RG" -n "$LAW" -l "$LOC" \
  --sku PerGB2018 --retention-time 90

# 2. Onboard Sentinel (modern path)
az sentinel onboarding-state create -g "$RG" --workspace-name "$LAW" --name default

# 3. Enable a connector (e.g., Azure Activity log) — most connectors are
#    actually configured on the SOURCE side via diagnostic settings.
#    For Microsoft 1st-party connectors (Entra ID, O365, MDC), enable
#    via the Sentinel portal / `az sentinel data-connector create`.

# 4. Inspect connectors
az sentinel data-connector list -g "$RG" --workspace-name "$LAW" -o table
```

> The exact `az sentinel ...` command surface evolves; verify with
> `az sentinel --help` before scripting.

## Recipe — Bicep

```bicep
param workspaceName string = 'law-sentinel'
param location string = resourceGroup().location

// 1. LAW
resource law 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: workspaceName
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 90
    features: {
      disableLocalAuth: true
      enableLogAccessUsingOnlyResourcePermissions: true
    }
    publicNetworkAccessForIngestion: 'Enabled'   // tighten with AMPLS in prod (see LAW skill)
    publicNetworkAccessForQuery: 'Enabled'
  }
}

// 2. Enable Sentinel on the workspace (modern resource)
resource sentinel 'Microsoft.SecurityInsights/onboardingStates@2025-09-01' = {
  scope: law
  name: 'default'                            // must be 'default'
  properties: {
    customerManagedKey: false
  }
}
```

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| Connector "Connected" but no data | Source resource's diagnostic settings aren't routing to **this** LAW | Confirm the source's diag setting points to the Sentinel LAW; see [`azure-monitor-diagnostic-settings`](../../observability/azure-monitor-diagnostic-settings/SKILL.md). |
| Analytics rule never fires | KQL `query` returns empty due to lookback / frequency mismatch | Run the query in Logs blade to verify; align `windowSize` and `evaluationFrequency`. |
| Microsoft Security Rules auto-disabled | Defender XDR incident integration is on | Expected — handle incidents in the XDR portal instead. |
| All analytic rules auto-disabled | A network security perimeter was applied to the workspace | NSP not supported on Sentinel — remove it. |
| Cannot move LAW to different RG/sub | Sentinel-enabled workspaces can't move | Plan the topology; recreate + re-onboard if needed. |
| Commitment tier change blocked | 31-day lock active | Wait it out, or open a Support case if accidental. |
| Playbook fails 403 | Logic App MI lacks `Microsoft Sentinel Responder` on the workspace | Grant the role. |

## References

- [Sentinel overview](https://learn.microsoft.com/azure/sentinel/overview)
- [Prerequisites](https://learn.microsoft.com/azure/sentinel/prerequisites)
- [Quickstart: onboard](https://learn.microsoft.com/azure/sentinel/quickstart-onboard)
- [Built-in detections](https://learn.microsoft.com/azure/sentinel/detect-threats-built-in)
- [Create playbooks](https://learn.microsoft.com/azure/sentinel/automation/create-playbooks)
- [Simplified pricing](https://learn.microsoft.com/azure/sentinel/enroll-simplified-pricing-tier)
- [LAW cost logs](https://learn.microsoft.com/azure/azure-monitor/logs/cost-logs)
- [`Microsoft.SecurityInsights/onboardingStates` template](https://learn.microsoft.com/azure/templates/microsoft.securityinsights/onboardingstates)
