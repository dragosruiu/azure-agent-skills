---
name: azure-migrate
description: >
  Use Azure Migrate to discover, assess, and migrate VMware / Hyper-V /
  physical / AWS / GCP servers + SQL + web apps to Azure. The hub is
  primarily portal-driven; the appliance VM (Windows Server 2022/2025,
  32 GB RAM / 8 vCPU / ~80 GB disk) needs outbound HTTPS to the
  documented `*.windowsazure.com` / `*.servicebus.windows.net` URLs.
version: 0.1.0
azure_services:
  - Microsoft.Migrate/MigrateProjects
  - Microsoft.Migrate/assessmentprojects
  - Microsoft.OffAzure  # internal RP for appliance/discovery
tags:
  - migration
  - assessment
  - migrate
last_reviewed: 2026-05-12
validated_with:
  az_cli: ">=2.60.0 (with `migrate` extension; experimental coverage)"
  api_version: "n/a (Bicep coverage limited; portal/REST primary)"
sources:
  - https://learn.microsoft.com/azure/migrate/migrate-services-overview
  - https://learn.microsoft.com/azure/migrate/migrate-appliance
  - https://learn.microsoft.com/azure/migrate/tutorial-assess-vmware-azure-vm
  - https://learn.microsoft.com/azure/migrate/migrate-support-matrix-vmware
  - https://learn.microsoft.com/azure/migrate/migrate-support-matrix-vmware-migration
  - https://learn.microsoft.com/azure/migrate/common-questions-appliance
  - https://learn.microsoft.com/azure/migrate/concepts-azure-migrate-gov-overview
---

# Azure Migrate

## When to use this skill

- The user is planning a lift-and-shift of on-prem VMs (VMware / Hyper-V
  / physical) to Azure.
- The user wants right-sizing recommendations + monthly Azure cost
  estimates before migrating.
- The user is consolidating SQL Server / web app discovery for
  modernization decisions (SQL → SQL MI / Flexible / VM; web app → App
  Service / Container Apps).

## When NOT to use this skill

- Application-level data migration (database export/import) — Azure
  Migrate orchestrates VM/server replication, not row-level data
  movement.
- Microsoft Entra-tenant migration / consolidation — that's Entra
  Cloud Sync / cross-tenant sync, not Azure Migrate.

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| Appliance OS | Windows Server 2022 / 2025 (FIPS mode **off**) | FIPS mode isn't supported for the appliance. |
| Outbound from appliance | only the documented URL list, on TCP 443 | Smaller allow-list = less ambient blast radius. |
| Source-system credentials in the appliance | scoped service accounts (vCenter read-only role + extended perms only when doing agentless migration; SQL `VIEW SERVER STATE` + `VIEW ANY DATABASE` only) | Don't reuse Domain Admin. |
| Replication artifacts | dedicated RG per migration wave | Cleanup after cutover is much easier. |
| KV (replication artifacts target) | private endpoint + RBAC | The appliance / target servers need outbound to `*.vault.azure.net`. |
| Test failover | **mandatory** before cutover | Validates Azure-side networking + creds. |
| Migrate project | one per migration *initiative*, in its own RG | Limits cross-team data exposure in the hub. |

## Architecture

```
Azure Migrate Project (one per migration initiative)
├── Discovery and Assessment tool
│   └── Azure Migrate Appliance (lightweight VM in your environment)
│       ├── VMware:   OVA → vCenter (≤ 10 vCenters, 10K servers / appliance)
│       ├── Hyper-V:  VHD → up to 300 hosts, 5K servers / appliance
│       └── Physical / AWS / GCP: PowerShell script → 1K servers / appliance
└── Migration and Modernization tool
    ├── Agentless VMware migration (same appliance + VDDK)
    └── Agent-based migration (separate replication appliance — VMware / physical)
```

## Appliance hardware (verified)

| Source | RAM | vCPU | Disk | OS |
| --- | --- | --- | --- | --- |
| VMware (OVA) | 32 GB | 8 | ~80 GB | Windows Server 2022 / 2025 |
| Hyper-V (VHD) | 16–32 GB | 8 | ~80 GB | Windows Server 2022 / 2025 |
| Physical (PowerShell) | 32 GB | 8 | ~80 GB | Windows Server 2022 / 2025 |

Constraints:
- **One appliance per project** (an appliance can't register to two).
- A project can have multiple appliances.
- **FIPS mode is not supported** for the appliance.
- Don't co-install the Replication Appliance on the same server as the
  Discovery Appliance.

## Required outbound URLs (firewall allow-list)

All on **TCP 443** outbound:

| URL | Purpose |
| --- | --- |
| `*.portal.azure.com` | Portal navigation |
| `*.windows.net`, `*.msftauth.net`, `*.msauth.net`, `*.microsoft.com`, `*.live.com`, `*.office.com`, `*.microsoftonline.com`, `*.microsoftonline-p.com`, `*.microsoftazuread-sso.com`, `*.cloud.microsoft` | Entra ID auth |
| `management.azure.com` | ARM ops |
| `*.vault.azure.net` | Key Vault (also needed on replicated servers during migration) |
| `aka.ms/*`, `download.microsoft.com/download` | Auto-update / installer downloads |
| `*.servicebus.windows.net` | Appliance ↔ Azure Migrate channel |
| `*.discoverysrv.windowsazure.com`, `*.migration.windowsazure.com` | Migrate service endpoints |
| `*.hypervrecoverymanager.windowsazure.com` | **VMware agentless migration only** |
| `*.blob.core.windows.net` | **VMware agentless migration only** (data upload) |

## Assessment knobs

| Type | Sizing basis | Use when |
| --- | --- | --- |
| As-is on-premises | Current VM size | Quick estimate; you trust the on-prem sizing |
| **Performance-based** | Live CPU + memory utilization | Right-sizing for actual load — **preferred** |

Other properties: target region, VM series exclusions, comfort factor
(buffer multiplier), savings options (Reserved Instances 1y/3y, Azure
Savings Plan, PAYG), Azure Hybrid Benefit (Windows Server licenses,
RHEL/SLES subscriptions), EA discount.

## Migration method picker

| Aspect | Agentless (VMware) | Agent-based |
| --- | --- | --- |
| Source agent | none | required |
| Infrastructure | same Discovery appliance + VDDK | **separate** Replication appliance |
| vCenter perms | extended (snapshot, change-tracking, VDDK) | standard |
| Sources supported | VMware only | VMware, physical, AWS, GCP |

Agentless requires the [vCenter permission list](https://learn.microsoft.com/azure/migrate/migrate-support-matrix-vmware-migration)
(snapshot/disk lease/change tracking/etc.).

## Recipe — primarily portal; some CLI

```bash
az extension add --name migrate --upgrade
az group create -n rg-migrate-prod -l eastus

# Create the Migrate project (CLI coverage is limited — many ops are portal-only)
az migrate project create -n migrate-app -g rg-migrate-prod -l eastus \
  --properties '{"assessmentSolutionId": null}'

# After this, the workflow is **portal-driven**:
#  1. Migrate hub → Servers, databases and web apps → Discover
#  2. Generate the OVA / VHD / PowerShell script
#  3. Deploy the appliance VM in your environment
#  4. Register the appliance to the project (uses an Entra device code)
#  5. Configure source credentials (vCenter / Hyper-V / SSH)
#  6. Run discovery (1–2 h for first scan)
#  7. Create assessment (As-is or Performance-based)
#  8. Set up replication (agentless or agent-based)
#  9. Test failover (mandatory before cutover)
# 10. Cutover
```

> **There is no production-quality Bicep recipe** for `Microsoft.Migrate/MigrateProjects`
> in current docs — the resource type exists but the schema isn't
> well-documented for IaC. Use the portal or the Migrate REST API.

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| Appliance can't connect to Azure Migrate service | On-prem firewall blocks the required outbound URLs | Allow the URL list above (TCP 443). Test with `Test-NetConnection servicebus.windows.net -Port 443`. |
| Assessment shows "Ready with conditions" | Guest OS unsupported, drivers missing, or SELinux Enforced | Update OS / install drivers; SELinux Enforced is not fully supported (use Permissive). |
| Replication saturates WAN | Many large VMs replicating in parallel | ExpressRoute (Microsoft peering preferred); throttle replication; stagger waves. |
| "Already registered to another project" on appliance register | An appliance can only belong to one project | Deploy a fresh appliance VM. |
| Software inventory empty | Source VMs lack VMware Tools 10.2.1+ | Install VMware Tools on sources before discovery. |
| SQL Server discovery fails | SQL on Linux not supported for discovery; or SQL discovery account lacks `VIEW SERVER STATE` + `VIEW ANY DATABASE` | Use Windows / Domain auth credentials; SQL on Linux discovery unsupported. |
| Migrated UEFI VM lost Secure Boot | Azure Gen 2 VMs don't auto-enable Trusted Launch on migration | Convert to Trusted Launch post-migration to re-enable Secure Boot. |
| Cutover failed because some resource not in the right RG | Replication created NICs / disks in default RGs | Pre-create target RGs; re-validate replication target settings before cutover. |

## References

- [Migrate services overview](https://learn.microsoft.com/azure/migrate/migrate-services-overview)
- [Appliance overview + URLs](https://learn.microsoft.com/azure/migrate/migrate-appliance)
- [VMware assessment tutorial](https://learn.microsoft.com/azure/migrate/tutorial-assess-vmware-azure-vm)
- [VMware support matrix](https://learn.microsoft.com/azure/migrate/migrate-support-matrix-vmware)
- [VMware migration support matrix](https://learn.microsoft.com/azure/migrate/migrate-support-matrix-vmware-migration)
- [Common questions on the appliance](https://learn.microsoft.com/azure/migrate/common-questions-appliance)
- [Azure Migrate for Government overview](https://learn.microsoft.com/azure/migrate/concepts-azure-migrate-gov-overview)
