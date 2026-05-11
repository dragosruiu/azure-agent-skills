---
name: azure-cost-management
description: >
  Provision Azure Cost Management budgets (`Microsoft.Consumption/budgets`)
  with actual + forecasted thresholds wired to action groups, daily cost
  exports to Storage, anomaly detection (now GA), and the Cost
  Management RBAC roles (which are separate from subscription roles).
version: 0.1.0
azure_services:
  - Microsoft.Consumption/budgets
  - Microsoft.CostManagement/exports
  - Microsoft.CostManagement/scheduledActions
tags:
  - governance
  - cost
  - finops
sources:
  - https://learn.microsoft.com/azure/cost-management-billing/costs/tutorial-acm-create-budgets
  - https://learn.microsoft.com/azure/cost-management-billing/understand/analyze-unexpected-charges
  - https://learn.microsoft.com/azure/cost-management-billing/costs/overview-cost-management
  - https://learn.microsoft.com/azure/cost-management-billing/costs/tutorial-export-acm-data
  - https://learn.microsoft.com/azure/cost-management-billing/reservations/save-compute-costs-reservations
  - https://learn.microsoft.com/azure/cost-management-billing/savings-plan/savings-plan-compute-overview
  - https://learn.microsoft.com/azure/cost-management-billing/costs/assign-access-acm-data
  - https://learn.microsoft.com/azure/templates/microsoft.consumption/budgets
  - https://learn.microsoft.com/azure/cost-management-billing/costs/quick-acm-cost-analysis
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2024-08-01"
last_reviewed: 2026-05-11
---

# Azure Cost Management

## When to use this skill

- The user wants budget alerts before a workload blows the bill.
- The user wants daily cost exports to a downstream BI / data lake.
- The user wants per-team chargeback via tags.

## When NOT to use this skill

- The user wants resource-level metric alerts (CPU, latency) — see
  [`azure-monitor-alerts`](../../observability/azure-monitor-alerts/SKILL.md).
- Reservation purchase decisions — that's a procurement / Advisor flow,
  not IaC.

## Cost Management RBAC (separate from subscription RBAC)

| Role | View costs | Create budgets | Create exports | Create anomaly alerts |
| --- | --- | --- | --- | --- |
| `Cost Management Reader` | ✅ | ❌ | ❌ | ❌ |
| `Cost Management Contributor` | ✅ | ✅ | ✅ | ✅ |
| Subscription `Reader` | ✅ (read-only) | ❌ | ❌ | ❌ |
| Subscription `Owner` / `Contributor` | ✅ | ✅ | ✅ | ✅ |

> A subscription `Reader` can view costs but cannot manage them. This
> is a common misconfiguration. EA customers may also need
> "DA view charges" / "AO view charges" enabled in the EA portal.

## Anomaly detection

**Status: GA.** Subscription-scope only. Uses a WaveNet model trained
on 60 days of usage; evaluates daily ~36 hours after end of day UTC.
**Not available in Azure Government.** ([Source](https://learn.microsoft.com/azure/cost-management-billing/understand/analyze-unexpected-charges))

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| Budget `category` | `'Cost'` | Only valid value at this writing. |
| Budget `timeGrain` | `'Monthly'` (typical); `'BillingMonth'` if you want to align to invoice cycle | |
| Notifications | **at least three**: Actual @ 80%, Actual @ 100%, **Forecasted @ 100%** | The forecast is your early warning. |
| `notifications[].operator` | `'GreaterThan'` | Standard; only sane choice. |
| `notifications[].contactGroups` | action group ARM IDs | Email is fine for most; webhook → Logic App for automated remediation. |
| Action group | confirm OTP for new email receivers within 30 min | If you forget, alerts silently never fire. |
| Tag discipline | enforce `environment`, `costCenter`, `department`, `application` (and inherit from RG via Azure Policy) | Without consistent tags, Cost Analysis grouping is uninformative. |
| Cost export to Storage | daily CSV; storage account allows trusted Microsoft services bypass; export REST API ≥ `2023-08-01` | Required when storage is firewalled. |
| Reservations | only for stable, predictable VM SKU/region | Refunds are limited (up to $50k / 12-month rolling window). |
| Savings Plans | for dynamic compute that may shift SKUs | **No refunds at all** — under-buy if uncertain. |

## Recipe — Bicep (subscription budget)

```bicep
targetScope = 'subscription'

param budgetName string = 'budget-myapp-prod-monthly'
param budgetAmount int = 5000
param alertEmail string
@description('Action group ARM ID for richer fan-out (Logic App, webhook, etc.)')
param actionGroupId string
param startDate string = '2026-05-01'
param endDate string   = '2027-05-01'

resource budget 'Microsoft.Consumption/budgets@2024-08-01' = {
  name: budgetName
  properties: {
    category: 'Cost'
    amount: budgetAmount
    timeGrain: 'Monthly'
    timePeriod: { startDate: startDate, endDate: endDate }
    notifications: {
      Actual_80: {
        enabled: true, operator: 'GreaterThan', threshold: 80
        thresholdType: 'Actual'
        contactEmails: [ alertEmail ]
        contactGroups: [ actionGroupId ]
      }
      Actual_100: {
        enabled: true, operator: 'GreaterThan', threshold: 100
        thresholdType: 'Actual'
        contactEmails: [ alertEmail ]
        contactGroups: [ actionGroupId ]
      }
      Forecast_100: {
        enabled: true, operator: 'GreaterThan', threshold: 100
        thresholdType: 'Forecasted'        // early warning
        contactEmails: [ alertEmail ]
        contactGroups: [ actionGroupId ]
      }
    }
  }
}
```

## Recipe — Azure CLI

```bash
SUB=$(az account show --query id -o tsv)

# 1. Subscription-scope monthly budget
az consumption budget create \
  --budget-name budget-myapp-prod \
  --amount 5000 --time-grain Monthly \
  --start-date 2026-05-01 --end-date 2027-05-01

# 2. Daily CSV export to Storage (storage must allow trusted Azure services)
az costmanagement export create \
  --name export-myapp-daily \
  --scope "/subscriptions/$SUB" \
  --storage-account-id "/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.Storage/storageAccounts/$SA" \
  --storage-container exports --storage-directory myapp/prod \
  --recurrence Daily \
  --recurrence-period from="2026-05-01T00:00:00Z" to="2027-05-01T00:00:00Z" \
  --type ActualCost

# 3. Cost Management roles (separate from subscription roles)
az role assignment create --assignee <user-or-sp-objectid> \
  --role "Cost Management Reader" --scope "/subscriptions/$SUB"
az role assignment create --assignee <ops-team-objectid> \
  --role "Cost Management Contributor" --scope "/subscriptions/$SUB"
```

## Reservations vs Savings Plans

| | Reservations | Savings Plans |
| --- | --- | --- |
| Discount | Up to ~72% off PAYG | Variable based on commitment & term |
| Term | 1 / 3 years | 1 / 3 years (compute); 1 year (databases) |
| Specificity | Locked to SKU + region | Auto-applies across eligible services + regions |
| Best for | Stable workloads, known SKU/region | Dynamic / changing SKU mix |
| Refunds | Up to $50k / 12-month rolling window | **None** |
| Risk if wrong | Stuck for 1–3 years (refund-limited) | Stuck for 1–3 years (no refund) |

Sanity-check via Azure Advisor recommendations before purchase.

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| Budget alert never fires | New email receiver in the action group never confirmed via OTP | Confirm OTP within 30 min of action group creation. |
| Cost analysis tag groupings are inconsistent | Tag values are case-sensitive; some resources use `Production`, some `prod` | Standardize via Azure Policy; remediation task to backfill. |
| Reservation goes unused | Bought wrong region or SKU series | Use Cost Analysis "Reservations utilization" + Advisor before purchase; refund within limits if needed. |
| Savings Plan over-committed | No refund available | Always start small with Advisor recommendations; monitor 30 days first. |
| Cost export fails after enabling Storage firewall | Storage blocks export service | "Allow trusted Microsoft services" on the Storage account; use export REST API `>= 2023-08-01`. |
| `Cost Management Reader` can't create budgets | Reader is read-only | Use `Cost Management Contributor`. |
| Anomaly alerts don't show in portal after API create | `viewId` was set to `null` | PUT must set `viewId` to `ms:DailyAnomalyByResourceGroup`. |
| New subscription shows no cost data | Up to 48-hour delay for new subs; refresh cycle is 8–24 h after that | Wait. |
| Forecasted budget alert fires immediately | Threshold too low for the historical trend | Adjust threshold; or disable the forecasted notification while learning the baseline. |

## References

- [Create budgets (tutorial)](https://learn.microsoft.com/azure/cost-management-billing/costs/tutorial-acm-create-budgets)
- [Analyze unexpected charges (anomaly detection)](https://learn.microsoft.com/azure/cost-management-billing/understand/analyze-unexpected-charges)
- [Cost Management overview](https://learn.microsoft.com/azure/cost-management-billing/costs/overview-cost-management)
- [Export Cost Management data](https://learn.microsoft.com/azure/cost-management-billing/costs/tutorial-export-acm-data)
- [Reservations](https://learn.microsoft.com/azure/cost-management-billing/reservations/save-compute-costs-reservations)
- [Savings plans](https://learn.microsoft.com/azure/cost-management-billing/savings-plan/savings-plan-compute-overview)
- [Assign access](https://learn.microsoft.com/azure/cost-management-billing/costs/assign-access-acm-data)
- [`Microsoft.Consumption/budgets` template](https://learn.microsoft.com/azure/templates/microsoft.consumption/budgets)
- [Cost Analysis quickstart](https://learn.microsoft.com/azure/cost-management-billing/costs/quick-acm-cost-analysis)
