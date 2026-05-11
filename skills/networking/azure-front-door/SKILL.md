---
name: azure-front-door
description: >
  Provision Azure Front Door Standard/Premium with end-to-end HTTPS,
  WAF Prevention with Microsoft Default Rule Set 2.1 (Premium), proper
  origin host header (the most common 502 cause), HTTPS-only redirect,
  and a managed certificate on a custom domain.
version: 0.1.0
azure_services:
  - Microsoft.Cdn/profiles
  - Microsoft.Cdn/profiles/afdEndpoints
  - Microsoft.Cdn/profiles/originGroups
  - Microsoft.Cdn/profiles/originGroups/origins
  - Microsoft.Cdn/profiles/afdEndpoints/routes
  - Microsoft.Network/FrontDoorWebApplicationFirewallPolicies
tags:
  - networking
  - cdn
  - waf
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/frontdoor/front-door-overview
  - https://learn.microsoft.com/azure/frontdoor/standard-premium/tier-comparison
  - https://learn.microsoft.com/azure/frontdoor/end-to-end-tls
  - https://learn.microsoft.com/azure/frontdoor/private-link
  - https://learn.microsoft.com/azure/web-application-firewall/afds/afds-overview
  - https://learn.microsoft.com/azure/frontdoor/create-front-door-cli
  - https://learn.microsoft.com/azure/frontdoor/best-practices
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2021-06-01"
last_reviewed: 2026-05-11
---

# Azure Front Door Standard/Premium (secure baseline)

## When to use this skill

- The user wants global L7 ingress with WAF, caching, and a managed cert.
- The user is migrating off Front Door (Classic) — it retires
  **March 31, 2027**, and new classic profiles have been blocked since
  March 31, 2025.
- The user needs Private Link to a VNet-isolated origin (Premium only).

## When NOT to use this skill

- The user needs regional L7 ingress only (single region) — use
  [`azure-application-gateway`](../azure-application-gateway/SKILL.md).
- The user needs L4 / TCP ingress — use Azure Load Balancer or Front
  Door Standard/Premium does not handle non-HTTP traffic.
- The user wants mTLS to clients — Front Door doesn't support it; use
  Application Gateway.

## Standard vs Premium

| Feature | Standard | Premium |
| --- | --- | --- |
| Custom WAF rules | ✅ | ✅ |
| Microsoft-managed WAF rules (DRS 2.1+) | ❌ | ✅ |
| Bot protection (Microsoft_BotManagerRuleSet) | ❌ | ✅ |
| Private Link to origin | ❌ | ✅ |
| WAF reports | ❌ | ✅ |

**Pick Premium** when you need managed WAF rules, bot protection, or
Private Link origins. Otherwise Standard is fine.

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| `--sku` | `Premium_AzureFrontDoor` (or `Standard_AzureFrontDoor`) | Choose per the matrix above. |
| Route `httpsRedirect` | `'Enabled'` | Force HTTP → HTTPS at the edge. |
| Route `forwardingProtocol` | `'HttpsOnly'` (or `'MatchRequest'`) | End-to-end TLS to origin. |
| Route `supportedProtocols` | `[ 'Http', 'Https' ]` | Accept HTTP only to redirect it. |
| Origin `originHostHeader` | **the origin's hostname (e.g., `myapp.azurewebsites.net`)** | The single most common 502 cause is omitting / mismatching this. |
| Minimum TLS | TLS 1.2 (TLS 1.0/1.1 are not supported by the platform) | Hard-coded; not configurable. |
| Managed certificate | enabled | Auto-rotates ~45 days before expiry. |
| WAF policy `mode` | start in `'Detection'` for new apps; switch to `'Prevention'` after tuning | Avoids self-DoS from over-eager managed rules. |
| WAF managed rule set (Premium) | `Microsoft_DefaultRuleSet` v `2.1` (action `Block`) | Current recommended ruleset. |
| Origin authentication (Premium) | Private Link to origin where supported | Origin remains private; FD reaches it over the Microsoft backbone. |

## Recipe — Azure CLI

```bash
RG=rg-afd-prod
PROFILE=afd-app-prod
ENDPOINT=app
ORIGIN_GROUP=og-app
ORIGIN=app-origin
ORIGIN_HOST=myapp.azurewebsites.net
WAF=waf-app-prod

az group create -n "$RG" -l global   # AFD profile is global; pick any region

# 1. Profile (Premium) + endpoint
az afd profile create  -g "$RG" --profile-name "$PROFILE" --sku Premium_AzureFrontDoor
az afd endpoint create -g "$RG" --profile-name "$PROFILE" --endpoint-name "$ENDPOINT" --enabled-state Enabled

# 2. Origin group with health probe
az afd origin-group create -g "$RG" --profile-name "$PROFILE" --origin-group-name "$ORIGIN_GROUP" \
  --probe-request-type GET --probe-protocol Https --probe-interval-in-seconds 60 --probe-path /health \
  --sample-size 4 --successful-samples-required 3 --additional-latency-in-milliseconds 50

# 3. Origin — origin-host-header MUST match
az afd origin create -g "$RG" --profile-name "$PROFILE" --origin-group-name "$ORIGIN_GROUP" \
  --origin-name "$ORIGIN" \
  --host-name "$ORIGIN_HOST" \
  --origin-host-header "$ORIGIN_HOST" \
  --priority 1 --weight 1000 --enabled-state Enabled \
  --http-port 80 --https-port 443

# 4. Route (HTTPS redirect, end-to-end TLS)
az afd route create -g "$RG" --profile-name "$PROFILE" --endpoint-name "$ENDPOINT" \
  --route-name route-main --origin-group "$ORIGIN_GROUP" \
  --supported-protocols Http Https \
  --https-redirect Enabled --forwarding-protocol HttpsOnly \
  --link-to-default-domain Enabled

# 5. WAF policy (start in Detection, switch to Prevention after tuning)
az network front-door waf-policy create -g "$RG" -n "$WAF" --sku Premium_AzureFrontDoor \
  --disabled false --mode Detection
az network front-door waf-policy managed-rules add -g "$RG" --policy-name "$WAF" \
  --type Microsoft_DefaultRuleSet --version 2.1 --action Block

# 6. Attach WAF policy to a security policy on the AFD profile
az afd security-policy create -g "$RG" --profile-name "$PROFILE" \
  --security-policy-name secpol-waf \
  --domains $(az afd endpoint show -g "$RG" --profile-name "$PROFILE" --endpoint-name "$ENDPOINT" --query id -o tsv) \
  --waf-policy $(az network front-door waf-policy show -g "$RG" -n "$WAF" --query id -o tsv)
```

## Recipe — Bicep (skeleton)

```bicep
param profileName string
param endpointName string = 'app'
param originHostName string

resource profile 'Microsoft.Cdn/profiles@2021-06-01' = {
  name: profileName
  location: 'global'
  sku: { name: 'Premium_AzureFrontDoor' }
}

resource endpoint 'Microsoft.Cdn/profiles/afdEndpoints@2021-06-01' = {
  parent: profile
  name: endpointName
  location: 'global'
  properties: { enabledState: 'Enabled' }
}

resource originGroup 'Microsoft.Cdn/profiles/originGroups@2021-06-01' = {
  parent: profile
  name: 'og-app'
  properties: {
    loadBalancingSettings: {
      sampleSize: 4
      successfulSamplesRequired: 3
      additionalLatencyInMilliseconds: 50
    }
    healthProbeSettings: {
      probePath: '/health'
      probeRequestType: 'GET'
      probeProtocol: 'Https'
      probeIntervalInSeconds: 60
    }
  }
}

resource origin 'Microsoft.Cdn/profiles/originGroups/origins@2021-06-01' = {
  parent: originGroup
  name: 'app-origin'
  properties: {
    hostName: originHostName
    originHostHeader: originHostName     // CRITICAL — match the origin
    httpPort: 80
    httpsPort: 443
    priority: 1
    weight: 1000
    enabledState: 'Enabled'
  }
}

resource route 'Microsoft.Cdn/profiles/afdEndpoints/routes@2021-06-01' = {
  parent: endpoint
  name: 'route-main'
  properties: {
    originGroup: { id: originGroup.id }
    supportedProtocols: [ 'Http', 'Https' ]
    httpsRedirect: 'Enabled'
    forwardingProtocol: 'HttpsOnly'
    linkToDefaultDomain: 'Enabled'
  }
  dependsOn: [ origin ]
}
```

> The WAF policy lives in the `Microsoft.Network/FrontDoorWebApplicationFirewallPolicies`
> namespace and is attached to the profile via a `securityPolicies` child
> resource. See the [CLI quickstart](https://learn.microsoft.com/azure/frontdoor/create-front-door-cli)
> for the full pattern.

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| Origin returns 502 / "Backend unhealthy" | `originHostHeader` is missing or doesn't match the origin's hostname | Set `originHostHeader: '<origin-hostname>'` on every origin. App Service in particular requires it. |
| Custom domain validation hangs | DNS validation record not in place | Add the TXT record AFD generated for `_dnsauth.<domain>`; wait for propagation. |
| WAF blocks legitimate traffic right after enabling | Managed rules in `Prevention` mode without tuning | Start in `Detection` mode; review WAF logs in Log Analytics; add custom exclusions before flipping to `Prevention`. |
| TLS 1.0/1.1 client can't connect | TLS 1.2 minimum is hard-coded | Update the client; this is not configurable. ([Source](https://learn.microsoft.com/azure/frontdoor/end-to-end-tls)) |
| Trying to add Private Link origin on Standard | Premium-only feature | Upgrade to Premium. |
| Tried to set up Front Door Classic | Classic profile creation has been blocked since March 31, 2025 | Use Standard or Premium. |

## References

- [Front Door overview](https://learn.microsoft.com/azure/frontdoor/front-door-overview)
- [Standard vs Premium tier comparison](https://learn.microsoft.com/azure/frontdoor/standard-premium/tier-comparison)
- [End-to-end TLS](https://learn.microsoft.com/azure/frontdoor/end-to-end-tls)
- [Private Link origin (Premium)](https://learn.microsoft.com/azure/frontdoor/private-link)
- [WAF on Azure Front Door](https://learn.microsoft.com/azure/web-application-firewall/afds/afds-overview)
- [Create Front Door (CLI)](https://learn.microsoft.com/azure/frontdoor/create-front-door-cli)
- [Best practices](https://learn.microsoft.com/azure/frontdoor/best-practices)
