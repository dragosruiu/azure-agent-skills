---
name: azure-service-bus
description: >
  Provision Azure Service Bus with secure defaults: Premium tier
  (required for VNet / private endpoint / large messages), `disableLocalAuth: true`
  to force Entra ID, queues with DLQ on max-delivery-count, sessions
  for FIFO-per-key, RBAC via Azure Service Bus Data Sender / Receiver
  / Owner.
version: 0.1.0
azure_services:
  - Microsoft.ServiceBus/namespaces
  - Microsoft.ServiceBus/namespaces/queues
  - Microsoft.ServiceBus/namespaces/topics
  - Microsoft.ServiceBus/namespaces/topics/subscriptions
tags:
  - integration
  - messaging
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/service-bus-messaging/service-bus-messaging-overview
  - https://learn.microsoft.com/azure/service-bus-messaging/disable-local-authentication
  - https://learn.microsoft.com/azure/service-bus-messaging/service-bus-managed-service-identity
  - https://learn.microsoft.com/azure/service-bus-messaging/service-bus-premium-messaging
  - https://learn.microsoft.com/azure/service-bus-messaging/service-bus-dead-letter-queues
  - https://learn.microsoft.com/azure/service-bus-messaging/message-sessions
  - https://learn.microsoft.com/azure/templates/microsoft.servicebus/namespaces
  - https://learn.microsoft.com/azure/templates/microsoft.servicebus/namespaces/queues
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2024-01-01"
last_reviewed: 2026-05-11
---

# Azure Service Bus (secure baseline)

## When to use this skill

- The user needs **command** semantics: each message must be processed
  exactly once by exactly one handler.
- The user wants ordered delivery per logical key (sessions).
- The user is moving off SAS connection strings to Entra ID auth.

## When NOT to use this skill

- The user wants **event** semantics (many independent subscribers, fire-
  and-forget) — use Event Grid.
- High-throughput streaming / Kafka surface — use Event Hubs.
- Pub/sub at scale where each event is processed independently — Event
  Grid is usually a better fit than Topics + many subscriptions.

## Tier picker

| Need | Tier |
| --- | --- |
| Dev / non-prod, < 256 KB messages, no VNet | **Standard** |
| Prod, VNet integration, private endpoint, dedicated capacity | **Premium** |
| Large messages (up to 100 MB, AMQP only) | **Premium** + `maxMessageSizeInKilobytes` |
| Zone redundancy | **Premium** |
| Sessions / topics | Standard or Premium (Basic doesn't support either) |

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| `sku.name` | `'Premium'` for prod | Only Premium supports VNet / PE / dedicated capacity. |
| `disableLocalAuth` | `true` | Disables SAS keys; forces Entra ID. |
| `minimumTlsVersion` | `'1.2'` | Reject TLS 1.0/1.1 clients. |
| `publicNetworkAccess` | `'Disabled'` | Pair with a private endpoint to `privatelink.servicebus.windows.net`. |
| `zoneRedundant` | `true` (Premium only) | AZ failure tolerance. |
| Queue `lockDuration` | `'PT1M'` (max `'PT5M'`) | Long enough for typical processing; renew in code if longer. |
| Queue `maxDeliveryCount` | `10` | After 10 failed attempts → DLQ. Tune for your retry policy. |
| Queue `deadLetteringOnMessageExpiration` | `true` | Catch poison messages. |
| Queue `requiresSession` | `true` for ordered/per-key processing | Each session = its own FIFO lane. |

## RBAC roles

Verified from [disable-local-authentication](https://learn.microsoft.com/azure/service-bus-messaging/disable-local-authentication):

| Role | Use case |
| --- | --- |
| `Azure Service Bus Data Sender` | Producers — send only. |
| `Azure Service Bus Data Receiver` | Consumers — receive + complete. |
| `Azure Service Bus Data Owner` | Manage entities + send + receive (admin / IaC). |

Scope at the **namespace, queue, or topic** — narrower is better.

## Recipe — Azure CLI

```bash
RG=rg-msg-prod
LOC=eastus
NS=sbns-app-prod-$RANDOM
QUEUE=orders

# Premium namespace with Entra-only auth
az servicebus namespace create -g "$RG" -n "$NS" -l "$LOC" \
  --sku Premium --capacity 1 \
  --disable-local-auth true \
  --minimum-tls-version 1.2 \
  --public-network-access Disabled

# Queue with DLQ on expiration; session disabled
az servicebus queue create -g "$RG" --namespace-name "$NS" --name "$QUEUE" \
  --lock-duration PT1M \
  --max-delivery-count 10 \
  --enable-dead-lettering-on-message-expiration true \
  --enable-session false

# Session-enabled queue (FIFO-per-session)
az servicebus queue create -g "$RG" --namespace-name "$NS" --name ordered-tasks \
  --enable-session true --lock-duration PT5M --max-delivery-count 10

# Topic + subscription (event broadcast)
az servicebus topic create        -g "$RG" --namespace-name "$NS" --name events
az servicebus topic subscription create -g "$RG" --namespace-name "$NS" --topic-name events --name billing-sub

# Grant a producer MI permission to send
PRINCIPAL=<objectId-of-producer-mi>
NS_ID=$(az servicebus namespace show -g "$RG" -n "$NS" --query id -o tsv)
az role assignment create \
  --assignee-object-id "$PRINCIPAL" --assignee-principal-type ServicePrincipal \
  --role "Azure Service Bus Data Sender" --scope "$NS_ID"
```

## Recipe — Bicep

```bicep
param namespaceName string
param location string = resourceGroup().location

resource sbns 'Microsoft.ServiceBus/namespaces@2024-01-01' = {
  name: namespaceName
  location: location
  sku: { name: 'Premium', tier: 'Premium', capacity: 1 }   // 1, 2, 4, 8, 16
  properties: {
    disableLocalAuth: true
    minimumTlsVersion: '1.2'
    publicNetworkAccess: 'Disabled'
    zoneRedundant: true
  }
}

resource queue 'Microsoft.ServiceBus/namespaces/queues@2024-01-01' = {
  parent: sbns
  name: 'orders'
  properties: {
    lockDuration: 'PT1M'                       // ISO 8601; max PT5M
    maxDeliveryCount: 10
    deadLetteringOnMessageExpiration: true
    requiresSession: false
    defaultMessageTimeToLive: 'P14D'
    enableBatchedOperations: true
    // Premium only — set to 102400 to enable 100 MB messages (AMQP only):
    // maxMessageSizeInKilobytes: 102400
  }
}
```

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| Messages pile up in DLQ with `MaxDeliveryCountExceeded` | Receiver throws an exception or lock expires before completion → message abandoned and re-delivered until the limit | Always handle exceptions and call `CompleteMessageAsync`; lengthen `lockDuration` (max `PT5M`) or call lock-renewal; raise `maxDeliveryCount` only if the work is genuinely slow. ([Source](https://learn.microsoft.com/azure/service-bus-messaging/service-bus-dead-letter-queues)) |
| `MessageLockLostException` mid-processing | Processing took longer than `lockDuration` | Renew the lock in the SDK, or chunk the work. |
| Trying to use VNet / private endpoint on Standard | Premium-only feature | Upgrade to Premium. |
| Large messages rejected (>256 KB) on Standard | Standard cap | Upgrade to Premium and set `maxMessageSizeInKilobytes: 102400`. **AMQP only — HTTP and SBMP still cap at 256 KB.** |
| Sender to a session-enabled queue gets `InvalidOperationException` | Sender didn't set `SessionId` | Producers must set `SessionId` on every message bound for a session-enabled entity. |
| 401 from SDK after enabling `disableLocalAuth` | App is using a connection string | Switch to `DefaultAzureCredential` and grant the MI a Data role. |

## References

- [Service Bus messaging overview](https://learn.microsoft.com/azure/service-bus-messaging/service-bus-messaging-overview)
- [Disable local (SAS) authentication](https://learn.microsoft.com/azure/service-bus-messaging/disable-local-authentication)
- [Authenticate with managed identities](https://learn.microsoft.com/azure/service-bus-messaging/service-bus-managed-service-identity)
- [Premium messaging](https://learn.microsoft.com/azure/service-bus-messaging/service-bus-premium-messaging)
- [Dead-letter queues](https://learn.microsoft.com/azure/service-bus-messaging/service-bus-dead-letter-queues)
- [Message sessions](https://learn.microsoft.com/azure/service-bus-messaging/message-sessions)
- [`Microsoft.ServiceBus/namespaces` template reference](https://learn.microsoft.com/azure/templates/microsoft.servicebus/namespaces)
