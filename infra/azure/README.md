# Azure Deployment — Learning Navigator AI

Two deployment modes are supported:

| Mode | Entry point | Best for |
|------|-------------|----------|
| **Azure Functions** (serverless) | `api/azure_functions.py` | Event-driven, pay-per-use |
| **FastAPI on App Service / ACI** | `api/server.py` via `Dockerfile` | Persistent, low-latency |

---

## Quick Start (Local)

```bash
# 1. Copy the template and fill in real values
cp local.settings.json.template local.settings.json

# 2. Install Azure Functions Core Tools  (v4+)
npm i -g azure-functions-core-tools@4 --unsafe-perm true

# 3. Start locally
func start
```

## Infrastructure Provisioning (Bicep)

```powershell
# One-command deployment — creates Storage, AI Search,
# App Insights, Consumption Plan, and Function App.
.\deploy.ps1 -ResourceGroup "rg-learning-nav" -Environment dev
```

**What gets created:**

| Resource | SKU | Purpose |
|----------|-----|---------|
| Storage Account | Standard_LRS | Learner state + portfolio blobs |
| Blob Container | `learning-navigator` | Default container |
| Azure AI Search | Basic | RAG retrieval index |
| Application Insights | — | Logging & metrics |
| App Service Plan | Y1 (Consumption) | Serverless compute |
| Function App | Python 3.10 | Hosts the 3 functions |

## Environment Variables

All settings use the `LN_` prefix (see `infra/config.py`):

| Variable | Default | Description |
|----------|---------|-------------|
| `LN_STORAGE_BACKEND` | `local_json` | `local_json` / `local_sqlite` / `azure_blob` |
| `LN_AZURE_STORAGE_CONNECTION_STRING` | — | Azure Storage connection string |
| `LN_AZURE_STORAGE_CONTAINER` | `learning-navigator` | Blob container name |
| `LN_SEARCH_BACKEND` | `local_tfidf` | `local_tfidf` / `azure_ai_search` |
| `LN_AZURE_SEARCH_ENDPOINT` | — | `https://<svc>.search.windows.net` |
| `LN_AZURE_SEARCH_KEY` | — | Admin API key |
| `LN_AZURE_SEARCH_INDEX` | `learning-navigator-index` | Index name |
| `LN_ADAPTIVE_ROUTING_ENABLED` | `true` | Cost-aware agent routing |
| `LN_COST_BUDGET_PER_TURN` | `10.0` | Budget per orchestration turn |

## Docker (FastAPI mode)

```bash
docker build -t learning-navigator -f infra/azure/Dockerfile .
docker run -p 8000:8000 --env-file .env learning-navigator
```

## Files

| File | Purpose |
|------|---------|
| `main.bicep` | IaC template — all Azure resources |
| `deploy.ps1` | One-click deployment script |
| `host.json` | Azure Functions host configuration |
| `local.settings.json.template` | Local dev settings (copy → `local.settings.json`) |
| `requirements-azure.txt` | Pinned deps for Azure Functions packaging |
| `Dockerfile` | Container image for FastAPI deployment |
