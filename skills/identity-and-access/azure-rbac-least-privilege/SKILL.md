---
name: azure-rbac-least-privilege
description: >
  Pick the smallest built-in Azure role for a given data-plane task.
  Covers blob / queue / Service Bus / Cosmos DB / Key Vault / ACR. Notes
  the Contributor-doesn't-cover-DataActions trap, the Cosmos native-RBAC
  exception, and how to inspect effective role assignments.
version: 0.1.0
azure_services:
  - Microsoft.Authorization/roleAssignments
  - Microsoft.Authorization/roleDefinitions
tags:
  - identity
  - rbac
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/role-based-access-control/built-in-roles
  - https://learn.microsoft.com/azure/role-based-access-control/role-definitions
  - https://learn.microsoft.com/azure/role-based-access-control/built-in-roles/containers
  - https://learn.microsoft.com/azure/role-based-access-control/role-assignments-list-cli
  - https://learn.microsoft.com/azure/role-based-access-control/role-assignments-cli
  - https://learn.microsoft.com/azure/role-based-access-control/best-practices
  - https://learn.microsoft.com/azure/storage/queues/authorize-access-azure-active-directory
  - https://learn.microsoft.com/azure/service-bus-messaging/service-bus-managed-service-identity
  - https://learn.microsoft.com/azure/cosmos-db/how-to-connect-role-based-access-control
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2022-04-01"
last_reviewed: 2026-05-11
---

# Azure RBAC least privilege (data-plane role picker)

## When to use this skill

- The user wants to grant a workload (managed identity, service principal,
  user) just enough access to read/write a specific data resource.
- The user is reaching for `Contributor` and we should stop them.
- The user reports a 403 from a data-plane call despite "having access".

## When NOT to use this skill

- Granting control-plane management rights (creating / deleting resources).
  That's a separate decision and usually `Contributor` scoped to an RG is
  appropriate for an automation principal.
- Cosmos DB Mongo / Cassandra / Gremlin APIs — not covered here. The
  NoSQL API uses native RBAC; other APIs vary.

## Prerequisites

- Caller must be `Owner` or `User Access Administrator` at the target
  scope to create role assignments.
- Use `--assignee-object-id` + `--assignee-principal-type ServicePrincipal`
  for managed identities — avoids a Microsoft Graph lookup that needs
  Directory.Read permission and races against identity creation.

## Secure defaults

| Decision | Default | Why |
| --- | --- | --- |
| **Scope** | The narrowest resource the workload needs (a specific blob container, queue, vault, ACR repo) — never `subscription` for an app | Blast-radius minimization. Source: [RBAC best practices](https://learn.microsoft.com/azure/role-based-access-control/best-practices). |
| **Role** | The most specific *data-plane* built-in (e.g., `Storage Blob Data Reader`, not `Storage Account Contributor`) | Control-plane roles like `Contributor` use `Actions: ['*']` which **does NOT** include `DataActions`. ([Source](https://learn.microsoft.com/azure/role-based-access-control/role-definitions)) |
| **`principalType`** | `'ServicePrincipal'` for any managed identity / app | Skips Graph lookup that races with identity creation. |

## The Contributor / DataActions trap

`Contributor` (and most other classic roles) are **control-plane** roles:
they have `Actions: ['*']` plus a few `NotActions`. The `*` wildcard
**does not** match `DataActions` (e.g.,
`Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read`).

So a managed identity with `Contributor` on a storage account **cannot
read a blob's contents** until it is also assigned a data-plane role like
`Storage Blob Data Reader`. ([Source](https://learn.microsoft.com/azure/role-based-access-control/role-definitions))

## Data-plane role picker

| Scenario | Built-in role | Role ID (built-in, globally stable) | Verified on Learn |
| --- | --- | --- | --- |
| Read blob | `Storage Blob Data Reader` | `2a2b9908-6ea1-4ae2-8e65-a410df84e7d1` | ✅ [role-definitions](https://learn.microsoft.com/azure/role-based-access-control/role-definitions) |
| Write/delete blob | `Storage Blob Data Contributor` | `ba92f5b4-2d11-453d-a403-e96b0029c9fe` | name verified, ID widely-used built-in |
| Read queue messages | `Storage Queue Data Reader` | `19e7f393-937e-4f77-808e-94535e297925` | name verified ([queue auth](https://learn.microsoft.com/azure/storage/queues/authorize-access-azure-active-directory)) |
| Send queue message | `Storage Queue Data Message Sender` | `c6a89b2d-59bc-44d0-9896-0f6e12d7b80a` | name verified |
| Process queue message (peek+delete) | `Storage Queue Data Message Processor` | `8a0f0c08-91a1-4084-bc3d-661d67233fed` | name verified |
| Send Service Bus message | `Azure Service Bus Data Sender` | `69a216fc-b8fb-44d8-bc22-1f3c2cd27a39` | name verified ([SB MSI](https://learn.microsoft.com/azure/service-bus-messaging/service-bus-managed-service-identity)) |
| Receive Service Bus message | `Azure Service Bus Data Receiver` | `4f6d3b9f-028c-4d7e-abb7-0f79d31286f1` | name verified |
| Manage SB queues/topics | `Azure Service Bus Data Owner` | `090c5cfd-751d-490a-894a-3ce6f1109419` | name verified |
| Read Key Vault secret | `Key Vault Secrets User` | `4633458b-17de-408a-b874-0445c86b69e6` | ✅ [KV rbac-guide](https://learn.microsoft.com/azure/key-vault/general/rbac-guide) |
| Create / rotate Key Vault secret | `Key Vault Secrets Officer` | `b86a8fe4-44ce-4948-aee5-eccb2c155cd7` | ✅ |
| Pull from ACR | `AcrPull` | `7f951dda-4ed3-4680-a7ca-43fe172d538d` | ✅ [container roles](https://learn.microsoft.com/azure/role-based-access-control/built-in-roles/containers) |
| Push to ACR | `AcrPush` | `8311e382-0749-4cb8-b61a-304f252e45ec` | ✅ |
| Read Cosmos DB document (NoSQL) | `Cosmos DB Built-in Data Reader` ⚠️ | native RBAC | ⚠️ see below |
| Read/write Cosmos DB document (NoSQL) | `Cosmos DB Built-in Data Contributor` ⚠️ | native RBAC | ⚠️ see below |

> **Always confirm a role ID before pinning it in IaC** with:
>
> ```bash
> az role definition list --name "Storage Blob Data Reader" --query "[].name" -o tsv
> ```
>
> Built-in role IDs are stable across Azure but a typo in IaC will silently
> assign nothing useful.

## Cosmos DB is special

Cosmos DB for NoSQL **does not** use the standard ARM RBAC subsystem for
data-plane access. It has its own built-in role definitions stored
inside the Cosmos account. ([Source](https://learn.microsoft.com/azure/cosmos-db/how-to-connect-role-based-access-control))

```bash
# Standard role assignment - does NOT work for Cosmos DB data plane
az role assignment create --role "Cosmos DB Built-in Data Reader" ...   # ❌ wrong tool

# Correct: use the Cosmos-DB-specific subcommands
az cosmosdb sql role definition list --account-name $COSMOS --resource-group $RG
az cosmosdb sql role assignment create \
  --account-name $COSMOS --resource-group $RG \
  --role-definition-id <id-from-list-above> \
  --principal-id $PRINCIPAL_ID \
  --scope "/dbs/<db>/colls/<container>"   # narrow scope inside the account
```

The two built-in role definition IDs (`00000000-0000-0000-0000-000000000001`
for Reader and `...0002` for Contributor) are widely cited but **always
look them up live** with `az cosmosdb sql role definition list` rather than
hard-coding.

## Recipe — Azure CLI

```bash
PRINCIPAL_ID=<objectId-of-managed-identity>

# Read blobs in a specific account
SA_ID=$(az storage account show -n mystorage -g $RG --query id -o tsv)
az role assignment create \
  --assignee-object-id "$PRINCIPAL_ID" \
  --assignee-principal-type ServicePrincipal \
  --role "Storage Blob Data Reader" \
  --scope "$SA_ID"

# Send to a specific Service Bus queue (narrower than namespace)
QUEUE_ID="/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.ServiceBus/namespaces/$NS/queues/$QUEUE"
az role assignment create \
  --assignee-object-id "$PRINCIPAL_ID" \
  --assignee-principal-type ServicePrincipal \
  --role "Azure Service Bus Data Sender" \
  --scope "$QUEUE_ID"

# Inspect effective roles for an identity at a scope (incl. inherited)
az role assignment list \
  --assignee "$PRINCIPAL_ID" \
  --scope "$SA_ID" \
  --include-inherited --all \
  --output table
```

## Recipe — Bicep

```bicep
param principalId string
var storageBlobDataReaderId = '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'

resource sa 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource blobReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(sa.id, principalId, storageBlobDataReaderId)
  scope: sa
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions', storageBlobDataReaderId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}
```

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| `Contributor` on RG can manage the storage account but **cannot read blobs** | `Contributor` is control-plane only; `*` in `Actions` doesn't match `DataActions` | Add a `Storage Blob Data *` role assignment. ([Source](https://learn.microsoft.com/azure/role-based-access-control/role-definitions)) |
| Granted `Cosmos DB Built-in Data Reader` via `az role assignment create`, app still 403s | Cosmos NoSQL data plane uses native RBAC, not ARM RBAC | Use `az cosmosdb sql role assignment create`. |
| Role assignment shows up in CLI but data calls still fail | Up to 10 min RBAC propagation; up to 12 h for management-group scope assignments with data actions | Retry with backoff; assign at resource scope, not management group, when latency matters. ([Source](https://learn.microsoft.com/azure/storage/queues/assign-azure-role-data-access)) |
| Removed someone's role but they can still access | OAuth tokens are valid for ~1 h (Azure AD); managed-identity tokens cached up to 24 h | Restart the consuming app to drop cached tokens; for human users, force sign-out. ([Source](https://learn.microsoft.com/azure/service-bus-messaging/service-bus-managed-service-identity)) |
| `--assignee` lookup fails: `Insufficient privileges to complete the operation` | The CLI tried to call Microsoft Graph to resolve the principal | Use `--assignee-object-id <principalId> --assignee-principal-type ServicePrincipal`. |
| Searched for `az role assignment list-for-scope` — command not found | That command does not exist | Use `az role assignment list --scope <resource-id>` (with `--include-inherited --all` if needed). |

## References

- [Azure built-in roles index](https://learn.microsoft.com/azure/role-based-access-control/built-in-roles)
- [Built-in roles — Containers (AcrPull / AcrPush)](https://learn.microsoft.com/azure/role-based-access-control/built-in-roles/containers)
- [Understand Azure role definitions (Actions vs DataActions)](https://learn.microsoft.com/azure/role-based-access-control/role-definitions)
- [List role assignments using Azure CLI](https://learn.microsoft.com/azure/role-based-access-control/role-assignments-list-cli)
- [Add or remove role assignments using Azure CLI](https://learn.microsoft.com/azure/role-based-access-control/role-assignments-cli)
- [RBAC best practices](https://learn.microsoft.com/azure/role-based-access-control/best-practices)
- [Authorize access to queues and tables using Microsoft Entra ID](https://learn.microsoft.com/azure/storage/queues/authorize-access-azure-active-directory)
- [Service Bus authentication with managed identities](https://learn.microsoft.com/azure/service-bus-messaging/service-bus-managed-service-identity)
- [Cosmos DB native RBAC](https://learn.microsoft.com/azure/cosmos-db/how-to-connect-role-based-access-control)
