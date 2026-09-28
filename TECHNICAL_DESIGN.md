# Technical Design Document: Enterprise Document Research Agent (ERA)

## 1. System Overview & Architecture

The **Enterprise Document Research Agent (ERA)** is an AI system designed to answer complex enterprise queries. It operates on a **RAG-first** (Retrieval-Augmented Generation) paradigm using internal Google Drive documents, backed by a vector database (Pinecone) and a metadata database (PostgreSQL). When internal document context is unavailable or insufficient to accurately answer a query, the agent dynamically fails over to an external web search tool (DuckDuckGo Search) to synthesize an up-to-date response.

```mermaid
graph TD
    User([User / API Client]) -->|POST /query| FastAPI[FastAPI Agent Service]
    
    subgraph Storage & Indexing
        GDrive[Google Drive Folder] -->|OAuth 2.0 Ingestion| Ingest[Ingestion Service]
        Ingest -->|Chunking & ADA-002 Embeddings| Pinecone[(Pinecone Vector DB)]
        Ingest -->|File & Chunk Mapping| Postgres[(PostgreSQL Metadata DB)]
    end

    subgraph Agent Core Execution
        FastAPI -->|1. Vector Search top-k| Pinecone
        Pinecone -->|2. Matched Vector IDs| FastAPI
        FastAPI -->|3. Filter score >= 0.75| ThresholdCheck{Score >= 0.75?}
        
        ThresholdCheck -->|Yes| CitationFetch[Fetch file_name from Postgres]
        CitationFetch --> LLMPrompt[Prompt GPT-4 Turbo with RAG Context]
        
        LLMPrompt --> FailureCheck{Contains [CONTEXT_INSUFFICIENT]?}
        
        ThresholdCheck -->|No 0 chunks| Fallback[Execute DuckDuckGo Web Search]
        FailureCheck -->|Yes| Fallback
        
        LLMPrompt -->|No - Valid Answer| Response1[Internal Documents Response]
        Fallback --> LLMSynthesize[Synthesize Web Results via GPT-4 Turbo]
        LLMSynthesize --> Response2[External Search Response]
    end

    Response1 --> FinalJSON([JSON Response: answer, source_type, sources])
    Response2 --> FinalJSON
```

---

## 2. Core Components & Technical Specifications

### A. Ingestion Service (`ingestion_service.py`)
- **Authentication**: Secure OAuth 2.0 authorization code flow with PKCE (`credentials.json` $\rightarrow$ persisted `token.json`).
- **File Retrieval**: Google Drive v3 REST API. Downloads files from specified `GDRIVE_FOLDER_ID`. Exports Google Docs/Sheets as plain text.
- **Preprocessing**: LangChain `RecursiveCharacterTextSplitter` configured with `CHUNK_SIZE=1000` and `CHUNK_OVERLAP=200`.
- **Embeddings**: OpenAI `text-embedding-ada-002` (1536 dimensions, normalized cosine similarity).
- **Vector Database**: Pinecone serverless vector index (`cosine` distance metric).
- **Metadata Database**: PostgreSQL database storing document metadata (`file_id`, `file_name`, `mime_type`, `ingested_at`) and chunk mapping (`chunk_id`, `vector_id`, `file_id`, `chunk_text`).

### B. Agent Service (`agent_service.py`)
- **Web Framework**: FastAPI running on Python 3.10 and `uvicorn`.
- **Primary Search (RAG)**:
  - Generates query embedding via `text-embedding-ada-002`.
  - Executes k-NN query against Pinecone index (`top_k=5`).
  - Filters results using `SIMILARITY_THRESHOLD = 0.75`.
- **Citation Resolution**: SQL query against PostgreSQL `document_chunks` and `documents` tables using `vector_id`s to fetch original source `file_name`s.
- **Failure Detection**:
  - LLM System Prompt instructs `gpt-4-turbo` with strict constraints.
  - If the answer cannot be generated *solely* from the RAG context, the LLM emits `[CONTEXT_INSUFFICIENT]`.
- **Fallback Search**:
  - Activated if 0 chunks pass threshold or LLM emits `[CONTEXT_INSUFFICIENT]`.
  - Uses `DuckDuckGoSearchRun` to gather external web context.
- **Synthesis & Output Formatting**:
  - Synthesizes answer using `gpt-4-turbo`.
  - Returns structured Pydantic schema: `answer` (str), `source_type` ("Internal Documents" | "External Search"), and `sources` (list of strings).

---

## 3. Database Schema

```sql
CREATE TABLE documents (
    file_id VARCHAR(255) PRIMARY KEY,
    file_name VARCHAR(512) NOT NULL,
    mime_type VARCHAR(255),
    ingested_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE document_chunks (
    chunk_id VARCHAR(255) PRIMARY KEY,
    vector_id VARCHAR(255) NOT NULL UNIQUE,
    file_id VARCHAR(255) NOT NULL REFERENCES documents(file_id) ON DELETE CASCADE,
    chunk_index INT NOT NULL,
    chunk_text TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_document_chunks_vector_id ON document_chunks(vector_id);
CREATE INDEX idx_document_chunks_file_id ON document_chunks(file_id);
```

---

## 4. API Specification

### Endpoint: `POST /query`
**Request Body**:
```json
{
  "query": "What is our company's Q3 revenue retention rate?"
}
```

**Response (200 OK - Internal RAG Success)**:
```json
{
  "answer": "According to the Q3 Financial Report, the company's net revenue retention rate for Q3 was 118%.",
  "source_type": "Internal Documents",
  "sources": [
    "Q3_Financial_Report.pdf",
    "Investor_Presentation_2025.pdf"
  ]
}
```

**Response (200 OK - Fallback Success)**:
```json
{
  "answer": "The current market price of Brent crude oil is approximately $78.50 per barrel as of recent trading sessions.",
  "source_type": "External Search",
  "sources": [
    "External Web Search (DuckDuckGo)"
  ]
}
```

### Endpoint: `GET /health`
**Response (200 OK)**:
```json
{
  "status": "healthy",
  "service": "Enterprise Document Research Agent"
}
```

---

## 5. Security & Governance Design
1. **Credentials Isolation**: All sensitive credentials (`OPENAI_API_KEY`, `PINECONE_API_KEY`, DB passwords) are loaded via environment variables or cloud secret managers.
2. **Database Least Privilege**: PostgreSQL user restricted to `era_db` operations.
3. **Container Security**: Runs as non-root user in lightweight Debian-slim container.
