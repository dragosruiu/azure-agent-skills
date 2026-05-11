# ai-and-ml/

Skills for adding AI capabilities to applications using Azure-hosted
models.

## In scope

- Azure OpenAI Service (GPT and embedding model deployments)
- Azure AI Search (planned — RAG retrieval layer)
- Azure AI Foundry / Azure AI Studio (planned)

## Default posture

- `disableLocalAuth: true` — no API keys; use Entra ID with the
  "Cognitive Services OpenAI User" role assigned to the calling MI.
- Public network access disabled; access via private endpoint to
  `privatelink.openai.azure.com` for production workloads.
- Pin to a specific `api-version` query parameter; never default to
  "latest".
- Attach a custom content filter to every production deployment.
