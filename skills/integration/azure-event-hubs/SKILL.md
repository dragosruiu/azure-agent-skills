---
name: azure-event-hubs
description: >
  Provision Azure Event Hubs with secure defaults: Standard tier with
  auto-inflate, `disableLocalAuth: true`, partition planning (immutable
  on Standard, set up front), Capture to Storage / Data Lake, the Kafka
  surface on port 9093, and the RBAC Data Sender / Receiver roles.
version: 0.1.0
azure_services:
  - Microsoft.EventHub/namespaces
  - Microsoft.EventHub/namespaces/eventhubs
  - Microsoft.EventHub/namespaces/eventhubs/consumergroups
tags:
  - integration
  - streaming
  - kafka
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/event-hubs/event-hubs-about
  - https://learn.microsoft.com/azure/event-hubs/event-hubs-features
  - https://learn.microsoft.com/azure/event-hubs/event-hubs-quotas
  - https://learn.microsoft.com/azure/event-hubs/authenticate-application
  - https://learn.microsoft.com/azure/event-hubs/event-hubs-capture-overview
  - https://learn.microsoft.com/azure/event-hubs/event-hubs-for-kafka-ecosystem-overview
  - https://learn.microsoft.com/azure/event-hubs/event-hubs-auto-inflate
  - https://learn.microsoft.com/azure/event-hubs/event-hubs-quickstart-cli
  - https://learn.microsoft.com/azure/templates/microsoft.eventhub/namespaces
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2024-01-01"
last_reviewed: 2026-05-11
---

# Azure Event Hubs (secure baseline)

## When to use this skill

- The user is ingesting high-rate telemetry or events (millions/sec).
- The user wants to use Event Hubs as a **Kafka broker** (port 9093,
  SASL).
- The user wants to capture the stream to Storage / Data Lake for batch
  processing.

## When NOT to use this skill

- The user wants pub/sub with managed delivery to specific endpoints —
  use Event Grid.
- The user wants exactly-once command processing — use Service Bus.

## Tier picker

| Need | Tier |
| --- | --- |
| Dev, < 20 TUs, partitions immutable after create | **Standard** |
| Higher throughput, predictable performance, dynamic partitions | **Premium** |
| Massive sustained throughput, dedicated cluster | **Dedicated** |
| Geo-replication, customer-managed keys, large retention | Premium / Dedicated |

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| `sku.name` | `'Standard'` for typical, `'Premium'` for prod | Premium adds dynamic partitions, dedicated capacity slices. |
| `disableLocalAuth` | `true` | Disables SAS keys; forces Entra ID. (CLI: verify with `az eventhubs namespace update --help`; `--disable-local-auth true` follows the SB pattern.) |
| `minimumTlsVersion` | `'1.2'` | Reject older TLS. |
| `publicNetworkAccess` | `'Disabled'` | Pair with PE to `privatelink.servicebus.windows.net` (yes, EH uses the SB zone). |
| `zoneRedundant` | `true` (default in supported regions on Standard+) | AZ failure tolerance. |
| `isAutoInflateEnabled` | `true` (Standard only) | TUs scale up to `maximumThroughputUnits` automatically. **Doesn't auto-deflate** — set ceiling carefully. |
| Hub `partitionCount` | **plan up front, 4–32 typical** | **Cannot be increased on Standard after creation** (Premium allows it). Higher = more parallelism, can't decrease. |
| Hub `messageRetentionInDays` | `1`–`7` (Standard) | Standard caps at 7. |
| `kafkaEnabled` | `true` | Enables the Kafka surface on port 9093. |

## RBAC roles

| Role | Use case |
| --- | --- |
| `Azure Event Hubs Data Sender` | Producers. |
| `Azure Event Hubs Data Receiver` | Consumers. |
| `Azure Event Hubs Data Owner` | Manage entities + send + receive. |

Scope at the namespace, hub, or consumer-group level.

## Recipe — Azure CLI

```bash
RG=rg-eh-prod
LOC=eastus
NS=ehns-app-prod-$RANDOM
HUB=telemetry

# 1. Namespace (Standard, auto-inflate up to 20 TUs)
az eventhubs namespace create -g "$RG" -n "$NS" -l "$LOC" \
  --sku Standard \
  --enable-auto-inflate true --maximum-throughput-units 20 \
  --zone-redundant true \
  --minimum-tls-version 1.2 \
  --public-network-access Disabled

# Force Entra-only (verify exact flag with --help)
az resource update -g "$RG" -n "$NS" \
  --resource-type Microsoft.EventHub/namespaces \
  --set properties.disableLocalAuth=true

# 2. Event Hub (partition count is permanent on Standard — pick carefully)
az eventhubs eventhub create -g "$RG" --namespace-name "$NS" -n "$HUB" \
  --partition-count 8 \
  --message-retention 3

# 3. Consumer group
az eventhubs eventhub consumer-group create -g "$RG" --namespace-name "$NS" \
  --eventhub-name "$HUB" --name app-consumer

# 4. Grant a producer MI Data Sender on the hub (narrower than namespace)
HUB_ID=/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.EventHub/namespaces/$NS/eventhubs/$HUB
az role assignment create \
  --assignee-object-id <producer-mi-objectid> \
  --assignee-principal-type ServicePrincipal \
  --role "Azure Event Hubs Data Sender" \
  --scope "$HUB_ID"

# 5. Capture to Storage (every 5 min OR every 300 MB, whichever first)
az eventhubs eventhub update -g "$RG" --namespace-name "$NS" -n "$HUB" \
  --enable-capture true \
  --capture-interval 300 \
  --capture-size-limit 314572800 \
  --destination-name EventHubArchive.AzureBlockBlob \
  --storage-account /subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.Storage/storageAccounts/saehcapture \
  --blob-container ehcapture \
  --archive-name-format "{Namespace}/{EventHub}/{PartitionId}/{Year}/{Month}/{Day}/{Hour}/{Minute}/{Second}"
```

## Recipe — Bicep

```bicep
param namespaceName string
param hubName string = 'telemetry'
param partitionCount int = 8
param location string = resourceGroup().location

resource ehns 'Microsoft.EventHub/namespaces@2024-01-01' = {
  name: namespaceName
  location: location
  sku: { name: 'Standard', tier: 'Standard', capacity: 1 }
  properties: {
    isAutoInflateEnabled: true
    maximumThroughputUnits: 20
    zoneRedundant: true
    minimumTlsVersion: '1.2'
    publicNetworkAccess: 'Disabled'
    disableLocalAuth: true
    kafkaEnabled: true
  }
}

resource hub 'Microsoft.EventHub/namespaces/eventhubs@2024-01-01' = {
  parent: ehns
  name: hubName
  properties: {
    partitionCount: partitionCount       // immutable on Standard
    messageRetentionInDays: 3
  }
}

resource cg 'Microsoft.EventHub/namespaces/eventhubs/consumergroups@2024-01-01' = {
  parent: hub
  name: 'app-consumer'
}
```

## Kafka surface (drop-in for Kafka producers/consumers)

- Bootstrap server: `{namespace}.servicebus.windows.net:9093`
- SASL mechanism: `PLAIN`
- Username: `$ConnectionString` (literal) when using SAS, or use OAuth /
  Entra ID (preferred — pair with `disableLocalAuth: true`).
- Topic names = Event Hub names.
- See [Event Hubs for Kafka](https://learn.microsoft.com/azure/event-hubs/event-hubs-for-kafka-ecosystem-overview).

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| Cannot increase `partitionCount` on Standard | Partitions are immutable on Standard | Plan partitions up front. Premium allows raising (not lowering). |
| Consumer falls behind / lag grows | Too few partitions, or too few consumer instances (one consumer per partition max within a consumer group) | Add partitions (Premium) or add hubs; scale consumer instances up to `partitionCount`. |
| Ordering broken across partitions | Order is **per-partition only** | Use a partition key based on the entity that needs ordering. |
| Capture seems to drop events | Capture writes when **either** time **or** size threshold is hit. Empty windows still emit empty Avro files unless you configure otherwise. | Lower thresholds or accept the empty-file behavior. ([Source](https://learn.microsoft.com/azure/event-hubs/event-hubs-capture-overview)) |
| Auto-inflate spent up to TU ceiling and now bills are high | Auto-inflate scales **up only**; you must scale down manually if traffic drops | Tune `maximumThroughputUnits` carefully; revisit after a known peak. ([Source](https://learn.microsoft.com/azure/event-hubs/event-hubs-auto-inflate)) |
| Kafka client gets 401 | SASL `PLAIN` with `$ConnectionString` but `disableLocalAuth: true` | Switch the Kafka client to OAuth / Entra-token credential and grant `Azure Event Hubs Data Sender`. |

## References

- [Event Hubs overview](https://learn.microsoft.com/azure/event-hubs/event-hubs-about)
- [Features](https://learn.microsoft.com/azure/event-hubs/event-hubs-features)
- [Quotas and limits](https://learn.microsoft.com/azure/event-hubs/event-hubs-quotas)
- [Authenticate with Entra ID](https://learn.microsoft.com/azure/event-hubs/authenticate-application)
- [Capture overview](https://learn.microsoft.com/azure/event-hubs/event-hubs-capture-overview)
- [Kafka ecosystem support](https://learn.microsoft.com/azure/event-hubs/event-hubs-for-kafka-ecosystem-overview)
- [Auto-inflate](https://learn.microsoft.com/azure/event-hubs/event-hubs-auto-inflate)
- [`Microsoft.EventHub/namespaces` template reference](https://learn.microsoft.com/azure/templates/microsoft.eventhub/namespaces)
