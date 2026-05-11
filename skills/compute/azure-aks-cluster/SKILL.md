---
name: azure-aks-cluster
description: >
  Provision a production-leaning Azure Kubernetes Service cluster with
  Microsoft Entra integration + Azure RBAC, Azure CNI Overlay, OIDC
  issuer + Workload Identity, private API server, autoscaling system +
  user node pools, and the Container Insights / Azure Policy / Key Vault
  Secrets Provider / Image Cleaner add-ons.
version: 0.1.0
azure_services:
  - Microsoft.ContainerService/managedClusters
  - Microsoft.ContainerService/managedClusters/agentPools
tags:
  - compute
  - kubernetes
  - aks
  - security-baseline
sources:
  - https://learn.microsoft.com/azure/aks/managed-aad
  - https://learn.microsoft.com/azure/aks/azure-cni-overlay
  - https://learn.microsoft.com/azure/aks/workload-identity-deploy-cluster
  - https://learn.microsoft.com/azure/aks/cluster-autoscaler
  - https://learn.microsoft.com/azure/aks/use-system-pools
  - https://learn.microsoft.com/azure/aks/csi-secrets-store-driver
  - https://learn.microsoft.com/azure/aks/container-registry-auth-aks
  - https://learn.microsoft.com/azure/aks/api-server-vnet-integration
  - https://learn.microsoft.com/azure/aks/image-cleaner
  - https://learn.microsoft.com/azure/aks/concepts-identity
  - https://learn.microsoft.com/azure/templates/microsoft.containerservice/managedclusters
validated_with:
  az_cli: ">=2.63.0"
  api_version: "2026-01-01"
last_reviewed: 2026-05-11
---

# Azure Kubernetes Service (production baseline)

## When to use this skill

- The workload needs cluster-level features (CRDs, custom CNI, GPUs,
  DaemonSets, operators).
- The user is migrating off self-managed Kubernetes / OpenShift.
- The user wants Workload Identity for pod → Azure auth without secrets.

## When NOT to use this skill

- The workload is a single web service or worker — Container Apps or
  App Service is faster to operate.
- The workload is event-driven and short-lived — Azure Functions Flex
  Consumption.

## Prerequisites

- Azure CLI `>= 2.63` (for current autoscaler profile flags).
- An Entra **group** to act as the cluster admin (Workload Identity
  + Azure RBAC require Entra integration).
- For private cluster: a VNet with subnets sized for nodes, the API
  server projection (if using `--enable-apiserver-vnet-integration`),
  and ingress (Bastion / VPN / jumpbox to reach `kubectl`).
- An ACR if you'll pull images from one.

## Secure defaults

| Setting | Value | Why |
| --- | --- | --- |
| `--enable-aad --enable-azure-rbac` | enabled | Managed Microsoft Entra integration; Azure RBAC as the K8s authz layer. **Cannot be disabled once enabled** — plan it. |
| `--aad-admin-group-object-ids <group-oid>` | required | Group whose members get cluster-admin via Entra. |
| `--disable-local-accounts` | enabled (prod hardening) | Disables cert-based admin kubeconfig — break-glass via Entra group only. |
| `--network-plugin azure --network-plugin-mode overlay` | Azure CNI **Overlay** | Smaller VNet IP footprint than legacy Azure CNI; preferred for new clusters. |
| `--pod-cidr` | `10.244.0.0/16` (default) | Must not overlap with VNet or peered networks. |
| `--enable-private-cluster` (+ `--enable-apiserver-vnet-integration`) | enabled | Keeps the API server private; ingest via Bastion / `az aks command invoke` / VPN. |
| `--enable-oidc-issuer --enable-workload-identity` | enabled | Pod-level Entra federated credentials. **Pod-managed identity is deprecated** — Workload Identity replaces it. |
| `--enable-cluster-autoscaler --min-count --max-count` | min ≥ 3 (system); raise per workload | HA + adaptive cost. |
| System node pool | `mode: System`, `vmSize: Standard_D4s_v5+`, `availabilityZones: ['1','2','3']`, taint `CriticalAddonsOnly=true:NoSchedule` | Keeps system pods (CoreDNS, metrics-server) protected. **Burstable B-series is not supported for system pools.** |
| `--enable-addons azure-keyvault-secrets-provider` | enabled | CSI driver to mount KV secrets as files / sync to K8s secrets. |
| `--enable-addons azure-policy` | enabled | OPA-based policy enforcement. |
| `--enable-addons monitoring --workspace-resource-id` | enabled | Container Insights → LAW. |
| `--enable-image-cleaner --image-cleaner-interval-hours 48` | enabled | Trivy-based stale/vulnerable image removal. |
| Microsoft Defender for Containers | enable at **subscription scope** via `az security pricing create -n KubernetesService --tier Standard` | The dedicated `--enable-defender` AKS flag isn't well-documented; subscription-level pricing is the reliable path. |

## RBAC roles (verified names; look up GUIDs with `az role definition list --name "..."`)

- `Azure Kubernetes Service RBAC Cluster Admin`
- `Azure Kubernetes Service RBAC Admin`
- `Azure Kubernetes Service RBAC Writer`
- `Azure Kubernetes Service RBAC Reader`
- `Azure Kubernetes Service Cluster User Role` (needed for `az aks get-credentials`)

## Recipe — Azure CLI

```bash
RG=rg-aks-prod
LOC=eastus2
CLUSTER=aks-app-prod
ACR=acrappprod
LAW_ID=/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.OperationalInsights/workspaces/law-aks
ADMIN_GROUP_OID=<entra-group-objectid>

az group create -n "$RG" -l "$LOC"

# Subscription-level Defender for Containers
az security pricing create -n KubernetesService --tier Standard

# Cluster
az aks create \
  -g "$RG" -n "$CLUSTER" -l "$LOC" \
  --enable-aad --enable-azure-rbac --aad-admin-group-object-ids "$ADMIN_GROUP_OID" \
  --disable-local-accounts \
  --network-plugin azure --network-plugin-mode overlay --pod-cidr 10.244.0.0/16 \
  --enable-private-cluster --enable-apiserver-vnet-integration \
  --enable-oidc-issuer --enable-workload-identity \
  --node-count 3 --enable-cluster-autoscaler --min-count 3 --max-count 6 \
  --node-vm-size Standard_D4s_v5 \
  --node-taints "CriticalAddonsOnly=true:NoSchedule" \
  --enable-addons azure-keyvault-secrets-provider,azure-policy,monitoring \
  --workspace-resource-id "$LAW_ID" \
  --enable-image-cleaner --image-cleaner-interval-hours 48 \
  --generate-ssh-keys

# Attach ACR (assigns AcrPull to the kubelet MI)
az aks update -g "$RG" -n "$CLUSTER" --attach-acr "$ACR"

# User node pool for app workloads
az aks nodepool add -g "$RG" --cluster-name "$CLUSTER" --name userpool \
  --mode User --node-count 2 \
  --enable-cluster-autoscaler --min-count 2 --max-count 20 \
  --node-vm-size Standard_D4s_v5

# Get credentials (Entra login required; use --admin only for break-glass)
az aks get-credentials -g "$RG" -n "$CLUSTER"

# Grant a user/group cluster-admin via Azure RBAC (not local)
AKS_ID=$(az aks show -g "$RG" -n "$CLUSTER" --query id -o tsv)
az role assignment create \
  --role "Azure Kubernetes Service RBAC Cluster Admin" \
  --assignee <user-or-group-objectid> --scope "$AKS_ID"
```

## Recipe — Bicep (skeleton)

```bicep
param clusterName string
param location string = resourceGroup().location
param adminGroupObjectId string
param logAnalyticsWorkspaceId string
param tenantId string = subscription().tenantId

resource aks 'Microsoft.ContainerService/managedClusters@2026-01-01' = {
  name: clusterName
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    aadProfile: {
      managed: true
      enableAzureRBAC: true
      adminGroupObjectIDs: [ adminGroupObjectId ]
      tenantID: tenantId
    }
    disableLocalAccounts: true
    oidcIssuerProfile: { enabled: true }
    securityProfile: {
      workloadIdentity: { enabled: true }
      imageCleaner: { enabled: true, intervalHours: 48 }
    }
    networkProfile: {
      networkPlugin: 'azure'
      networkPluginMode: 'overlay'
      podCidr: '10.244.0.0/16'
      serviceCidr: '10.0.0.0/16'
      dnsServiceIP: '10.0.0.10'
      loadBalancerSku: 'standard'
    }
    apiServerAccessProfile: {
      enablePrivateCluster: true
      enablePrivateClusterPublicFQDN: false
    }
    agentPoolProfiles: [
      {
        name: 'system'
        mode: 'System'
        count: 3
        minCount: 3
        maxCount: 5
        enableAutoScaling: true
        vmSize: 'Standard_D4s_v5'
        osType: 'Linux'
        nodeTaints: [ 'CriticalAddonsOnly=true:NoSchedule' ]
        availabilityZones: [ '1', '2', '3' ]
      }
    ]
    addonProfiles: {
      azurepolicy: { enabled: true }
      omsagent: {
        enabled: true
        config: { logAnalyticsWorkspaceResourceID: logAnalyticsWorkspaceId }
      }
      azureKeyvaultSecretsProvider: {
        enabled: true
        config: { enableSecretRotation: 'true', rotationPollInterval: '2m' }
      }
    }
  }
}

resource userPool 'Microsoft.ContainerService/managedClusters/agentPools@2026-01-01' = {
  parent: aks
  name: 'userpool'
  properties: {
    mode: 'User'
    count: 2
    minCount: 2
    maxCount: 20
    enableAutoScaling: true
    vmSize: 'Standard_D4s_v5'
    osType: 'Linux'
    availabilityZones: [ '1', '2', '3' ]
  }
}
```

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| Pods get `ErrImagePull` from ACR | Kubelet MI lacks `AcrPull` on the registry | `az aks update --attach-acr <acr>`. ([Source](https://learn.microsoft.com/azure/aks/container-registry-auth-aks)) |
| Workload Identity pod can't get a token | Missing SA annotation `azure.workload.identity/client-id`, or FIC `--issuer` doesn't match `oidcIssuerProfile.issuerUrl` | Annotate the SA; verify the issuer URL matches exactly. ([Source](https://learn.microsoft.com/azure/aks/workload-identity-deploy-cluster)) |
| `kubectl` from laptop hangs on a private cluster | API server is private | Use Bastion / VPN / jumpbox, or `az aks command invoke -g $RG -n $CLUSTER -c "kubectl get pods -A"`. |
| Autoscaler thrashing | PDBs prevent eviction or `scale-down-delay-after-add` too short | Tune `--cluster-autoscaler-profile scale-down-delay-after-add=10m` and ensure PDBs allow voluntary disruption. |
| `Microsoft Entra integration can't be disabled` | Managed Entra is one-way | Plan before enabling. For break-glass, temporarily re-enable local accounts with a feature flag. |
| Federated credential just created — token exchange fails | Entra needs a few seconds to propagate | Add a `sleep 30` / retry loop in the pipeline after `az identity federated-credential create`. |
| RBAC role granted but `kubectl` still 403s | Entra ID authz webhook caches role assignments up to ~5 min | Wait. |
| System pods evicted because user workloads scheduled there | No taint on system pool | Add `CriticalAddonsOnly=true:NoSchedule` at create time (taints are immutable). ([Source](https://learn.microsoft.com/azure/aks/use-system-pools)) |

## References

- [Managed Microsoft Entra integration](https://learn.microsoft.com/azure/aks/managed-aad)
- [Azure CNI Overlay](https://learn.microsoft.com/azure/aks/azure-cni-overlay)
- [Workload Identity](https://learn.microsoft.com/azure/aks/workload-identity-deploy-cluster)
- [Cluster autoscaler](https://learn.microsoft.com/azure/aks/cluster-autoscaler)
- [System node pools](https://learn.microsoft.com/azure/aks/use-system-pools)
- [Key Vault Secrets Provider CSI driver](https://learn.microsoft.com/azure/aks/csi-secrets-store-driver)
- [ACR authentication](https://learn.microsoft.com/azure/aks/container-registry-auth-aks)
- [API server VNet integration](https://learn.microsoft.com/azure/aks/api-server-vnet-integration)
- [Image Cleaner](https://learn.microsoft.com/azure/aks/image-cleaner)
- [`Microsoft.ContainerService/managedClusters` template](https://learn.microsoft.com/azure/templates/microsoft.containerservice/managedclusters)
