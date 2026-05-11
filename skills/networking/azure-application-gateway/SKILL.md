---
name: azure-application-gateway
description: >
  Provision Azure Application Gateway WAF_v2 with zone-redundant
  autoscaling, the modern TLS policy `AppGwSslPolicy20220101`
  (TLS 1.2+ with TLS 1.3 support), an OWASP CRS 3.2 WAF policy, and a
  custom health probe (the default probes 127.0.0.1, which doesn't
  reach the backend).
version: 0.1.0
azure_services:
  - Microsoft.Network/applicationGateways
  - Microsoft.Network/applicationGatewayWebApplicationFirewallPolicies
  - Microsoft.Network/publicIPAddresses
tags:
  - networking
  - waf
  - layer-7
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/application-gateway/overview
  - https://learn.microsoft.com/azure/application-gateway/configuration-infrastructure
  - https://learn.microsoft.com/azure/application-gateway/application-gateway-ssl-policy-overview
  - https://learn.microsoft.com/azure/application-gateway/application-gateway-autoscaling-zone-redundant
  - https://learn.microsoft.com/azure/application-gateway/application-gateway-probe-overview
  - https://learn.microsoft.com/azure/application-gateway/waf-overview
  - https://learn.microsoft.com/azure/reliability/reliability-application-gateway-v2
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2023-09-01"
last_reviewed: 2026-05-11
---

# Azure Application Gateway v2 (WAF, secure baseline)

## When to use this skill

- Regional L7 ingress with WAF (single Azure region).
- mTLS to clients — Front Door doesn't support it, AppGW does.
- Path-based routing into a VNet-isolated backend (App Service, AKS,
  VMSS) where the user wants to terminate TLS and inspect traffic.

## When NOT to use this skill

- Global anycast ingress, caching, or DDoS at the edge — use
  [`azure-front-door`](../azure-front-door/SKILL.md).
- Pure L4 / TCP — use Azure Load Balancer.
- The legacy v1 SKU — only `Standard_v2` and `WAF_v2` are recommended;
  v1 doesn't support modern WAF policy resources.

## Prerequisites

- A dedicated subnet **just for the Application Gateway** — `/24`
  recommended for `WAF_v2` (supports up to 125 instances). `/26` is the
  hard minimum but caps autoscaling at ~32 instances.
- A Standard SKU **public IP**, ideally zone-redundant
  (`zones: ['1','2','3']`). Basic SKU isn't supported on v2.
- For HTTPS listeners: a TLS cert in PFX or a Key Vault reference.

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| SKU | `WAF_v2` (or `Standard_v2` if no WAF) | v2 only. **WAF policy resource works on `WAF_v2` only.** |
| `zones` | `[ '1', '2', '3' ]` | Zone-redundant deployment in supported regions. |
| Autoscale | `minCapacity: 2`, `maxCapacity: 10–125` | `0` minimum is allowed but cold-start risk. Default `maxCapacity` if unset is 10. |
| `sslPolicy.policyName` | `AppGwSslPolicy20220101` | TLS 1.2+ with TLS 1.3 support. **TLS 1.0 / 1.1 are discontinued as of Aug 31, 2025** (`AppGwSslPolicy20150501` is gone). |
| WAF mode | `'Prevention'` (after starting in `'Detection'` to tune) | Same approach as Front Door. |
| Managed rule set | OWASP CRS `3.2` | Latest CRS at this writing. |
| Backend HTTP setting `protocol` | `Https` for end-to-end TLS | Don't terminate at AppGW and re-emit cleartext. |
| Custom health probe | **always set one**; do not rely on the default | Default probe targets `127.0.0.1` and never reaches the backend — silently broken. ([Source](https://learn.microsoft.com/azure/application-gateway/application-gateway-probe-overview)) |
| `--host-name-from-backend-pool` (HTTP settings) | `true` for App Service backends | App Service requires the host header to match its hostname. |

## Health-probe IP gotcha

The source IP of AppGW health probes is **not** the frontend listener IP:

- **Private backend (PE / private IP):** source = AppGW subnet address space
- **Public backend (FQDN):** source = AppGW frontend public IP

NSG rules on backend subnets must allow the **AppGW subnet**, not just
the frontend IP. ([Source](https://learn.microsoft.com/azure/application-gateway/application-gateway-probe-overview))

## Recipe — Azure CLI

```bash
RG=rg-appgw-prod
LOC=eastus
VNET=vnet-appgw
AGSUB=snet-appgw
PIP=pip-appgw
AG=agw-prod

az group create -n "$RG" -l "$LOC"

# 1. VNet + dedicated AppGW subnet (/24 recommended)
az network vnet create -g "$RG" -n "$VNET" --address-prefixes 10.2.0.0/16 \
  --subnet-name "$AGSUB" --subnet-prefixes 10.2.0.0/24

# 2. Public IP (Standard, zone-redundant)
az network public-ip create -g "$RG" -n "$PIP" --sku Standard \
  --allocation-method Static --zone 1 2 3

# 3. WAF policy (Detection first, then flip to Prevention)
az network application-gateway waf-policy create -g "$RG" -n waf-app-prod
az network application-gateway waf-policy managed-rule rule-set add -g "$RG" \
  --policy-name waf-app-prod --type OWASP --version 3.2
az network application-gateway waf-policy policy-setting update -g "$RG" \
  --policy-name waf-app-prod --mode Detection --state Enabled \
  --max-request-body-size 128 --request-body-check true

# 4. Application Gateway (WAF_v2, autoscale, zone-redundant)
az network application-gateway create -g "$RG" -n "$AG" -l "$LOC" \
  --vnet-name "$VNET" --subnet "$AGSUB" --public-ip-address "$PIP" \
  --sku WAF_v2 --min-capacity 2 --max-capacity 10 \
  --zones 1 2 3 --waf-policy waf-app-prod --priority 1

# 5. TLS policy: TLS 1.2+, TLS 1.3 capable
az network application-gateway ssl-policy set -g "$RG" --gateway-name "$AG" \
  --policy-type Predefined --name AppGwSslPolicy20220101

# 6. Backend (App Service example) + HTTPS settings + custom probe
az network application-gateway address-pool create -g "$RG" --gateway-name "$AG" \
  -n backend-pool --servers myapp.azurewebsites.net

az network application-gateway probe create -g "$RG" --gateway-name "$AG" \
  -n custom-probe --protocol Https --path /health \
  --interval 30 --timeout 30 --threshold 3 --host-name-from-http-settings true

az network application-gateway http-settings create -g "$RG" --gateway-name "$AG" \
  -n backend-https --port 443 --protocol Https \
  --cookie-based-affinity Disabled --timeout 30 \
  --host-name-from-backend-pool true --probe custom-probe
```

## Recipe — Bicep (skeleton)

```bicep
param location string = resourceGroup().location
param minCapacity int = 2
param maxCapacity int = 10

resource pip 'Microsoft.Network/publicIPAddresses@2023-09-01' = {
  name: 'pip-appgw'
  location: location
  sku: { name: 'Standard' }
  zones: [ '1', '2', '3' ]
  properties: { publicIPAllocationMethod: 'Static' }
}

resource waf 'Microsoft.Network/applicationGatewayWebApplicationFirewallPolicies@2023-09-01' = {
  name: 'waf-app-prod'
  location: location
  properties: {
    policySettings: {
      state: 'Enabled'
      mode: 'Detection'           // start here; switch to Prevention after tuning
      requestBodyCheck: true
      maxRequestBodySizeInKb: 128
    }
    managedRules: {
      managedRuleSets: [
        { ruleSetType: 'OWASP', ruleSetVersion: '3.2' }
      ]
    }
    customRules: []
  }
}

resource agw 'Microsoft.Network/applicationGateways@2023-09-01' = {
  name: 'agw-prod'
  location: location
  zones: [ '1', '2', '3' ]
  properties: {
    sku: { name: 'WAF_v2', tier: 'WAF_v2' }
    autoscaleConfiguration: { minCapacity: minCapacity, maxCapacity: maxCapacity }
    firewallPolicy: { id: waf.id }
    sslPolicy: {
      policyType: 'Predefined'
      policyName: 'AppGwSslPolicy20220101'   // TLS 1.2+, TLS 1.3 capable
    }
    // ...gatewayIPConfigurations, frontendIPConfigurations,
    // frontendPorts, listeners, backendAddressPools,
    // backendHttpSettings, probes, requestRoutingRules go here.
  }
}
```

(See the [official quickstart Bicep template](https://learn.microsoft.com/azure/application-gateway/quick-create-bicep)
for the complete property tree.)

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| 502 from AppGW even when backend is healthy | Health probe is the default and probes `127.0.0.1` | Always create a custom probe (`--host-name-from-http-settings true` or set `--host` explicitly). |
| 502 only from one Available Zone | Backend NSG allows the frontend IP but not the AppGW **subnet** | Allow the AppGW subnet's CIDR in the backend NSG. |
| Backend HTTPS to a self-signed cert fails | AppGW doesn't trust the root | Upload the root cert to the AppGW (`backendAddressPools` + `trustedRootCertificates`). |
| Hit instance scale cap during a traffic spike | `maxCapacity` set too low (default 10) | Raise `maxCapacity`; ensure subnet is `/24` so it has room to scale to 125. |
| TLS 1.0/1.1 client suddenly can't connect after Aug 31, 2025 | `AppGwSslPolicy20150501` was discontinued | Switch to `AppGwSslPolicy20220101`. |
| WAF policy created but not applied | Policy not associated with the gateway (or with WAF_v1) | WAF policy resource only works with `WAF_v2`. Set `firewallPolicy: { id: waf.id }`. |

## References

- [Application Gateway overview](https://learn.microsoft.com/azure/application-gateway/overview)
- [Configuration: subnet sizing](https://learn.microsoft.com/azure/application-gateway/configuration-infrastructure)
- [SSL policy overview](https://learn.microsoft.com/azure/application-gateway/application-gateway-ssl-policy-overview)
- [Autoscaling and zone redundancy](https://learn.microsoft.com/azure/application-gateway/application-gateway-autoscaling-zone-redundant)
- [Health probe overview](https://learn.microsoft.com/azure/application-gateway/application-gateway-probe-overview)
- [WAF overview](https://learn.microsoft.com/azure/application-gateway/waf-overview)
- [Reliability for App Gateway v2](https://learn.microsoft.com/azure/reliability/reliability-application-gateway-v2)
