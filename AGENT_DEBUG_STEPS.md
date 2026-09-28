# Comprehensive Guide: Agent Local Setup, VS Code Development, GCP Deployment, Debugging & Enhancement

## Executive Summary
This technical guide provides complete, step-by-step instructions for the **Enterprise Document Research Agent (ERA)** covering:
1. Local laptop setup and testing.
2. Visual Studio Code (VS Code) environment setup for code enhancements and interactive debugging.
3. Google Cloud Platform (GCP Cloud Run) deployment and multi-language application integration.
4. Detailed error debugging for Vector DB (Pinecone), Vector Search, Database, and LLM issues.
5. Agent enhancement techniques and best practices.

---

## 1. Local Laptop Setup & Testing

### Prerequisites
- **Python**: 3.10 or higher
- **Git**: 2.30 or higher
- **Package Manager**: `pip` and `virtualenv`
- **CLI Tools**: `curl`

### Step 1.1: Clone Repository & Set Up Virtual Environment
```bash
# Clone the repository
git clone https://github.com/prashantkvind/enterprise-document-research-agentV1.git
cd enterprise-document-research-agentV1

# Create Python virtual environment
python3 -m venv .venv

# Activate virtual environment
# On Linux/macOS:
source .venv/bin/activate
# On Windows (PowerShell):
# .venv\Scripts\Activate.ps1
```

### Step 1.2: Install Dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 1.3: Configure Environment Variables
Create or edit the `.env` file in the project root directory:
```env
# Application Settings
ENVIRONMENT=development
LOG_LEVEL=INFO
DOCUMENTS_DIR=./documents

# Vector Database (Pinecone)
PINECONE_API_KEY=your_pinecone_api_key_here
PINECONE_ENVIRONMENT=us-east-1
PINECONE_INDEX_NAME=enterprise-docs

# Metadata Database (PostgreSQL)
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=era_metadata
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_password_here

# LLM Provider (OpenAI)
OPENAI_API_KEY=your_openai_api_key_here

# Vector Search Thresholds
SIMILARITY_THRESHOLD=0.75
CHUNK_SIZE=500
CHUNK_OVERLAP=50
```

### Step 1.4: Add Test Documents
Create sample documents in the `./documents` directory:
```bash
mkdir -p documents

# Create sample policy file
cat << 'EOF' > documents/company_policy.md
# Enterprise Working Policy
## 1. Remote Work Policy
Employees can work remotely up to 3 days per week with manager approval. Core working hours are from 10:00 AM to 4:00 PM EST.

## 2. Q3 Retention Metrics
In Q3, our Net Revenue Retention (NRR) reached 118%, driven by expansion in enterprise tier accounts.
EOF

# Create sample financial report
cat << 'EOF' > documents/q3_financial_report.txt
Q3 Financial Summary Report
=================================
Total Revenue: $14.2M
Gross Margin: 74%
Net Revenue Retention: 118%
Operating Expenses: $8.5M
EBITDA: $2.1M
EOF
```

### Step 1.5: Launch and Test Agent Service
Run the FastAPI agent service:
```bash
python agent_service.py
```
*The service starts on `http://localhost:8000`.*

#### Testing Options:
1. **Interactive UI Playground**: Open `http://localhost:8000` in your web browser.
2. **Swagger OpenAPI Docs**: Open `http://localhost:8000/docs`.
3. **cURL Request**:
```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What is our Q3 Net Revenue Retention rate?",
    "location": "./documents"
  }'
```

---

## 2. Visual Studio Code Setup for Agent Enhancement

### Step 2.1: Open Project in VS Code
Launch VS Code and open the repository directory:
```bash
code .
```

### Step 2.2: Recommended Extensions
Install the following extensions from the VS Code Marketplace:
- **Python** (`ms-python.python`)
- **Pylance** (`ms-python.vscode-pylance`)
- **Docker** (`ms-azuretools.vscode-docker`)
- **GitLens** (`eamodio.gitlens`)
- **REST Client** (`humao.rest-client`)

### Step 2.3: Select Python Interpreter
1. Press `Ctrl+Shift+P` (or `Cmd+Shift+P` on macOS).
2. Type `Python: Select Interpreter`.
3. Select the interpreter inside `.venv`: `./.venv/bin/python`.

### Step 2.4: Create Debug Configuration (`launch.json`)
Create a file at `.vscode/launch.json` to enable 1-click breakpoint debugging:
```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Debug Agent Service (FastAPI)",
      "type": "debugpy",
      "request": "launch",
      "module": "uvicorn",
      "args": [
        "agent_service:app",
        "--reload",
        "--port",
        "8000"
      ],
      "jinja": true,
      "justMyCode": false,
      "envFile": "${workspaceFolder}/.env"
    },
    {
      "name": "Debug Standalone Test Script",
      "type": "debugpy",
      "request": "launch",
      "program": "${workspaceFolder}/agent_service.py",
      "console": "integratedTerminal",
      "envFile": "${workspaceFolder}/.env"
    }
  ]
}
```

### Step 2.5: Developer Enhancement Workflow
- **Adding new document formats** (`.pdf`, `.pptx`, `.docx`): Modify `LocalDirectoryRetriever._read_file_content()` in `agent_service.py`.
- **Modifying RAG Prompt Templates**: Update system prompts in `AgentOrchestrator.process_query()` in `agent_service.py`.
- **Customizing Distance Metrics**: Adjust `SIMILARITY_THRESHOLD` or chunk sizes in `config.py`.

---

## 3. GCP Deployment & Application Integration Guide

### Step 3.1: Prerequisites for GCP
- Active GCP Account with Billing Enabled.
- Install `gcloud` CLI: `gcloud components install beta`.
- Enable GCP Services:
```bash
gcloud services enable run.googleapis.com \
                       artifactregistry.googleapis.com \
                       cloudbuild.googleapis.com \
                       secretmanager.googleapis.com
```

### Step 3.2: Authenticate and Set Project
```bash
gcloud auth login
gcloud config set project YOUR_GCP_PROJECT_ID
```

### Step 3.3: Build & Push Container Image
Build the container image using Google Cloud Build:
```bash
gcloud builds submit --tag gcr.io/YOUR_GCP_PROJECT_ID/enterprise-document-research-agent:v1 .
```

### Step 3.4: Deploy to GCP Cloud Run
Deploy the container as a managed serverless web service:
```bash
gcloud run deploy era-agent \
  --image gcr.io/YOUR_GCP_PROJECT_ID/enterprise-document-research-agent:v1 \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars ENVIRONMENT=production,DOCUMENTS_DIR=./documents,SIMILARITY_THRESHOLD=0.75 \
  --set-secrets PINECONE_API_KEY=pinecone-api-key:latest,OPENAI_API_KEY=openai-api-key:latest
```

---

### Step 3.5: Application Integration

#### Option A: Python Integration Example
```python
import requests

AGENT_URL = "https://era-agent-xyz-uc.a.run.app/query" # Replace with your Cloud Run URL

payload = {
    "query": "What is our remote work policy?",
    "location": "./documents"
}

response = requests.post(AGENT_URL, json=payload)
data = response.json()

print("Answer:", data["answer"])
print("Source Type:", data["source_type"])
print("Sources Used:", data["sources"])
for match in data.get("matches", []):
    print(f"Match: {match['file_name']} ({int(match['score']*100)}%): {match['snippet']}")
```

#### Option B: JavaScript / Node.js Integration Example
```javascript
const AGENT_URL = "https://era-agent-xyz-uc.a.run.app/query";

async function queryAgent(userQuery) {
  const response = await fetch(AGENT_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query: userQuery,
      location: "./documents"
    })
  });

  const result = await response.json();
  console.log("Answer:", result.answer);
  console.log("Matches:", result.matches);
}

queryAgent("What is our Q3 Net Revenue Retention rate?");
```

---

## 4. Comprehensive Debugging & Troubleshooting Guide

### Vector DB (Pinecone) & Vector Search Debugging

#### Issue 1: `(401) Unauthorized HTTP response`
- **Symptom**: `PineconeException: (401) Reason: Unauthorized`.
- **Root Cause**: `PINECONE_API_KEY` is missing or set to placeholder string (`your_pinecone_api_key_here`).
- **Resolution**:
  1. Generate API Key at [https://app.pinecone.io](https://app.pinecone.io).
  2. Update `.env` with `PINECONE_API_KEY=pcsk_...`.
  3. *Note*: The agent automatically catches this exception and routes queries to `LocalDirectoryRetriever` without crashing.

#### Issue 2: Zero Chunks / Low Relevance Scores
- **Symptom**: Query returns empty chunks list or defaults to DuckDuckGo search even when documents exist.
- **Root Causes**:
  - `SIMILARITY_THRESHOLD` is set too high (e.g. `0.90`).
  - Embedding model mismatch (query embedded with `text-embedding-ada-002` vs index created with `text-embedding-3-small`).
- **Resolution**:
  1. Lower threshold in `config.py` / `.env` to `0.70` or `0.65`.
  2. Verify vector dimension matches model output (`1536` for `text-embedding-ada-002`).

#### Issue 3: PostgreSQL Citation Metadata Connection Failed
- **Symptom**: `psycopg2.OperationalError: could not connect to server`.
- **Resolution**:
  - Verify PostgreSQL container/service is running: `pg_isready -h localhost -p 5432`.
  - Execute database initialization script:
    ```bash
    psql -h localhost -U postgres -d era_metadata -f database_setup.sql
    ```

---

## 5. Agent Enhancement Techniques

### 1. Hybrid Search (Dense Vector + Sparse BM25)
Combine semantic vector embeddings with keyword BM25 scoring for exact keyword precision (e.g. serial numbers, legal clause identifiers).

### 2. Cross-Encoder Re-Ranking
Add a re-ranking model (e.g. `Cohere Rerank` or `bge-reranker-large`) after initial vector retrieval to score top 20 candidates down to top 3 most contextually precise chunks.

### 3. Asynchronous File Ingestion Pipelines
Use Celery / Redis or Google Cloud Tasks for asynchronous background chunking and embedding generation when ingesting thousands of large documents.

### 4. Agent Observability & Tracing
Integrate OpenTelemetry or LangSmith for end-to-end latency monitoring, prompt-response logging, and retrieval debugging.

---
*Documentation generated for Enterprise Document Research Agent (ERA).*
