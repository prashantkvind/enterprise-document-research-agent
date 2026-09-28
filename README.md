# Enterprise Document Research Agent (ERA)

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-green.svg)](https://fastapi.tiangolo.com/)
[![LangChain](https://img.shields.io/badge/LangChain-0.2.0+-orange.svg)](https://www.langchain.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

An enterprise-grade intelligent research agent that prioritizes local company documents via Retrieval-Augmented Generation (RAG) and dynamically falls back to external web search (DuckDuckGo) when internal context is missing or insufficient.

---

## Technical Highlights

- **Dual Database Architecture**: Vector embeddings stored in **Pinecone (VDB)**; citation metadata stored in **PostgreSQL (MDB)**.
- **Strict Failure Detection**: Prompts `gpt-4-turbo` to issue `[CONTEXT_INSUFFICIENT]` when internal documents cannot fulfill the query.
- **Dynamic Tool Routing**: Automatically transitions to DuckDuckGo Search fallback upon RAG context absence or insufficiency.
- **Source Attribution**: Transparently cites document file names for RAG results or indicates web search fallback.
- **Production Ready**: Full FastAPI REST implementation, Dockerized deployment, and Google Cloud Platform (GCP) Cloud Run guide.

---

## Directory Structure

```
.
├── .env                  # Configuration template
├── requirements.txt      # Dependencies
├── config.py             # Settings loader
├── database_setup.sql    # PostgreSQL schema
├── ingestion_service.py  # Google Drive OAuth, text chunking & Pinecone/Postgres indexing
├── agent_service.py      # FastAPI agent orchestration server
├── Dockerfile            # Container definition
├── TECHNICAL_DESIGN.md   # Architectural specifications & sequence flows
└── DEPLOYMENT_GUIDE.md   # Laptop local testing & GCP Cloud Run deployment guide
```

---

## Quick Start

1. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
2. **Configure environment**:
   Copy `.env` and fill in your keys.
3. **Run Ingestion**:
   ```bash
   python ingestion_service.py
   ```
4. **Launch Agent**:
   ```bash
   python agent_service.py
   ```
5. **Query Agent**:
   ```bash
   curl -X POST http://localhost:8000/query \
     -H "Content-Type: application/json" \
     -d '{"query": "What is our Q3 retention target?"}'
   ```

For detailed architectural design, see [TECHNICAL_DESIGN.md](file:///config/.gemini/antigravity/scratch/era/TECHNICAL_DESIGN.md).  
For laptop local testing and GCP Cloud Run deployment, see [DEPLOYMENT_GUIDE.md](file:///config/.gemini/antigravity/scratch/era/DEPLOYMENT_GUIDE.md).
