---
name: microsoft-defender-for-cloud
description: >
  Enable Microsoft Defender for Cloud at subscription scope: foundational
  free CSPM (auto-applied), paid Defender CSPM for attack-path / DSPM /
  agentless scanning, and the workload-protection plans (Servers Plan 2,
  Storage, Containers, Key Vault, App Service, Resource Manager, DNS,
  Open-source RDB, APIs, SQL). MCSB is auto-applied as the security
  baseline.
version: 0.1.0
azure_services:
  - Microsoft.Security/pricings
  - Microsoft.Security/securityContacts
  - Microsoft.Security/autoProvisioningSettings
tags:
  - security
  - defender
  - cspm
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/defender-for-cloud/concept-cloud-security-posture-management
  - https://learn.microsoft.com/azure/defender-for-cloud/just-in-time-access-overview
  - https://learn.microsoft.com/azure/defender-for-cloud/auto-deploy-azure-monitoring-agent
  - https://learn.microsoft.com/azure/defender-for-cloud/concept-regulatory-compliance
  - https://learn.microsoft.com/azure/defender-for-cloud/secure-score-security-controls
  - https://learn.microsoft.com/azure/templates/microsoft.security/2024-01-01/pricings
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2024-01-01"
last_reviewed: 2026-05-12
---

# Microsoft Defender for Cloud (CSPM + workload protection)

## When to use this skill

- Bootstrapping a new subscription / management group and want a sane
  security posture baseline.
- The user wants attack-path / DSPM / agentless vuln scanning — those
  need **Defender CSPM** (paid).
- Compliance evidence (PCI / ISO / SOC 2 / etc.) is needed — regulatory
  compliance dashboards are Defender CSPM only.

## When NOT to use this skill

- The user wants a SIEM — see [`microsoft-sentinel`](../microsoft-sentinel/SKILL.md).
- The user wants App-side anomaly detection — see
  [`azure-application-insights`](../../observability/azure-application-insights/SKILL.md).

## Posture vs workload protection

| Tier | What you get | When |
| --- | --- | --- |
| **Foundational CSPM (Free)** | Auto-applied on every onboarded sub. MCSB initiative auto-assigned, Secure Score, recommendations, asset inventory. | Always on. |
| **Defender CSPM (Standard)** | Adds attack-path analysis, agentless VM + container scanning, DSPM, regulatory compliance dashboards (PCI/ISO/etc), risk prioritization, Entra Permissions Management. | When you need any of the above. |
| **Workload-protection plans (per service)** | Runtime threat detection, alerts, JIT, FIM, vuln assessment, etc. — one per resource type. | Per workload. |

## Workload-protection plan picker (verified plan names)

All use `Microsoft.Security/pricings@2024-01-01` at subscription scope with `pricingTier: 'Standard'`.

| Plan | `name` field | `subPlan` | Notable extensions |
| --- | --- | --- | --- |
| Defender for Servers Plan 1 | `VirtualMachines` | `P1` | `MdeDesignatedSubscription` |
| Defender for Servers Plan 2 | `VirtualMachines` | `P2` | `FileIntegrityMonitoring`, `AgentlessVmScanning`, `MdeDesignatedSubscription`. **Required for JIT VM access.** |
| Defender for Storage | `StorageAccounts` | (none = P2 by default) | `OnUploadMalwareScanning`, `SensitiveDataDiscovery` |
| Defender for Containers | `Containers` | — | `AgentlessDiscoveryForKubernetes`, `ContainerRegistriesVulnerabilityAssessments`, `ContainerSensor` |
| Defender CSPM | `CloudPosture` | — | `AgentlessDiscoveryForKubernetes`, `AgentlessVmScanning`, `SensitiveDataDiscovery`, `EntraPermissionsManagement` |
| Defender for Key Vault | `KeyVaults` | — | — |
| Defender for App Service | `AppServices` | — | — |
| Defender for Resource Manager | `Arm` | — | — |
| Defender for DNS | `Dns` | — | — |
| Defender for Open-source RDB | `OpenSourceRelationalDatabases` | — | — |
| Defender for SQL servers on machines | `SqlServerVirtualMachines` | — | — |
| Defender for SQL DB / MI | `SqlServers` | — | — |
| Defender for APIs | `Api` | — | — |

> The plan `name` strings are platform-stable. Verify `subPlan` and
> extension lists against [Microsoft.Security/pricings@2024-01-01](https://learn.microsoft.com/azure/templates/microsoft.security/2024-01-01/pricings).

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| Defender for Servers | **Plan 2** | JIT, FIM, agentless VM scanning, 500 MB/day free LAW ingest. Plan 1 lacks all of these. |
| Defender CSPM | enabled (paid) | Attack-path, DSPM, regulatory compliance dashboards. |
| Defender for Storage / Containers / Key Vault / Resource Manager | enable for any sub that holds those resources | Per-service runtime detection. |
| `enforce` | `'True'` on every pricing resource | Prevents child scopes (RGs, sub-MGs) from overriding. |
| MCSB initiative | auto-applied; **leave it on** | Drives Secure Score and recommendations. See [`azure-policy-baseline`](../../governance/azure-policy-baseline/SKILL.md). |
| Auto-provisioning of **AMA** | on (Log Analytics agent / MMA is **deprecated**) | AMA is the modern path. |
| Email alerts | configure a **`securityContact`** with `alertNotifications: 'On'` | Otherwise high-severity alerts go nowhere. |

## Recipe — Azure CLI

```bash
SUB=$(az account show --query id -o tsv)

# Inspect current state
az security pricing list --query "[].{name:name, tier:pricingTier, subPlan:subPlan}" -o table

# Enable Defender for Servers Plan 2
az security pricing create --name VirtualMachines --tier Standard --sub-plan P2

# Enable Defender CSPM
az security pricing create --name CloudPosture --tier Standard

# Enable Defender for Containers (also enables AKS Defender; pair with --enable-defender on aks)
az security pricing create --name Containers --tier Standard

# Enable a few more universal plans
az security pricing create --name StorageAccounts --tier Standard
az security pricing create --name KeyVaults       --tier Standard
az security pricing create --name Arm             --tier Standard

# Security contact (so alerts go somewhere)
az security contact create --name default \
  --emails security@contoso.com --notifications-by-role 'Owner;ServiceAdmin' \
  --alert-notifications 'On' --notifications-sources 'Alert;AttackPath'
```

## Recipe — Bicep (subscription scope)

```bicep
targetScope = 'subscription'

// Defender for Servers Plan 2 with FIM + agentless scanning
resource defServers 'Microsoft.Security/pricings@2024-01-01' = {
  name: 'VirtualMachines'
  properties: {
    pricingTier: 'Standard'
    subPlan: 'P2'
    enforce: 'True'
    extensions: [
      { name: 'FileIntegrityMonitoring',     isEnabled: 'True' }
      { name: 'AgentlessVmScanning',         isEnabled: 'True' }
      { name: 'MdeDesignatedSubscription',   isEnabled: 'True' }
    ]
  }
}

// Defender CSPM (paid) — attack path + DSPM + regulatory compliance
resource defCspm 'Microsoft.Security/pricings@2024-01-01' = {
  name: 'CloudPosture'
  properties: {
    pricingTier: 'Standard'
    enforce: 'True'
    extensions: [
      { name: 'AgentlessDiscoveryForKubernetes', isEnabled: 'True' }
      { name: 'AgentlessVmScanning',             isEnabled: 'True' }
      { name: 'SensitiveDataDiscovery',          isEnabled: 'True' }
      { name: 'EntraPermissionsManagement',      isEnabled: 'True' }
    ]
  }
}

// Defender for Containers (works with AKS / ACR / etc.)
resource defContainers 'Microsoft.Security/pricings@2024-01-01' = {
  name: 'Containers'
  properties: {
    pricingTier: 'Standard'
    enforce: 'True'
    extensions: [
      { name: 'AgentlessDiscoveryForKubernetes',           isEnabled: 'True' }
      { name: 'ContainerRegistriesVulnerabilityAssessments', isEnabled: 'True' }
      { name: 'ContainerSensor',                           isEnabled: 'True' }
    ]
  }
}
```

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| AMA not auto-deploying | Auto-provisioning disabled, or no plan that requires AMA is enabled | Check `az security auto-provisioning-setting list`; enable a plan that triggers AMA. |
| JIT button greyed out | Defender for **Servers Plan 1** (or no Defender) | Switch to Plan 2. |
| Recommendations stuck "in progress" | Remediation script (DINE policy) lacks RBAC at the target scope | Grant the policy assignment's MI the role listed in `roleDefinitionIds`. |
| AKS Defender protection inactive | The AKS cluster needs `securityProfile.defender` configured | Set `--enable-defender` on `az aks create/update`, or set the Bicep property. |
| Regulatory compliance dashboard empty | Foundational CSPM only — dashboards need **Defender CSPM** | Enable `CloudPosture` plan. |
| Plan enabled at MG but child sub overrides | Default behavior unless `enforce: 'True'` | Set `enforce: 'True'` on every pricing assignment. |
| Alerts silent | No `securityContact` with `alertNotifications: 'On'` | Create one. |
| MCSB v2 not visible | v2 is **opt-in** from the regulatory compliance dashboard | Opt in from the portal. |

## References

- [Cloud Security Posture Management](https://learn.microsoft.com/azure/defender-for-cloud/concept-cloud-security-posture-management)
- [Just-in-time access](https://learn.microsoft.com/azure/defender-for-cloud/just-in-time-access-overview)
- [Auto-deploy Azure Monitor Agent](https://learn.microsoft.com/azure/defender-for-cloud/auto-deploy-azure-monitoring-agent)
- [Regulatory compliance](https://learn.microsoft.com/azure/defender-for-cloud/concept-regulatory-compliance)
- [Secure Score](https://learn.microsoft.com/azure/defender-for-cloud/secure-score-security-controls)
- [`Microsoft.Security/pricings@2024-01-01` template](https://learn.microsoft.com/azure/templates/microsoft.security/2024-01-01/pricings)
