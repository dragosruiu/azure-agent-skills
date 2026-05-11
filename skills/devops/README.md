# devops/

Skills for shipping to Azure from CI/CD pipelines without long-lived
credentials.

## In scope

- GitHub Actions OIDC to Azure (federated identity, no client secrets)
- Azure DevOps service connections with workload identity federation (planned)
- Azure Developer CLI (`azd`) templates (planned)
- Azure Deployment Environments (planned)

## Default posture

- **No client secrets in CI.** Use federated identity credentials and
  OIDC tokens — see `github-actions-oidc-to-azure`.
- Scope the federated credential's `subject` to a specific repo + branch
  (or environment), never `*`.
- Grant the federated identity the *least* RBAC role needed (typically
  `Contributor` only on the target resource group, not subscription).
- Use `what-if` for IaC changes before applying them.
