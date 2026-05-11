# networking/

Skills for exposing services to the right consumers and isolating them
from everyone else.

## In scope

- Private endpoints (universal pattern + per-service DNS zones)
- Virtual networks and subnets (planned)
- Azure Front Door (planned)
- Application Gateway and WAF (planned)
- NSGs and route tables (planned)

## Default posture

- Public network access **disabled** on data and platform services.
- Private endpoints in the consumer VNet, with the canonical
  `privatelink.*` private DNS zone linked to the consumer VNet.
- Public ingress only through a managed front door (Front Door, App
  Gateway, or App Service / Container Apps ingress with WAF).
