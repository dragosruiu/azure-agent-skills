---
name: azure-application-insights
description: >
  Provision Azure Application Insights as workspace-based (the only
  supported mode for new resources), use the connection string for
  ingestion (not the deprecated instrumentation key), enable Entra-based
  ingestion (Monitoring Metrics Publisher), and wire App Service
  autoinstrumentation.
version: 0.1.0
azure_services:
  - Microsoft.Insights/components
  - Microsoft.OperationalInsights/workspaces
tags:
  - observability
  - telemetry
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/azure-monitor/app/app-insights-overview
  - https://learn.microsoft.com/azure/azure-monitor/app/create-workspace-resource
  - https://learn.microsoft.com/azure/azure-monitor/app/connection-strings
  - https://learn.microsoft.com/azure/azure-monitor/app/sampling
  - https://learn.microsoft.com/azure/azure-monitor/app/opentelemetry-configuration
  - https://learn.microsoft.com/azure/azure-monitor/app/azure-ad-authentication
  - https://learn.microsoft.com/azure/azure-monitor/app/live-stream
  - https://learn.microsoft.com/azure/azure-monitor/app/azure-web-apps-net-core
validated_with:
  az_cli: ">=2.71.0"
  api_version: "2020-02-02"
last_reviewed: 2026-05-11
---

# Azure Application Insights (workspace-based)

## When to use this skill

- The user is provisioning App Insights for a new app on App Service,
  Functions, Container Apps, AKS, or anywhere the OTel SDK runs.
- The user is migrating from a "classic" (non-workspace) AI resource and
  hitting deprecation warnings.
- The user is putting an instrumentation key in app settings — replace
  with a connection string and Entra ID auth.

## When NOT to use this skill

- The user wants infrastructure metrics only (no app-side
  instrumentation) — use Azure Monitor metrics + diagnostic settings on
  the resource directly. See [`azure-monitor-diagnostic-settings`](../azure-monitor-diagnostic-settings/SKILL.md).
- Browser/JavaScript SDK with `disableLocalAuth: true` — that combo is
  **not supported**; the JS SDK can't acquire Entra tokens directly.

## Prerequisites

- A Log Analytics workspace (LAW) in the same region.
- `az extension add --name application-insights` (the AI subcommands ship
  as an extension; min `az` `2.71.0`).

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| **Mode** | **Workspace-based** (`WorkspaceResourceId` set on creation) | Only mode supported for new resources. Classic AI is deprecated. |
| `kind` | `'web'` | Standard for web/server-side apps. |
| `properties.Application_Type` | `'web'` | Same. |
| `properties.IngestionMode` | `'LogAnalytics'` | Workspace-based ingestion (vs `'ApplicationInsights'` classic). |
| App setting | `APPLICATIONINSIGHTS_CONNECTION_STRING` (full connection string) | Required in sovereign clouds. **Do not use `APPINSIGHTS_INSTRUMENTATIONKEY`.** ([Source](https://learn.microsoft.com/azure/azure-monitor/app/connection-strings)) |
| App setting (Entra ID) | `APPLICATIONINSIGHTS_AUTHENTICATION_STRING=Authorization=AAD` (or `Authorization=AAD;ClientId=<client-id>` for user-assigned MI) | Entra-based ingestion; eliminates iKey-as-secret. ([Source](https://learn.microsoft.com/azure/azure-monitor/app/azure-ad-authentication)) |
| `properties.DisableLocalAuth` | `true` for production | Forces Entra ingestion. **Unsupported for browser/JS SDK and Python App Service autoinstrumentation** — leave `false` for those. |
| RBAC | Grant **Monitoring Metrics Publisher** on the AI resource to the app's MI | Lets the MI ingest telemetry via Entra. |
| Sampling | OTel `microsoft.fixed_percentage` at 10% (`OTEL_TRACES_SAMPLER_ARG=0.1`) for high-volume; rate-limited (`microsoft.rate_limited`) for capped budgets | Controls cost without dropping randomly mid-trace. |

## Recipe — Azure CLI

```bash
RG=rg-app-prod
LOC=eastus
LAW=law-app-prod
AI=appi-app-prod
APP=app-app-prod
PRINCIPAL_ID=<objectId-of-app-managed-identity>

az extension add --name application-insights --upgrade

# 1. Log Analytics workspace
az monitor log-analytics workspace create \
  -g "$RG" -l "$LOC" -n "$LAW" --retention-time 90
LAW_ID=$(az monitor log-analytics workspace show -g "$RG" -n "$LAW" --query id -o tsv)

# 2. Workspace-based App Insights
az monitor app-insights component create \
  -g "$RG" -l "$LOC" -a "$AI" \
  --kind web --application-type web \
  --workspace "$LAW_ID"

# 3. Connection string + grant Monitoring Metrics Publisher to the MI
CONN=$(az monitor app-insights component show -g "$RG" -a "$AI" --query connectionString -o tsv)
AI_ID=$(az monitor app-insights component show -g "$RG" -a "$AI" --query id -o tsv)
az role assignment create \
  --assignee-object-id "$PRINCIPAL_ID" \
  --assignee-principal-type ServicePrincipal \
  --role "Monitoring Metrics Publisher" --scope "$AI_ID"

# 4. App Service autoinstrumentation (Linux: ~3, Windows: ~2)
az webapp config appsettings set -g "$RG" -n "$APP" --settings \
  APPLICATIONINSIGHTS_CONNECTION_STRING="$CONN" \
  ApplicationInsightsAgent_EXTENSION_VERSION="~3" \
  XDT_MicrosoftApplicationInsights_Mode="recommended" \
  XDT_MicrosoftApplicationInsights_PreemptSdk="1" \
  APPLICATIONINSIGHTS_AUTHENTICATION_STRING="Authorization=AAD"
```

## Recipe — Bicep

```bicep
param location string = resourceGroup().location
param appInsightsName string
param logAnalyticsName string

resource law 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: logAnalyticsName
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 90
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: law.id          // makes it workspace-based
    IngestionMode: 'LogAnalytics'
    DisableLocalAuth: false              // set true once all SDKs support Entra ingestion
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

output connectionString string = appInsights.properties.ConnectionString
```

## OTel sampling

```bash
# Fixed-rate: 10%
export OTEL_TRACES_SAMPLER=microsoft.fixed_percentage
export OTEL_TRACES_SAMPLER_ARG=0.1

# OR rate-limited: max 1.5 traces/sec
export OTEL_TRACES_SAMPLER=microsoft.rate_limited
export OTEL_TRACES_SAMPLER_ARG=1.5
```

## KQL starter set

Run in the LAW associated with the AI resource.

```kusto
// Validate the effective sampling rate
union requests, dependencies, pageViews, exceptions, traces
| where timestamp > ago(1d)
| summarize RetainedPercentage = 100/avg(itemCount) by bin(timestamp, 1h), itemType

// Recent failed requests
requests
| where timestamp > ago(1h) and success == false
| project timestamp, name, url, resultCode, duration, cloud_RoleName
| order by timestamp desc

// Exceptions with messages
exceptions
| where timestamp > ago(1h)
| project timestamp, type, outerMessage, innermostMessage, operation_Id
| order by timestamp desc

// Outbound dependency failures
dependencies
| where timestamp > ago(1h) and success == false
| project timestamp, name, target, resultCode, duration, type
| order by timestamp desc
```

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| No telemetry in the portal | App is reading `APPINSIGHTS_INSTRUMENTATIONKEY` (deprecated) | Set `APPLICATIONINSIGHTS_CONNECTION_STRING`. ([Source](https://learn.microsoft.com/azure/azure-monitor/app/connection-strings)) |
| Telemetry stops after `DisableLocalAuth: true` | Browser JS SDK or Python App Service autoinstrumentation in use | Revert `DisableLocalAuth` for those scenarios. ([Source](https://learn.microsoft.com/azure/azure-monitor/app/azure-ad-authentication)) |
| Distributed traces are missing spans | Sampling too aggressive (e.g., `OTEL_TRACES_SAMPLER_ARG=0.01`) | Use `microsoft.fixed_percentage` at higher rate; sample at the SDK source, not at ingestion. ([Source](https://learn.microsoft.com/azure/azure-monitor/app/sampling)) |
| App Service autoinstrumentation: no data | Missing `ApplicationInsightsAgent_EXTENSION_VERSION` or wrong version (`~2` Windows, `~3` Linux) | Set all four required settings. ([Source](https://learn.microsoft.com/azure/azure-monitor/app/azure-web-apps-net-core)) |
| Live Metrics blank | ASP.NET (Framework) doesn't support OTel Live Metrics | Use ASP.NET Core, Java, Node.js, or Python; or check `EnableLiveMetrics`. ([Source](https://learn.microsoft.com/azure/azure-monitor/app/live-stream)) |
| Live Metrics auth warning after Sept 30 2025 | API keys for Live Metrics streaming are retired | Switch to Entra ID auth. |
| AI created as classic (no LAW link) | `--workspace` omitted on create / `WorkspaceResourceId` missing in Bicep | Always pass workspace; classic mode is deprecated. ([Source](https://learn.microsoft.com/azure/azure-monitor/app/create-workspace-resource)) |

## References

- [Application Insights overview](https://learn.microsoft.com/azure/azure-monitor/app/app-insights-overview)
- [Create workspace-based AI](https://learn.microsoft.com/azure/azure-monitor/app/create-workspace-resource)
- [Connection strings](https://learn.microsoft.com/azure/azure-monitor/app/connection-strings)
- [Sampling](https://learn.microsoft.com/azure/azure-monitor/app/sampling)
- [OpenTelemetry configuration](https://learn.microsoft.com/azure/azure-monitor/app/opentelemetry-configuration)
- [Microsoft Entra authentication](https://learn.microsoft.com/azure/azure-monitor/app/azure-ad-authentication)
- [Live Metrics stream](https://learn.microsoft.com/azure/azure-monitor/app/live-stream)
- [App Service autoinstrumentation](https://learn.microsoft.com/azure/azure-monitor/app/azure-web-apps-net-core)
