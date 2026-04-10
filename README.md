<div align="center">

<img src="docs/logo.png" alt="Patra Toolkit Logo" width="300"/>

  # Patra Knowledge Base

[![License](https://img.shields.io/badge/License-BSD%203--Clause-blue.svg)](https://opensource.org/licenses/BSD-3-Clause)
[![Build Status](https://github.com/Data-to-Insight-Center/patra-kg/actions/workflows/ci.yml/badge.svg)](https://github.com/Data-to-Insight-Center/patra-kg/actions)

</div>

The Patra Knowledge Base is a system designed to manage and track AI/ML models, with the objective of making them more accountable and trustworthy. It's a key part of the Patra ModelCards framework, which aims to improve transparency and accountability in AI/ML models throughout their entire lifecycle. This includes the model's initial training phase, subsequent deployments, and ongoing usage, whether by the same or different individuals.

**Tag**: CI4AI, PADI

## Status Notice

Patra's active backend is now the **FastAPI + PostgreSQL** service under `rest_server/`.

The following Neo4j-based components are **retained only for archive/reference compatibility and are no longer part of the active backend path**:
- `legacy/legacy_server/`
- `mcp_server/`
- `legacy/ingester/neo4j_ingester.py`
- `legacy/reconstructor/mc_reconstructor.py`
- Neo4j-oriented Docker/Make targets

For all new development, deployment, integration, and operational work, use the PostgreSQL-backed REST API only.

## Explanation

At the heart of the Patra Knowledge Base is the concept of Model Cards. These cards are essentially detailed records that provide essential information about each AI/ML model. This information includes technical details like the model's accuracy and latency, but it goes beyond that to include non-technical aspects such as fairness, explainability, and the model's behavior in various deployment environments. This holistic approach is intended to create a comprehensive understanding of the model's strengths and weaknesses, enabling more informed decisions about its use and deployment

Key features and capabilities of the Patra ModelCards Framework include:

- **Semi-automated information capture:** Patra reduces the burden of manual documentation by automatically capturing information about model fairness, explainability, and performance in different deployment environments. This automation is facilitated by the [Model Card Toolkit](https://github.com/Data-to-Insight-Center/patra-toolkit)  , which invokes analysis tools and integrates the results directly into the Model Cards.
  
- **Relational system of record:** Patra's active backend now uses PostgreSQL as the system of record for model cards, datasheets, and protected asset ingestion APIs. Neo4j-era graph components are preserved only as legacy reference code and are no longer the supported runtime path.
  
- **Provenance tracking:** Patra leverages the concepts of **forward and backward provenance** to comprehensively track the relationships between models, datasets, and deployment instances. This makes it possible to understand the lineage of models, trace their origins, and analyze their usage patterns.
  
- **Real-time deployment information:** Patra integrates with the [CKN Edge AI Framework](https://github.com/Data-to-Insight-Center/cyberinfrastructure-knowledge-network)  to capture real-time information about model execution in edge environments. This includes data on performance, resource usage, and other relevant metrics, which can be used to optimize deployments and gain insights into model behavior in real-world settings.
  
- **Machine-actionable API:** Patra provides a **machine-actionable API** that allows intelligent systems in the edge-cloud continuum to query the knowledge base and make informed decisions about model selection. This enables automated model selection based on various criteria, including fairness, explainability, and performance metrics, further enhancing accountability and transparency.
  
- **Versioning and Similarity Analysis:** Patra infers relationships between model cards such as **"alternateOf," "revisionOf," and "transformativeUseOf"** by leveraging embedding vectors and cosine similarity comparisons. This capability is essential for tracking model evolution, identifying different versions, and understanding how models are adapted and reused over time.

By combining these capabilities, the Patra Knowledge Base provides a robust foundation for **trustworthy and accountable AI/ML model management within the edge-cloud continuum**. This framework addresses crucial aspects of transparency, provenance tracking, and performance monitoring, ultimately contributing to more responsible and reliable AI deployments.

For more information, please refer to the [Patra ModelCards paper](https://ieeexplore.ieee.org/document/10678710).

### Patra Servers

Patra provides multiple server implementations for different use cases.

#### 1. Primary REST API (FastAPI + PostgreSQL)

The primary REST API is implemented with FastAPI and backed by PostgreSQL. It is intended for new integrations and powers the privacy-aware model card and datasheet APIs.

- **Code location**: `rest_server/`
- **Default port**: `8000`
- **Example endpoints** (non-exhaustive):
  - `GET /` – Simple health/info endpoint.
  - `GET /modelcards` – List model cards (public-only by default; private when authorized).
  - `GET /modelcard/{id}` – Retrieve a single model card.
  - `PUT /modelcard/{id}` – Update a model card and its linked AI model (authenticated).
  - `GET /datasheets` – List datasheets (public-only by default; private when authorized).
  - `GET /datasheet/{identifier}` – Retrieve a single datasheet with normalized DataCite-style metadata.
  - `PUT /datasheet/{identifier}` – Update a datasheet, including title and description (authenticated).

The FastAPI app is exposed via the `rest_server` package (see `rest_server/main.py`) and is built into the Docker image `plalelab/patra-backend:latest` using `rest_server/Dockerfile` (see `scripts/build-push-backend.sh`).

#### 2. Legacy REST Server (Flask + Neo4j)

The legacy REST server is built using Flask and exposes a RESTful API for interaction with the Patra Knowledge Graph (KG) stored in Neo4j. It is retained in-repo for archive/reference purposes only and is not part of the active backend going forward.

- **Code location**: `legacy/legacy_server/`
- **Default port**: `5002`

Key endpoints include:

| Endpoint                                               | Method | Description                                                                                                  |
|--------------------------------------------------------|--------|--------------------------------------------------------------------------------------------------------------|
| `/modelcard`                                           | POST   | Create (upload) a model card.                                                                                |
| `/modelcard/{id}`                                      | GET    | Retrieve a model card.                                                                                       |
| `/modelcard/{id}`                                      | HEAD   | Return linkset relations via HTTP Link headers.                                                              |
| `/modelcard/{id}`                                      | PUT    | Update an existing model card.                                                                               |
| `/datasheet`                                           | POST   | Upload a datasheet.                                                                                          |
| `/modelcards/search?q=...`                             | GET    | Full-text search for model cards.                                                                            |
| `/modelcard/{id}/download_url`                         | GET    | Retrieve the download URL for a model artifact.                                                              |
| `/modelcards`                                          | GET    | List all model cards.                                                                                        |
| `/modelcard/{id}/deployments`                          | GET    | Retrieve deployments for a model.                                                                            |
| `/modelcard/{id}/location`                             | PUT    | Update the model's location.                                                                                 |
| `/modelcard/id`                                        | POST   | Generate a persistent model ID (PID) for author, name, version.                                             |
| `/modelcard/{id}/huggingface_credentials`              | GET    | Get Hugging Face credentials (if configured).                                                                |
| `/modelcard/{id}/github_credentials`                   | GET    | Get GitHub credentials (if configured).                                                                      |
| `/modelcard/{id}/linkset`                              | GET    | Retrieve linkset relations (same output as HEAD but with empty body & Link headers).                         |
| `/device`                                              | POST   | Register an edge device.                                                                                     |
| `/user`                                                | POST   | Register a user.                                                                                             |

For more information on the legacy REST endpoints, please refer to the [API documentation.](docs/patra_openapi.json)

#### 3. MCP (Model Context Protocol) Server, Suspended
The in-repo MCP server is Neo4j-backed legacy code retained for reference. It is not part of the active PostgreSQL backend path.

| Endpoint                                    | Type     | Description                                                                                                  |
|-------------------------------------------------|----------|--------------------------------------------------------------------------------------------------------------|
| `modelcard://{id}`                               | Resource | Retrieve a model card by ID.                                                                                 |
| `modelcard://{id}/download_url`                  | Resource | Retrieve the download URL for a model artifact.                                                              |
| `modelcard://{id}/deployments`                   | Resource | Retrieve deployments for a model.                                                                            |
| `modelcard://{id}/linkset`                       | Resource | Retrieve linkset relations for a model card.                                                                 |
| `create_edge`                                    | Tool     | Create an edge between two nodes in the Patra Knowledge graph.                                            |
| `search_modelcards`                              | Tool     | Full-text search for model cards.                                                                            |
| `list_modelcards`                                | Tool     | List all model cards.                                                                                        |
| `upload_modelcard`                               | Tool     | Upload a model card.                                                                                |
| `update_modelcard`                               | Tool     | Update an existing model card.                                                                               |
| `upload_datasheet`                               | Tool     | Upload a datasheet.                                                                                          |
| `update_model_location`                          | Tool     | Update the model's location.                                                                                 |
| `register_device`                                | Tool     | Register an edge device.                                                                                     |
| `register_user`                                  | Tool     | Register a user.                                                                                              |

The MCP server runs on port `8050` and uses Server-Sent Events (SSE) transport for communication.

---



## How-To Guide

### Prerequisites

#### System Requirements
- [Docker](https://www.docker.com/get-started) and [Docker Compose](https://docs.docker.com/compose) installed and running.
- Open network access to the following ports:
  - `8000` (Primary REST API)
  - `5002` (legacy Flask server, suspended)
  - `8050` (legacy MCP server, suspended)

#### Dependencies
- **PostgreSQL**: Required for the active FastAPI backend.
- **Neo4j**: Legacy-only dependency retained for archived code paths; not required for new backend work.
- [Optional] **OpenAI API Key**: If the system needs to support Model Card similarities, you need to obtain a valid Open AI API key. Refer to the [OpenAI documentation](https://platform.openai.com) for instructions. This is disabled by default.


### 1. Set up Environment Variables

**Model Similarity (Optional)**  
To enable model similarity detection using OpenAI embeddings, set `ENABLE_MC_SIMILARITY` to `True` and provide your OpenAI API key:
```bash
export ENABLE_MC_SIMILARITY=True
export OPENAI_API_KEY=<YOUR_OPENAI_API_KEY>
```

**Hugging Face Integration (Optional)**  
To upload models and artifacts to Hugging Face, create a repository and generate an access token. Then, set the following environment variables:
```bash
export HF_HUB_USERNAME=<your-hf-username>
export HF_HUB_TOKEN=<your-hf-access-token>
```
Requires write access to the target Hugging Face repo.

**GitHub Integration (Optional)**  
To upload models and artifacts to GitHub, create a repository and generate an access token. Then, set the following environment variables:
```bash
export GH_HUB_USERNAME=<your-github-username>
export GH_HUB_TOKEN=<your-github-personal-access-token>
```
Requires `repo` scope enabled on the GitHub token.

### 2. Clone the repository and start services
```bash
git clone https://github.com/Data-to-Insight-Center/patra-kg.git
cd patra-kg
docker compose -f docker-compose.backend.yml up --build
```
  
The supported service stack is the PostgreSQL-backed FastAPI app under `rest_server/`, started with `docker-compose.backend.yml`.
Legacy Neo4j compose assets remain in the repository for archival reference only and should not be treated as the supported deployment path.

- To shut down services, use:
    ```bash
    docker compose -f docker-compose.backend.yml down
    ```

### 3. Using the MCP Server (Optional)

This section describes the suspended in-repo Neo4j-based MCP server for archival/reference purposes only. It is not part of the active PostgreSQL backend and should not be used for new integrations.

The legacy MCP server provides:
- **4 Resources** for reading model card data by identifier
- **10 Tools** for operations, queries, and state modifications

**For Claude Desktop:**
1. Add to your Claude Desktop configuration (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

For the legacy archived MCP server:
```json
{
  "mcpServers": {
    "patra-kg": {
      "url": "http://localhost:8050/sse"
    }
  }
}
```

**For Custom AI Agents:**
Connect to the MCP server endpoint:
- MCP Server: `http://localhost:8050/sse` (legacy archived endpoint)

**Historical Example Usage:**

*With MCP Server:*
```
User: "Upload this model card and then search for similar models"
AI Assistant: [Uses upload_modelcard tool, then search_modelcards tool]
Result: Model card uploaded and similar models found
```

*Reading model card data:*
```
User: "Get information about model card test-mc-123"
AI Assistant: [Reads modelcard://test-mc-123 resource]
Result: Returns complete model card data
```
---

## License

The **Patra Knowledge Base** is copyrighted by the **Indiana University Board of Trustees** and distributed under the **BSD 3-Clause License**. See the `LICENSE.txt` file for more details.

## Acknowledgements
This research is funded in part through the National Science Foundation under award #2112606, AI Institute for Intelligent CyberInfrastructure with Computational Learning in the Environment (ICICLE), and in part through Data to Insight Center (D2I) at Indiana University.

