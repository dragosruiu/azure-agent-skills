---
name: azure-event-grid
description: >
  Provision Azure Event Grid topics (system, custom, domain) with
  `disableLocalAuth: true`, CloudEvents v1.0 schema, retry + dead-
  letter-to-Storage, and the webhook-handshake flow that trips up new
  subscribers.
version: 0.1.0
azure_services:
  - Microsoft.EventGrid/topics
  - Microsoft.EventGrid/systemTopics
  - Microsoft.EventGrid/domains
  - Microsoft.EventGrid/eventSubscriptions
tags:
  - integration
  - events
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/event-grid/overview
  - https://learn.microsoft.com/azure/event-grid/concepts
  - https://learn.microsoft.com/azure/event-grid/cloud-event-schema
  - https://learn.microsoft.com/azure/event-grid/event-schema
  - https://learn.microsoft.com/azure/event-grid/security-authentication
  - https://learn.microsoft.com/azure/event-grid/webhook-event-delivery
  - https://learn.microsoft.com/azure/event-grid/delivery-and-retry
  - https://learn.microsoft.com/azure/event-grid/manage-event-delivery
  - https://learn.microsoft.com/azure/event-grid/system-topics
  - https://learn.microsoft.com/azure/event-grid/event-domains
  - https://learn.microsoft.com/azure/templates/microsoft.eventgrid/topics
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2025-02-15"
last_reviewed: 2026-05-11
---

# Azure Event Grid (secure baseline)

## When to use this skill

- The user wants **event** semantics: things that happened, often with
  multiple independent subscribers.
- The user is reacting to Azure resource events (Storage blob created,
  Key Vault secret rotated, Resource group changed) — that's **system topics**.
- The user is publishing custom events from their own app — that's a
  **custom topic** (or **domain** for multi-tenant routing).

## When NOT to use this skill

- The user needs strict ordering or exactly-once command semantics —
  use [`azure-service-bus`](../azure-service-bus/SKILL.md).
- The user needs Kafka or high-throughput streaming — use
  [`azure-event-hubs`](../azure-event-hubs/SKILL.md).

## System topic vs custom topic vs domain

| Pattern | Use when |
| --- | --- |
| **System topic** | You want to react to events from an Azure resource (Storage, Key Vault, Resource Group, etc.). The topic is auto-created when you subscribe. |
| **Custom topic** | Your own app publishes events; one publisher → many subscribers. |
| **Domain** | Multi-tenant scenario: one logical "topic per tenant" without provisioning thousands of resources. Use `subject` to route per tenant. |

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| `properties.disableLocalAuth` | `true` | Disables SAS / access-key publishing; forces Entra ID. **No verified `az` CLI flag** — set via `az resource update --set properties.disableLocalAuth=true` or Bicep. |
| `properties.publicNetworkAccess` | `'Disabled'` (custom topics + domains) | Pair with a PE to the relevant private DNS zone. |
| `properties.minimumTlsVersionAllowed` | `'1.2'` (recent API versions) | Reject older TLS. |
| `properties.inputSchema` | `'CloudEventSchemaV1_0'` | Use the open CNCF standard, not the proprietary `EventGridSchema`. |
| Subscription `eventDeliverySchema` | `'CloudEventSchemaV1_0'` | Same — match end-to-end. |
| Subscription `retryPolicy.maxDeliveryAttempts` | `30` (default; 1–30) | Cap retries. |
| Subscription `retryPolicy.eventTimeToLiveInMinutes` | `1440` (default 24h) | Drop events older than this. |
| Subscription `deadLetterDestination` | a Storage container (`StorageBlob`) | Capture undeliverable events for inspection. |

## RBAC roles

| Role | Use case |
| --- | --- |
| `EventGrid Data Sender` | Publishers — `Microsoft.EventGrid/events/send/action`. |
| `EventGrid Contributor` | Manage topics, subscriptions, system topics. |
| `EventGrid TopicSpaces Subscriber` (MQTT) | MQTT-broker subscribers. |

## Recipe — Azure CLI (custom topic + webhook subscription)

```bash
RG=rg-events-prod
LOC=eastus
TOPIC=evgt-app-prod
WEBHOOK_URL=https://app.contoso.com/api/eventgrid

# 1. Custom topic with CloudEvents schema and Entra-only auth
az eventgrid topic create -g "$RG" -n "$TOPIC" -l "$LOC" \
  --input-schema CloudEventSchemaV1_0
az resource update -g "$RG" -n "$TOPIC" \
  --resource-type Microsoft.EventGrid/topics \
  --set properties.disableLocalAuth=true \
        properties.publicNetworkAccess=Disabled

# 2. Subscription with retry policy + dead-letter to Storage
SA_ID=/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.Storage/storageAccounts/sadeadletters
az eventgrid event-subscription create \
  --name to-app-webhook \
  --source-resource-id $(az eventgrid topic show -g "$RG" -n "$TOPIC" --query id -o tsv) \
  --endpoint "$WEBHOOK_URL" \
  --event-delivery-schema cloudeventschemav1_0 \
  --max-delivery-attempts 10 \
  --event-ttl 1440 \
  --deadletter-endpoint "${SA_ID}/blobServices/default/containers/deadletters" \
  --included-event-types Order.Created Order.Cancelled

# 3. System topic on a Storage account (subscribe to blob created events)
az eventgrid system-topic create -g "$RG" -n storage-events -l "$LOC" \
  --topic-type Microsoft.Storage.StorageAccounts \
  --source $(az storage account show -g "$RG" -n mystore --query id -o tsv)
az eventgrid system-topic event-subscription create \
  --name on-blob-created --resource-group "$RG" --system-topic-name storage-events \
  --endpoint "$WEBHOOK_URL" \
  --included-event-types Microsoft.Storage.BlobCreated
```

## Recipe — Bicep (custom topic)

```bicep
param topicName string
param location string = resourceGroup().location

resource topic 'Microsoft.EventGrid/topics@2025-02-15' = {
  name: topicName
  location: location
  properties: {
    inputSchema: 'CloudEventSchemaV1_0'
    disableLocalAuth: true
    publicNetworkAccess: 'Disabled'
    minimumTlsVersionAllowed: '1.2'
  }
}

output endpoint string = topic.properties.endpoint
```

## Webhook handshake (the trap that bites first-time subscribers)

When you create a subscription targeting a webhook, Event Grid sends a
`Microsoft.EventGrid.SubscriptionValidationEvent` first. The endpoint
**must** respond with HTTP 200 and a JSON body containing
`{ "validationResponse": "<code>" }` within ~30 seconds. If it doesn't,
the subscription creation fails and no events are delivered. ([Source](https://learn.microsoft.com/azure/event-grid/webhook-event-delivery))

Azure Functions, Logic Apps, and Service Bus / Storage queue endpoints
do this automatically. **Custom HTTP endpoints must implement it.**

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| Subscription create fails: "endpoint validation failed" | Webhook didn't return the validation response | Implement the handshake (see above). Or use `endpointType: ServiceBusQueue` / `AzureFunction` which auto-handle it. |
| Events appear missing on the consumer | `subject` filter case-sensitive; subject prefix/suffix not matching | Inspect the actual `subject` and the filter; subject filters are exact match (with prefix/suffix). |
| Webhook gets **hammered with retries** when down | Default retry policy hits 30 attempts over 24 h | Set `maxDeliveryAttempts` and `eventTimeToLiveInMinutes` lower; configure dead-letter so undeliverable events go to Storage instead of looping. ([Source](https://learn.microsoft.com/azure/event-grid/delivery-and-retry)) |
| 401 publishing to a custom topic | App used the access key but `disableLocalAuth: true` | Use `DefaultAzureCredential` and grant `EventGrid Data Sender` to the MI. |
| Event Grid system topic on Storage doesn't fire | Account isn't GPv2, or wrong event type filter, or destination is in wrong region | Confirm `kind: StorageV2`; double-check `Microsoft.Storage.BlobCreated` (case-sensitive). |
| Dead-letter container empty even though events fail | Container doesn't exist; or Event Grid principal lacks `Storage Blob Data Contributor` on the SA | Create the container; assign the role to the system-topic / topic principal. |

## References

- [Event Grid overview](https://learn.microsoft.com/azure/event-grid/overview)
- [Concepts (topics, subscriptions, events)](https://learn.microsoft.com/azure/event-grid/concepts)
- [CloudEvents schema](https://learn.microsoft.com/azure/event-grid/cloud-event-schema)
- [Security and authentication](https://learn.microsoft.com/azure/event-grid/security-authentication)
- [Webhook event delivery (handshake)](https://learn.microsoft.com/azure/event-grid/webhook-event-delivery)
- [Delivery and retry](https://learn.microsoft.com/azure/event-grid/delivery-and-retry)
- [System topics](https://learn.microsoft.com/azure/event-grid/system-topics)
- [Event domains](https://learn.microsoft.com/azure/event-grid/event-domains)
- [`Microsoft.EventGrid/topics` template reference](https://learn.microsoft.com/azure/templates/microsoft.eventgrid/topics)
