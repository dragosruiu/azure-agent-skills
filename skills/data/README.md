# data/

Skills for storing application state — choosing the right service and
configuring it with secure defaults.

## In scope

- Azure Storage (blobs, files, queues, tables)
- Azure Cosmos DB (NoSQL API; other APIs planned)
- Azure Database for PostgreSQL Flexible Server
- Azure SQL Database (planned)
- Azure Cache for Redis (planned)

## How to choose

| If the data is... | Pick |
| --- | --- |
| Unstructured blobs, files, or simple queues | Storage account |
| JSON documents, low-latency global, high write | Cosmos DB |
| Relational, OLTP, ACID, want PostgreSQL specifically | PostgreSQL Flexible Server |
| Relational, want SQL Server compatibility | Azure SQL Database |
| Hot cache, sub-ms latency, ephemeral | Redis |

All data skills enforce: Entra ID auth (no shared keys / no SQL auth where
avoidable), public network access disabled, encryption at rest with at
least platform-managed keys, soft-delete / point-in-time-restore where
the service supports it.
