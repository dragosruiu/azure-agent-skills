# governance/

Skills for naming, tagging, scoping, and policing resources so a fleet
stays manageable.

## In scope

- Azure naming and tagging (CAF abbreviations + required-tag set)
- Azure Policy baseline (planned)
- Resource group strategy (planned — per environment vs per blast radius)
- Cost management tags and budgets (planned)
- Management groups and subscription strategy (planned)

## Default posture

- Resource names follow the Cloud Adoption Framework abbreviation
  table: `rg-`, `kv-`, `app-`, `func-`, `cae-`, `aks-`, `psql-`,
  `cosmos-`, `st…` (no hyphens, ≤ 24 chars), etc.
- Required tags on every resource and resource group:
  `environment`, `costCenter`, `owner`, `application`, `dataClassification`.
- Tag inheritance from RG via Azure Policy (`Inherit a tag from the
  resource group if missing`) — does not retroactively tag existing
  resources; remediation task required.
