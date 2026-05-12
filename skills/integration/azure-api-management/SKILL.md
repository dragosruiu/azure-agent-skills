---
name: azure-api-management
description: >
  Provision Azure API Management (Premium classic, or Standard v2 /
  Premium v2 for the modern simpler SKUs) with system-assigned MI for
  backend auth, validate-jwt / validate-azure-ad-token policies for
  Entra-protected APIs, Key Vault-backed named values, and TLS 1.0/1.1
  explicitly disabled.
version: 0.1.0
azure_services:
  - Microsoft.ApiManagement/service
  - Microsoft.ApiManagement/service/apis
  - Microsoft.ApiManagement/service/policies
  - Microsoft.ApiManagement/service/namedValues
tags:
  - integration
  - api-gateway
  - apim
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/api-management/api-management-key-concepts
  - https://learn.microsoft.com/azure/api-management/api-management-features
  - https://learn.microsoft.com/azure/api-management/v2-service-tiers-overview
  - https://learn.microsoft.com/azure/api-management/api-management-howto-use-managed-service-identity
  - https://learn.microsoft.com/azure/api-management/api-management-howto-protect-backend-with-aad
  - https://learn.microsoft.com/azure/api-management/api-management-howto-properties
  - https://learn.microsoft.com/azure/api-management/private-endpoint
  - https://learn.microsoft.com/azure/templates/microsoft.apimanagement/service
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2024-05-01"
last_reviewed: 2026-05-12
---

# Azure API Management (APIM)

## When to use this skill

- Centralized gateway for many backend APIs with shared auth, rate
  limiting, transformation, caching, and a developer portal.
- Protecting backends with Microsoft Entra ID JWT validation.
- Multi-region / multi-tenant API publishing on the same gateway.

## When NOT to use this skill

- Serving a single API to a single audience — App Service / Container
  Apps / Functions with a custom domain is simpler.
- Regional L7 with WAF + path routing only — see
  [`azure-application-gateway`](../../networking/azure-application-gateway/SKILL.md).
- Global edge ingress + WAF — see
  [`azure-front-door`](../../networking/azure-front-door/SKILL.md).

## SKU picker (v2 SKUs are GA from API `2024-05-01`)

| Need | Pick |
| --- | --- |
| Dev / non-prod, no SLA | Developer (classic) |
| Production, modest scale, **private endpoint + outbound VNet integration**, simpler ops than v1 | **Standard v2** |
| Enterprise: full **VNet injection**, multi-region active-active, AZ-redundant, workspaces | **Premium v2** (or Premium classic for legacy needs) |
| Pay-per-call only, simple consumption | Consumption (no SLA, limited features) |
| Feature parity with the "old" Premium (e.g., self-hosted gateways, multi-region) | Premium classic |

> **For new builds, prefer v2 SKUs** — simpler networking model and
> faster scale ops. Capability gaps with classic Premium are narrowing
> but not zero — verify your specific need (e.g., self-hosted gateway
> support) before committing.

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| `sku.name` | `Premium` (classic) or `PremiumV2` / `StandardV2` | Lower SKUs lack PE / VNet integration. |
| `identity.type` | `'SystemAssigned'` | For named-value KV lookups and `authentication-managed-identity` policies on backend calls. |
| `properties.publicNetworkAccess` | `'Disabled'` (after PE provisioned) | Pair with PE to `privatelink.azure-api.net`. |
| `customProperties` (TLS hardening) | disable TLS 1.0 + 1.1 on **both** gateway and backend protocols (4 keys) | Required for any current security baseline; defaults are not all-off historically. |
| `virtualNetworkType` (Premium classic) | `'Internal'` (gateway only reachable from VNet) or `'External'` (gateway has a public IP but is in your VNet) | v2 SKUs use a different networking model — they support PE + outbound VNet integration without classic VNet injection. |
| Named values | **Key Vault references**, not inline secrets | Centralizes rotation. APIM MI needs `Key Vault Secrets User`. |
| API protection | `validate-azure-ad-token` policy (or `validate-jwt`) on every protected operation | Reject unauthenticated requests at the gateway. |
| Backend auth | `authentication-managed-identity` policy with the `resource` parameter | MI calls the backend with an Entra token. |
| Rate-limit | a sensible policy: `rate-limit-by-key` keyed by subscription / IP / user | Without it, one client can starve everyone. |
| Subscription required | `true` for all "internal" APIs | Subscription keys are still useful for client identification even with Entra. |

## TLS hardening properties

```bicep
customProperties: {
  'Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Protocols.Tls10':         'false'
  'Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Protocols.Tls11':         'false'
  'Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Backend.Protocols.Tls10': 'false'
  'Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Backend.Protocols.Tls11': 'false'
}
```

## Recipe — Azure CLI

```bash
RG=rg-apim-prod
LOC=eastus
APIM=apim-app-prod
KV=kv-apim-prod

az group create -n "$RG" -l "$LOC"

# 1. Create APIM (Premium for full features) — provisioning takes 30–60 min for classic
az apim create -g "$RG" -n "$APIM" -l "$LOC" \
  --sku-name Premium --sku-capacity 1 \
  --publisher-email admin@contoso.com --publisher-name Contoso \
  --no-wait

# 2. Enable system MI
az apim update -g "$RG" -n "$APIM" --enable-managed-identity true

# 3. Grant MI Key Vault Secrets User on the vault
APIM_MI=$(az apim show -g "$RG" -n "$APIM" --query identity.principalId -o tsv)
KV_ID=$(az keyvault show -g "$RG" -n "$KV" --query id -o tsv)
az role assignment create \
  --assignee-object-id "$APIM_MI" --assignee-principal-type ServicePrincipal \
  --role "Key Vault Secrets User" --scope "$KV_ID"

# 4. Private endpoint (groupId = Gateway)
APIM_ID=$(az apim show -g "$RG" -n "$APIM" --query id -o tsv)
az network private-endpoint create -g "$RG" -n "pe-$APIM" \
  --vnet-name vnet-app --subnet snet-pe \
  --private-connection-resource-id "$APIM_ID" \
  --connection-name "pec-$APIM" --group-id Gateway
az network private-dns zone create -g "$RG" -n privatelink.azure-api.net
# (link the zone to consumer VNets and add DNS zone group on the PE)

# 5. After PE works, disable public access
az apim update -g "$RG" -n "$APIM" --public-network-access Disabled
```

## Recipe — Bicep (Premium classic, Internal VNet, system MI, TLS hardened)

```bicep
param apimName string
param location string = resourceGroup().location
param publisherEmail string
param publisherName string
param subnetId string

resource apim 'Microsoft.ApiManagement/service@2024-05-01' = {
  name: apimName
  location: location
  identity: { type: 'SystemAssigned' }
  sku: { name: 'Premium', capacity: 1 }
  properties: {
    publisherEmail: publisherEmail
    publisherName: publisherName
    publicNetworkAccess: 'Disabled'           // pair with PE
    virtualNetworkType: 'Internal'            // gateway only reachable from VNet
    virtualNetworkConfiguration: { subnetResourceId: subnetId }
    customProperties: {
      'Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Protocols.Tls10':         'false'
      'Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Protocols.Tls11':         'false'
      'Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Backend.Protocols.Tls10': 'false'
      'Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Backend.Protocols.Tls11': 'false'
    }
  }
}
```

## Policy snippets

**Validate Microsoft Entra JWT on inbound:**
```xml
<inbound>
  <validate-azure-ad-token tenant-id="{{tenant-id}}" failed-validation-httpcode="401">
    <client-application-ids>
      <application-id>{{client-app-id}}</application-id>
    </client-application-ids>
    <audiences>
      <audience>api://my-api</audience>
    </audiences>
  </validate-azure-ad-token>
  <base />
</inbound>
```

**Call backend with the APIM MI token (the `resource` parameter is required):**
```xml
<inbound>
  <authentication-managed-identity resource="api://my-backend" />
  <set-backend-service base-url="https://backend.internal.contoso.com" />
  <base />
</inbound>
```

**Rate-limit per subscription:**
```xml
<inbound>
  <rate-limit-by-key calls="100" renewal-period="60" counter-key="@(context.Subscription.Id)" />
  <base />
</inbound>
```

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| Backend 401 with `authentication-managed-identity` | Missing the `resource` attribute | Always specify `resource="<backend app id URI>"`. |
| Named-value KV reference fails | APIM MI lacks `Key Vault Secrets User` on the vault | Grant the role on the vault scope. |
| `rate-limit-by-key` returns 500 | Counter key references something that's null (e.g., `context.Subscription.Key` when no subscription is enforced) | Use a key that always exists (`context.Request.IpAddress`, `context.User.Id`). |
| v2 SKU not available in chosen region | Regional rollout incomplete | Pick a different region, or use Premium classic. |
| TLS 1.0/1.1 client suddenly can't connect | The hardening properties are now in effect | That's the point — update the client. |
| `validate-headers` policy doesn't enforce | API was imported with an old management-API version | Re-import with `2021-01-01-preview` or later. |
| Self-hosted gateway not allowed on the SKU | Self-hosted gateways are Premium classic only (and select v2 tiers) — verify the SKU | Move to a SKU that supports it, or use a different deployment model. |

## References

- [APIM key concepts](https://learn.microsoft.com/azure/api-management/api-management-key-concepts)
- [Features matrix](https://learn.microsoft.com/azure/api-management/api-management-features)
- [v2 service tiers overview](https://learn.microsoft.com/azure/api-management/v2-service-tiers-overview)
- [Use managed service identity](https://learn.microsoft.com/azure/api-management/api-management-howto-use-managed-service-identity)
- [Protect backend with Entra ID](https://learn.microsoft.com/azure/api-management/api-management-howto-protect-backend-with-aad)
- [Named values](https://learn.microsoft.com/azure/api-management/api-management-howto-properties)
- [Private endpoint](https://learn.microsoft.com/azure/api-management/private-endpoint)
- [`Microsoft.ApiManagement/service` template](https://learn.microsoft.com/azure/templates/microsoft.apimanagement/service)
