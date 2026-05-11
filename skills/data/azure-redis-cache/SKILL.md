---
name: azure-redis-cache
description: >
  Provision Azure Cache for Redis with secure defaults: Premium tier
  (required for VNet / private endpoint / persistence / clustering),
  TLS 1.2 minimum, non-SSL port 6379 disabled, Microsoft Entra
  authentication enabled (`aad-enabled: true`), shared-key auth
  disabled, sensible `maxmemory-policy: allkeys-lru`.
version: 0.1.0
azure_services:
  - Microsoft.Cache/redis
  - Microsoft.Cache/redis/accessPolicyAssignments
tags:
  - data
  - cache
  - redis
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/azure-cache-for-redis/cache-overview
  - https://learn.microsoft.com/azure/azure-cache-for-redis/cache-azure-active-directory-for-authentication
  - https://learn.microsoft.com/azure/azure-cache-for-redis/cache-configure
  - https://learn.microsoft.com/azure/azure-cache-for-redis/cache-private-link
  - https://learn.microsoft.com/azure/azure-cache-for-redis/cache-how-to-premium-persistence
  - https://learn.microsoft.com/azure/azure-cache-for-redis/cache-how-to-zone-redundancy
  - https://learn.microsoft.com/azure/azure-cache-for-redis/cache-best-practices-memory-management
  - https://learn.microsoft.com/cli/azure/redis
  - https://learn.microsoft.com/azure/templates/microsoft.cache/redis
validated_with:
  az_cli: ">=2.60.0"
  api_version: "2024-11-01"
last_reviewed: 2026-05-11
---

# Azure Cache for Redis (secure baseline)

## When to use this skill

- The user wants a managed Redis cache for an app (session store,
  rate-limiter, distributed lock, hot read-through cache).
- The user wants persistence (RDB/AOF) for a non-pure-cache workload.
- The user wants Redis-compatible advanced modules (RediSearch, RedisJSON,
  RedisBloom) — that's **Enterprise** tier.

## When NOT to use this skill

- The user wants Redis modules + Entra auth — **Enterprise / Enterprise
  Flash do NOT support Entra auth** at the time of writing. Use Premium.
- The data is durable / source-of-truth — Redis is a cache; pair with a
  database.

## Tier picker

| Need | Tier |
| --- | --- |
| Dev / non-prod, < 6 GB | Basic |
| Prod, replication, no VNet | Standard |
| **Prod with VNet / PE / persistence / clustering / geo-replication** | **Premium** |
| Redis modules (RediSearch, RedisJSON, RedisBloom) | Enterprise |
| Cost-optimized large caches with NVMe | Enterprise Flash |

| Tier | Entra auth supported? |
| --- | --- |
| Basic / Standard / Premium | ✅ |
| Enterprise / Enterprise Flash | ❌ (at time of writing) |

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| `--sku` / `sku.name` | `Premium` for prod | VNet, PE, persistence, clustering, geo-replication. |
| `--vm-size` | `p1`–`p5` (Premium); `c0`–`c6` (Basic/Standard) | P1 = 6 GB, P5 = 120 GB. |
| `--minimum-tls-version` / `properties.minimumTlsVersion` | `1.2` | Reject older TLS. |
| `enableNonSslPort` | **`false`** (default; never include `--enable-non-ssl-port`) | The non-TLS port 6379 is insecure. Use 6380 + TLS. |
| `disableAccessKeyAuthentication` / `--disable-access-keys true` | `true` | Disables shared-key auth; forces Entra-only (Basic/Standard/Premium). |
| `redisConfiguration.aad-enabled` | `'true'` | Enables Entra token auth. |
| `redisConfiguration.maxmemory-policy` | `'allkeys-lru'` | Default is `volatile-lru` which only evicts keys with TTL — surprising eviction behavior. |
| `publicNetworkAccess` | `'Disabled'` (after PE creation) | Force private-only access. **Not supported on Enterprise tiers via this flag.** |
| `zonalAllocationPolicy` | `'Automatic'` (Premium) | Zone-redundant in supported regions. |
| Persistence (Premium only) | RDB or AOF if you need it | Optional; pure-cache use cases skip it. |

## Recipe — Azure CLI

```bash
RG=rg-redis-prod
LOC=eastus
CACHE=redis-app-prod-$RANDOM

# 1. Redis configuration JSON (Entra + safe maxmemory)
cat > /tmp/redis-config.json <<'EOF'
{
  "aad-enabled": "true",
  "maxmemory-policy": "allkeys-lru",
  "maxmemory-reserved": "200",
  "maxfragmentationmemory-reserved": "200"
}
EOF

az group create -n "$RG" -l "$LOC"

# 2. Premium cache, Entra-only, TLS-only
az redis create -g "$RG" -n "$CACHE" -l "$LOC" \
  --sku Premium --vm-size p1 \
  --minimum-tls-version 1.2 \
  --disable-access-keys true \
  --redis-configuration @/tmp/redis-config.json \
  --zonal-allocation-policy Automatic
# Note: do NOT pass --enable-non-ssl-port — keep 6379 closed.

# 3. Private endpoint to privatelink.redis.cache.windows.net (groupId = redisCache)
CACHE_ID=$(az redis show -g "$RG" -n "$CACHE" --query id -o tsv)
az network private-endpoint create -g "$RG" -n "pe-$CACHE" \
  --vnet-name vnet-app --subnet snet-pe \
  --private-connection-resource-id "$CACHE_ID" \
  --connection-name "pec-$CACHE" --group-id redisCache
az network private-dns zone create -g "$RG" -n privatelink.redis.cache.windows.net
az network private-dns link vnet create -g "$RG" -n vnet-app-link \
  -z privatelink.redis.cache.windows.net --virtual-network vnet-app --registration-enabled false
az network private-endpoint dns-zone-group create -g "$RG" --endpoint-name "pe-$CACHE" \
  -n zg-redis --private-dns-zone privatelink.redis.cache.windows.net --zone-name redis

# 4. Now disable public network access
az redis update -g "$RG" -n "$CACHE" --set "publicNetworkAccess=Disabled"

# 5. Grant the app's MI Redis Data Owner via the Redis access-policy-assignment
PRINCIPAL_ID=<objectId-of-app-managed-identity>
az redis access-policy-assignment create -g "$RG" -n "$CACHE" \
  --policy-assignment-name app-data-owner \
  --access-policy-name "Data Owner" \
  --object-id "$PRINCIPAL_ID" \
  --object-id-alias app-mi

echo "Connect over TLS to $CACHE.redis.cache.windows.net:6380"
```

## Recipe — Bicep

```bicep
param cacheName string
param location string = resourceGroup().location

resource redis 'Microsoft.Cache/redis@2024-11-01' = {
  name: cacheName
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    sku: { name: 'Premium', family: 'P', capacity: 1 }   // P1 = 6 GB
    enableNonSslPort: false                  // SECURE: keep 6379 closed
    minimumTlsVersion: '1.2'
    publicNetworkAccess: 'Disabled'
    disableAccessKeyAuthentication: true     // Entra-only
    zonalAllocationPolicy: 'Automatic'
    redisConfiguration: {
      'aad-enabled': 'true'
      'maxmemory-policy': 'allkeys-lru'      // change from default volatile-lru
      'maxmemory-reserved': '200'
      'maxfragmentationmemory-reserved': '200'
    }
    redisVersion: '6.0'
  }
}
```

## Connecting from code

```python
# Python sketch using azure-identity + redis-py
from azure.identity import DefaultAzureCredential
import redis

credential = DefaultAzureCredential()
token = credential.get_token("https://redis.azure.com/.default").token

r = redis.Redis(
    host=f"{cache_name}.redis.cache.windows.net",
    port=6380, ssl=True,
    username="<entra-object-id-or-alias>",
    password=token,         # the access token IS the password
)
```

The token must be **refreshed before expiry** (~1 hour). Most SDK
wrappers handle this; bare `redis-py` does not.

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| Client can't connect | App is hitting the non-SSL port 6379 (which is correctly disabled) | Use port `6380` and TLS. |
| "MAXMEMORY exceeded" / cache constantly evicting | `maxmemory-policy` defaulted to `volatile-lru` and most keys have no TTL | Set `maxmemory-policy` to `allkeys-lru`. ([Source](https://learn.microsoft.com/azure/azure-cache-for-redis/cache-best-practices-memory-management)) |
| Tried to enable VNet on Standard tier | VNet support requires Premium | Upgrade to Premium. |
| Tried to enable Entra on Enterprise | Entra not supported on Enterprise / Enterprise Flash at time of writing | Use Premium tier or wait for support. ([Source](https://learn.microsoft.com/azure/azure-cache-for-redis/cache-azure-active-directory-for-authentication)) |
| Token-based connect works for ~1 h then fails | Entra access token expires | Implement token refresh in the client; many SDKs do this for you. |
| Persistence doesn't survive a region failure | Persistence is per-region; geo-replication is a separate feature | Configure geo-replication on Premium for cross-region recovery. |

## References

- [Azure Cache for Redis overview](https://learn.microsoft.com/azure/azure-cache-for-redis/cache-overview)
- [Microsoft Entra authentication for Redis](https://learn.microsoft.com/azure/azure-cache-for-redis/cache-azure-active-directory-for-authentication)
- [Configure Redis](https://learn.microsoft.com/azure/azure-cache-for-redis/cache-configure)
- [Azure Private Link for Redis](https://learn.microsoft.com/azure/azure-cache-for-redis/cache-private-link)
- [Redis persistence (Premium)](https://learn.microsoft.com/azure/azure-cache-for-redis/cache-how-to-premium-persistence)
- [Zone redundancy](https://learn.microsoft.com/azure/azure-cache-for-redis/cache-how-to-zone-redundancy)
- [Memory management best practices](https://learn.microsoft.com/azure/azure-cache-for-redis/cache-best-practices-memory-management)
- [`az redis` CLI](https://learn.microsoft.com/cli/azure/redis)
- [`Microsoft.Cache/redis` template reference](https://learn.microsoft.com/azure/templates/microsoft.cache/redis)
