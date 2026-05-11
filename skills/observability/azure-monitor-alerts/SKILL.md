---
name: azure-monitor-alerts
description: >
  Provision Azure Monitor alerts: metric alerts (`Microsoft.Insights/metricAlerts`),
  log search alerts (`microsoft.insights/scheduledQueryRules`), activity log
  alerts, and action groups (email/SMS/webhook/Function/Logic App). Notes
  the SMS rate limit, dynamic-threshold warm-up, and the `windowSize` /
  `evaluationFrequency` trap that causes alert fatigue.
version: 0.1.0
azure_services:
  - Microsoft.Insights/metricAlerts
  - microsoft.insights/scheduledQueryRules
  - microsoft.insights/activityLogAlerts
  - Microsoft.Insights/actionGroups
tags:
  - observability
  - alerts
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/azure-monitor/alerts/alerts-overview
  - https://learn.microsoft.com/azure/azure-monitor/alerts/alerts-types
  - https://learn.microsoft.com/azure/azure-monitor/alerts/alerts-create-metric-alert-rule
  - https://learn.microsoft.com/azure/azure-monitor/alerts/alerts-create-log-alert-rule
  - https://learn.microsoft.com/azure/azure-monitor/alerts/alerts-dynamic-thresholds
  - https://learn.microsoft.com/azure/azure-monitor/alerts/action-groups
  - https://learn.microsoft.com/azure/azure-monitor/alerts/resource-manager-alerts-metric
  - https://learn.microsoft.com/azure/azure-monitor/alerts/resource-manager-alerts-log
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2018-03-01"
last_reviewed: 2026-05-11
---

# Azure Monitor alerts

## When to use this skill

- The user wants page-on-call notifications when a metric crosses a
  threshold or a KQL query returns rows.
- The user wants to react to control-plane events (resource deleted,
  policy denied) — that's an activity-log alert.
- The user wants self-tuning thresholds (dynamic) on metrics with
  seasonality.

## When NOT to use this skill

- The user wants application-side anomaly detection at the trace level
  — Application Insights smart detection is a different surface.
- The user wants alerts based on Defender for Cloud findings — those
  flow through Defender, not Monitor.

## Alert type → resource type

| Alert | ARM resource type | Stable API version |
| --- | --- | --- |
| Metric alert (static or dynamic threshold) | `Microsoft.Insights/metricAlerts` | `2018-03-01` |
| Log search alert | `microsoft.insights/scheduledQueryRules` | `2021-08-01` (static) / `2025-01-01-preview` (dynamic) |
| Activity log alert | `microsoft.insights/activityLogAlerts` | (not a fully verified Bicep template — use portal/CLI) |
| Smart detection | `Microsoft.AlertsManagement/smartDetectorAlertRules` | (verify before authoring) |
| Action group | `Microsoft.Insights/actionGroups` | recent stable (verify with `az resource show`) |

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| Metric alert `location` | `'global'` | Metric alerts are always global. |
| Log alert `location` | the workspace / scoped-resource region | Log alerts run in the data's region. |
| `severity` | `0` Critical, `1` Error, `2` Warning, `3` Informational, `4` Verbose | Use `0`/`1` only for true paging events. |
| `evaluationFrequency` | `PT5M` typical (`PT1M` for critical metric alerts) | Don't set `PT1M` on log alerts using `search`/`union`/`take`/`adx` — unsupported. |
| `windowSize` | `>= evaluationFrequency`, often `2×–3×` | Smaller windows = noisier; tune with `failingPeriods.minFailingPeriodsToAlert`. |
| `failingPeriods.minFailingPeriodsToAlert` | `2`+ for log alerts | Reduces false positives without changing window size. |
| `autoMitigate` (log alerts) | `true` | Stateful — alert resolves when condition clears. |
| Dynamic threshold `alertSensitivity` | `'Medium'` (default) | `High` = more alerts, `Low` = fewer. |
| Dynamic threshold warm-up | wait **3 days + 30 samples** on a new resource | Below that, the model can't detect seasonality. |
| Action group `secure webhook` | enabled (Entra ID auth) over plain webhook | No basic auth; cert support not available either. |

## Recipe — Azure CLI

```bash
RG=rg-monitoring-prod
LOC=eastus
AG_ID="/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.Insights/actionGroups/ag-oncall"

# 1. Action group (email + SMS)
az monitor action-group create -g "$RG" -n ag-oncall --short-name oncall \
  --email-receiver name=AdminEmail email=oncall@contoso.com \
  --sms-receiver  name=OncallSMS  country-code=1 phone-number=5551234567

# 2. Metric alert: VM CPU > 80% for 5 min
VM_ID=/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.Compute/virtualMachines/myVM
az monitor metrics alert create -g "$RG" -n vm-high-cpu \
  --scopes "$VM_ID" \
  --condition "avg Percentage CPU > 80" \
  --window-size 5m --evaluation-frequency 1m \
  --severity 2 --action "$AG_ID"

# 3. Log search alert: more than 0 errors in last 15 minutes
LAW_ID=/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.OperationalInsights/workspaces/law-app
az monitor scheduled-query create -g "$RG" -n app-error-spike \
  --scopes "$LAW_ID" \
  --condition-query "AppExceptions | where TimeGenerated > ago(15m) | summarize count()" \
  --condition "count 'AppExceptions' > 0" \
  --window-size 15m --evaluation-frequency 5m \
  --severity 2 --action "$AG_ID"
```

## Recipe — Bicep (metric alert, static threshold)

```bicep
param alertName string
param actionGroupId string
param targetResourceId string

resource cpu 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: alertName
  location: 'global'                  // metric alerts always global
  properties: {
    severity: 2
    enabled: true
    scopes: [ targetResourceId ]
    evaluationFrequency: 'PT1M'
    windowSize: 'PT5M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        {
          name: 'cpu-over-80'
          metricName: 'Percentage CPU'
          operator: 'GreaterThan'
          threshold: 80
          timeAggregation: 'Average'
          criterionType: 'StaticThresholdCriterion'
          dimensions: []
        }
      ]
    }
    actions: [ { actionGroupId: actionGroupId } ]
  }
}
```

## Recipe — Bicep (log alert, dynamic threshold)

```bicep
resource podRestarts 'microsoft.insights/scheduledQueryRules@2025-01-01-preview' = {
  name: 'aks-pod-restart-spike'
  location: resourceGroup().location
  kind: 'LogAlert'
  properties: {
    severity: 2
    enabled: true
    evaluationFrequency: 'PT5M'   // dynamic-threshold log alerts cannot use PT1M
    windowSize: 'PT10M'
    scopes: [ logAnalyticsWorkspaceId ]
    criteria: {
      allOf: [
        {
          query: '''KubePodInventory
            | summarize restartCount = sum(PodRestartCount) by bin(TimeGenerated, 10m), Namespace, Name'''
          metricMeasureColumn: 'restartCount'
          timeAggregation: 'Count'
          dimensions: [ { name: 'Name', operator: 'Include', values: [ '*' ] } ]
          operator: 'GreaterOrLessThan'
          failingPeriods: { numberOfEvaluationPeriods: 4, minFailingPeriodsToAlert: 4 }
          alertSensitivity: 'Medium'
          criterionType: 'DynamicThresholdCriterion'
        }
      ]
    }
    actions: { actionGroups: [ actionGroupId ] }
  }
}
```

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| Alert fires constantly (alert fatigue) | `windowSize` too small; aggregation always returns rows | Larger `windowSize`; raise `minFailingPeriodsToAlert`; use `autoMitigate: true`. |
| Metric alert silently never fires | Resource type doesn't emit that metric, or wrong metric namespace | Confirm in Metrics Explorer first; check supported metrics for the resource type. |
| SMS not arriving | Production rate limit: **1 SMS per 5 minutes** per receiver | Switch high-frequency channels to email/webhook; consolidate alert rules. |
| Dynamic threshold alert doesn't fire on a new resource | Needs 3 days + 30 samples to learn | Expected; wait it out, or use a static-threshold alert in the meantime. |
| Activity-log alert misses events | Activity log alerts are scoped to a single subscription | Create one per subscription. |
| Log alert at `PT1M` frequency errors out | Some KQL operators (`search`, `union`, `take`, `ingestion_time()`, `adx`) aren't supported at 1-minute frequency | Use `PT5M`+ or rewrite the query. |
| Email alerts not delivered to a new address | New email receivers require an OTP confirmation within 30 min of action group creation | Confirm OTP. |

## References

- [Alerts overview](https://learn.microsoft.com/azure/azure-monitor/alerts/alerts-overview)
- [Alert types](https://learn.microsoft.com/azure/azure-monitor/alerts/alerts-types)
- [Create metric alert rules](https://learn.microsoft.com/azure/azure-monitor/alerts/alerts-create-metric-alert-rule)
- [Create log search alert rules](https://learn.microsoft.com/azure/azure-monitor/alerts/alerts-create-log-alert-rule)
- [Dynamic thresholds](https://learn.microsoft.com/azure/azure-monitor/alerts/alerts-dynamic-thresholds)
- [Action groups](https://learn.microsoft.com/azure/azure-monitor/alerts/action-groups)
- [Bicep / ARM for metric alerts](https://learn.microsoft.com/azure/azure-monitor/alerts/resource-manager-alerts-metric)
- [Bicep / ARM for log alerts](https://learn.microsoft.com/azure/azure-monitor/alerts/resource-manager-alerts-log)
