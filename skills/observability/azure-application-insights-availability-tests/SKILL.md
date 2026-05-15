---
name: azure-application-insights-availability-tests
description: >
  Synthetic uptime monitoring for App Insights. Use **Standard tests**
  (URL ping is deprecated; retires 2026-09-30). Run from ≥ 5 locations,
  alert at `n − 2`, retry enabled, SSL check + proactive cert expiry,
  and the **mandatory `hidden-link:<componentId>` tag** so the test
  shows up in the Availability blade. Private endpoints need
  `TrackAvailability()` from a VNet-integrated Function instead.
version: 0.1.0
azure_services:
  - Microsoft.Insights/webtests
  - Microsoft.Insights/components
  - Microsoft.Insights/metricAlerts
tags:
  - observability
  - synthetic-monitoring
  - availability
sources:
  - https://learn.microsoft.com/azure/azure-monitor/app/availability-overview
  - https://learn.microsoft.com/azure/azure-monitor/app/availability-standard-tests
  - https://learn.microsoft.com/azure/templates/microsoft.insights/webtests
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2022-06-15"
last_reviewed: 2026-05-15
---

# Application Insights — availability tests

## When to use this skill

- You need synthetic external uptime checks against a public HTTP(S)
  endpoint.
- You want an alert when a site goes down across multiple geographies.

## When NOT to use this skill

- Endpoint is **private** (behind a private endpoint or in a VNet) —
  use **custom `TrackAvailability()`** in a VNet-integrated Azure
  Function (Premium plan) instead.
- Multi-step transactional flows — multi-step web tests are deprecated;
  use Azure Load Testing or `TrackAvailability()`.

## Test types

| Type | Status | Notes |
| --- | --- | --- |
| **Standard test** | ✅ recommended | single HTTP/HTTPS request; SSL + cert-lifetime check; custom headers; content match |
| **URL ping test** | ⚠️ **deprecated** — being **removed 2026-09-30** | migrate now |
| **Custom `TrackAvailability()`** | available (Classic API archived) | Function-driven; required for private endpoints |
| **Multi-step web tests** | ⚠️ deprecated | being phased out |

## Standard test settings

| Setting | Notes |
| --- | --- |
| HTTP verbs | `GET`, `HEAD`, `POST` |
| Custom headers | `Host` and `User-Agent` are **reserved** (silently ignored if you set them); pass `Authorization: Bearer <token>` for OAuth-protected endpoints |
| Follow redirects | up to 10 |
| Parse dependent requests | up to 15 (images, scripts, CSS) — stricter pass criteria |
| Content match | plain string, **case-sensitive**, **English characters only** |
| SSL check | validates cert on the **final** redirect URL only |
| Proactive SSL lifetime check | alert N days before cert expiry |
| Test timeout | 30 s default |
| Retry on failure | recommended; reports failure only after **3 successive** failures (~80 % of transient failures vanish on retry) |
| Frequency | 5 / 10 / 15 min |
| Locations | up to 16; **minimum 5 recommended** |
| Config propagation | up to **20 min** to all test agents |
| Max tests per App Insights resource | **100** |

## Alert pattern

| Setting | Recommendation |
| --- | --- |
| Alert location threshold | `n − 2` (e.g. **3 of 5**) |
| Alert type | near-real-time / state-based — fires once on DOWN, once on RECOVER |
| Custom rule aggregation | up to 24 h (default rule: 6 h) |
| Custom rule frequency | up to 1 h (default: 15 min) |

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| `RetryEnabled` | `true` | Removes ~80 % of false positives. |
| `SSLCheck` | `true` | Catches expired / mis-installed certs. |
| `SSLCertRemainingLifetimeCheck` | `7` (days) or more | Alerts before cert expires. |
| Test locations | `≥ 5` | Differentiates site outage from regional network problem. |
| Alert threshold | `n − 2` (`failedLocationCount: 3` for 5 locations) | Reduces noise. |
| `hidden-link:<componentId>` tag | **REQUIRED** on the webtest | Without it, the test doesn't appear in the App Insights Availability blade. |
| Auth tokens in headers | use `Authorization: Bearer ...` header (not URL query) | Don't expose tokens in URLs / logs. |
| Endpoint visibility | public | Standard tests can't reach private endpoints — use `TrackAvailability()` from a VNet-integrated Function. |
| Quota awareness | ≤ 100 tests / App Insights resource | Hard limit. |

## Recipe — Bicep (Standard test + n−2 metric alert)

```bicep
param location string = resourceGroup().location
param testName string = 'my-availability-test'
param testUrl string  = 'https://myapp.example.com/health'
param appInsightsName string

resource ai 'Microsoft.Insights/components@2020-02-02' existing = {
  name: appInsightsName
}

resource webTest 'Microsoft.Insights/webtests@2022-06-15' = {
  name: testName
  location: location
  kind: 'standard'
  // CRITICAL — without this tag the test won't show in the Availability blade
  tags: {
    'hidden-link:${ai.id}': 'Resource'
  }
  properties: {
    Name: testName
    SyntheticMonitorId: testName
    Kind: 'standard'
    Enabled: true
    Frequency: 300                 // 5 min per location
    Timeout: 30
    RetryEnabled: true             // strongly recommended
    Locations: [
      { Id: 'us-va-ash-azr' }      // East US
      { Id: 'us-tx-sn1-azr' }      // South Central US
      { Id: 'us-ca-sjc-azr' }      // West US
      { Id: 'emea-nl-ams-azr' }    // West Europe
      { Id: 'apac-sg-sin-azr' }    // Southeast Asia
    ]
    Request: {
      RequestUrl: testUrl
      HttpVerb: 'GET'
      FollowRedirects: true
      ParseDependentRequests: false
      // Headers: [ { key: 'Authorization', value: 'Bearer <token>' } ]
    }
    ValidationRules: {
      ExpectedHttpStatusCode: 200
      IgnoreHttpStatusCode: false
      SSLCheck: true
      SSLCertRemainingLifetimeCheck: 7
      ContentValidation: {
        ContentMatch: 'healthy'        // English characters only, case-sensitive
        IgnoreCase: false
        PassIfTextFound: true
      }
    }
  }
}

// Alert when 3 of 5 locations fail (n - 2)
resource alert 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: '${testName}-alert'
  location: 'global'
  properties: {
    description: 'Availability — n-2 location threshold'
    severity: 2
    enabled: true
    scopes: [ webTest.id, ai.id ]
    evaluationFrequency: 'PT1M'
    windowSize: 'PT5M'
    autoMitigate: true
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.WebtestLocationAvailabilityCriteria'
      webTestId: webTest.id
      componentId: ai.id
      failedLocationCount: 3
    }
    // actions: [ { actionGroupId: '/subscriptions/.../actionGroups/<name>' } ]
  }
}
```

## Recipe — Azure CLI (`az rest` to the ARM API)

```bash
RG=ai-rg
LOC=eastus
AI=myappinsights
TEST=my-availability-test
URL=https://myapp.example.com/health

AI_ID=$(az monitor app-insights component show -g "$RG" --app "$AI" --query id -o tsv)
SUB=$(az account show --query id -o tsv)

az rest --method PUT \
  --uri "https://management.azure.com/subscriptions/$SUB/resourceGroups/$RG/providers/microsoft.insights/webtests/$TEST?api-version=2022-06-15" \
  --body "{
    \"location\":\"$LOC\",
    \"kind\":\"standard\",
    \"tags\":{\"hidden-link:$AI_ID\":\"Resource\"},
    \"properties\":{
      \"Name\":\"$TEST\",\"SyntheticMonitorId\":\"$TEST\",\"Kind\":\"standard\",
      \"Enabled\":true,\"Frequency\":300,\"Timeout\":30,\"RetryEnabled\":true,
      \"Locations\":[
        {\"Id\":\"us-va-ash-azr\"},{\"Id\":\"us-tx-sn1-azr\"},
        {\"Id\":\"us-ca-sjc-azr\"},{\"Id\":\"emea-nl-ams-azr\"},
        {\"Id\":\"apac-sg-sin-azr\"}
      ],
      \"Request\":{\"RequestUrl\":\"$URL\",\"HttpVerb\":\"GET\",\"FollowRedirects\":true,\"ParseDependentRequests\":false},
      \"ValidationRules\":{\"ExpectedHttpStatusCode\":200,\"SSLCheck\":true,\"SSLCertRemainingLifetimeCheck\":7}
    }
  }"
```

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| URL ping tests get deleted on 2026-09-30 | URL ping deprecation | Migrate every URL ping test to a Standard test before the date |
| Test missing from App Insights Availability blade | `hidden-link:<componentId>` tag missing or wrong componentId | Add the tag exactly as `hidden-link:/subscriptions/.../components/<name>: Resource` |
| Noisy false-positive alerts | < 5 locations or threshold too low | Use ≥ 5 locations and `n − 2` threshold |
| Continuous alerts fire every cycle | Configured against legacy classic alert rules | Use unified (near-real-time) alert rule — state-based by default |
| Content match fails for non-English text | `ContentMatch` is English chars only | Use `TrackAvailability()` for richer content validation |
| Multi-step web tests stopped working | Deprecated; phased out | Migrate to `TrackAvailability()` Function or Azure Load Testing |
| Standard test can't reach a private endpoint | Microsoft-hosted agents are on the public internet | Custom `TrackAvailability()` in a VNet-integrated Function (Premium plan) |
| Bigger-than-expected bill from `TrackAvailability()` | Function execution + App Insights ingestion costs | Prefer Standard tests; budget for Function + ingestion if custom is required |
| Config change has no effect for ~20 min | Config propagation is up to 20 min | Disable (don't delete) the test during maintenance |
| `Host` / `User-Agent` header customization ignored | These are reserved | Use separate tests per hostname for host-header routed services |
| 101st test fails to create | Hard limit of 100 tests per App Insights resource | Distribute across multiple App Insights resources |

## API versions

| Resource | Pinned |
| --- | --- |
| `Microsoft.Insights/webtests` | `2022-06-15` (verified latest stable) |
| `Microsoft.Insights/components` | `2020-02-02` (workspace-based App Insights) |
| `Microsoft.Insights/metricAlerts` | `2018-03-01` |

## References

- [Availability overview](https://learn.microsoft.com/azure/azure-monitor/app/availability-overview)
- [Standard tests](https://learn.microsoft.com/azure/azure-monitor/app/availability-standard-tests)
- [`webtests` template reference](https://learn.microsoft.com/azure/templates/microsoft.insights/webtests)
