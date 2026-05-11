# observability/

Skills for collecting telemetry from every Azure resource an agent
provisions.

## In scope

- Application Insights (workspace-based; connection string ingestion)
- Azure Monitor diagnostic settings (universal log + metric routing)
- Log Analytics workspace setup (planned)
- Azure Monitor alerts (planned)
- Workbooks and dashboards (planned)

## Default posture

- Every workload-bearing resource gets a diagnostic setting routing
  `allLogs` + `AllMetrics` to a centralized Log Analytics workspace.
- Application telemetry uses the **connection string**, not the
  deprecated instrumentation key.
- Sampling enabled in production to control ingestion cost; never
  disabled in `Live Metrics` view.
