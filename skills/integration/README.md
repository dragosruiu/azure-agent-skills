# integration/

Skills for messaging, eventing, and orchestrating between services.

## In scope (planned — no skills yet authored this round)

- Azure Service Bus (queues + topics, premium tier, RBAC)
- Azure Event Grid (system + custom topics, MQTT)
- Azure Event Hubs (streaming, Kafka surface)
- Azure Logic Apps Standard

When in doubt, prefer Service Bus for **commands** (work that must be
processed exactly once with a guaranteed handler) and Event Grid for
**events** (things that happened, with potentially many subscribers).
