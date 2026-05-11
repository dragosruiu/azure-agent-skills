# compute/

Skills for choosing where to run code and configuring the runtime
securely.

## In scope

- Azure App Service (Web Apps, Linux + Windows)
- Azure Functions (Flex Consumption and Premium)
- Azure Container Apps (Consumption and Dedicated profiles)
- Azure Kubernetes Service (planned)
- Virtual Machines (planned)
- Azure Container Instances (planned)

## How to choose

| If the workload is... | Pick |
| --- | --- |
| Stateless HTTP API or web UI | App Service or Container Apps |
| Event-driven, short-lived, scale-to-zero | Functions (Flex Consumption) |
| Containerized microservices, want Dapr / KEDA / revisions | Container Apps |
| Needs full cluster control (CRDs, custom networking, GPUs) | AKS |
| Lift-and-shift Windows / IaaS workload | Virtual Machines |

Each skill enforces: managed identity over keys, HTTPS-only, TLS 1.2+,
Application Insights for observability, public network access disabled
where feasible.
