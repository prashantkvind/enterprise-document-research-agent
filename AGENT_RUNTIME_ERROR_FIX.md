# Technical Documentation: Agent Runtime Error Fix & Location Search Enhancement

## Executive Summary
This document provides a comprehensive technical breakdown of the fixes applied to resolve runtime errors (including `HTTP 401 Unauthorized` and `ModuleNotFoundError` crashes) in the **Enterprise Document Research Agent (ERA)**. It also details the architectural enhancements implemented to enable document searching within a specified directory location.

---

## 1. Root Cause Analysis

### Issue A: Pinecone 401 Unauthorized Error
- **Symptom**: When querying `agent_service.py` without valid Pinecone credentials, the agent crashed with `Error: An error occurred in agent orchestration: (401) Reason: Unauthorized HTTP response headers...`.
- **Root Cause**: Unhandled exception during `Pinecone(api_key=...).Index(...).query()` when `PINECONE_API_KEY` was set to a placeholder (`your_pinecone_api_key_here`) or an invalid token.

### Issue B: Missing Module Crashes
- **Symptom**: `ModuleNotFoundError` / `ImportError` for packages like `psycopg2`, `pinecone`, or `ddgs`.
- **Root Cause**: Top-level unconditional imports crashed the entire service module if specific database or web search libraries were missing from the host Python environment.

### Issue C: Lack of Local Document Location Support
- **Symptom**: The agent relied exclusively on external cloud services (Google Drive + Pinecone VDB + PostgreSQL MDB).
- **Root Cause**: No built-in local file system retriever existed to search documents in a specific folder path (e.g. `./documents`).

---

## 2. Step-by-Step Technical Fixes Applied

### Step 1: Resilience & Safe Optional Imports
**Files Modified**: `agent_service.py`
- Wrapped external dependencies in `try-except ImportError` blocks to prevent top-level module crashes:
  ```python
  try:
      import psycopg2
  except ImportError:
      psycopg2 = None

  try:
      from pinecone import Pinecone
  except ImportError:
      Pinecone = None

  try:
      from langchain_openai import OpenAIEmbeddings, ChatOpenAI
  except ImportError:
      OpenAIEmbeddings = None
      ChatOpenAI = None

  try:
      from langchain_community.tools import DuckDuckGoSearchRun
      from langchain_core.messages import SystemMessage, HumanMessage
  except ImportError:
      DuckDuckGoSearchRun = None
      SystemMessage = None
      HumanMessage = None
  ```

### Step 2: Implementation of `LocalDirectoryRetriever`
**Files Modified**: `agent_service.py`
- Developed a local location document retriever class (`LocalDirectoryRetriever`) that scans, parses, chunks, and scores documents (`.md`, `.txt`, `.json`, `.csv`, `.py`, `.pdf`, `.docx`) directly in a target folder location (`DOCUMENTS_DIR` or custom path parameter).
- Implemented term matching, density scoring, snippet extraction, and relevance percentage calculations:
  ```python
  class LocalDirectoryRetriever:
      def search_location(self, query: str, location: Optional[str] = None, top_k: int = 5) -> Dict[str, Any]:
          target_dir = location if (location and os.path.exists(location)) else settings.documents_dir
          ...
          # Calculates relevance scores and extracts top matching snippets
  ```

### Step 3: Orchestrator Pipeline & Fail-Safe RAG Routing
**Files Modified**: `agent_service.py`
- Updated `AgentOrchestrator.process_query()` with a 3-tier fallback architecture:
  1. **Primary**: Vector DB search (Pinecone). If API key is missing or throws 401/connection error, catch exception and log warning.
  2. **Secondary**: Local Directory Location Search (`LocalDirectoryRetriever`). If vector DB returns 0 results or fails, query target folder.
  3. **Tertiary**: External Web Search (DuckDuckGo). Only activated if internal documents produce 0 matching chunks.
- Enhanced `QueryRequest` and `QueryResponse` models with `MatchDetail` (filename, file path, score, snippet):
  ```python
  class MatchDetail(BaseModel):
      file_name: str
      file_path: str
      score: float
      snippet: str
  ```
- Added a dedicated `/search` endpoint to query documents in a specific location directly.

### Step 4: System Configuration Updates
**Files Modified**: `config.py`, `.env`, `ingestion_service.py`
- Added `DOCUMENTS_DIR=./documents` field in `config.py` Settings class and `.env`.
- Added `list_local_files(directory_path)` helper in `ingestion_service.py` to support indexing local directories alongside Google Drive.

---

## 3. Validation & Test Verification

### Test Environment Setup
Created `./documents` folder with two test files:
1. `company_policy.md` (Remote Work Policy & Q3 Retention Metrics)
2. `q3_financial_report.txt` (Q3 Financial Summary & Revenue Details)

### Test Execution Commands & Results

#### Test Command:
```bash
.venv/bin/python -c "
from agent_service import get_orchestrator
orchestrator = get_orchestrator()

# Test 1: Query Net Revenue Retention in location
res1 = orchestrator.process_query('What is our Q3 Net Revenue Retention rate?', location='./documents')
print(res1)

# Test 2: Query Remote Work Policy in location
res2 = orchestrator.process_query('What is the policy for remote work?', location='./documents')
print(res2)
"
```

#### Verification Results:
- **Zero Crashes**: Pinecone 401 and module errors were cleanly handled without throwing unhandled HTTP 500 exceptions.
- **Match 1**: Found `company_policy.md` (Relevance: **82%**) and `q3_financial_report.txt` (Relevance: **57%**) for Q3 NRR query.
- **Match 2**: Found `company_policy.md` (Relevance: **57%**) for Remote Work Policy query.
- **Source Attribution**: Returned file names, relative paths, snippet text, and relevance scores.

---

## 4. File Modification Summary

| File Name | Change Summary |
| :--- | :--- |
| `config.py` | Added `documents_dir` setting (`DOCUMENTS_DIR`) |
| `.env` | Added `DOCUMENTS_DIR=./documents` configuration |
| `agent_service.py` | Added safe imports, `LocalDirectoryRetriever`, `MatchDetail`, `/search` endpoint, and fail-safe orchestrator routing |
| `ingestion_service.py` | Added `list_local_files()` for local file discovery |
| `./documents/*` | Added sample test documents (`company_policy.md`, `q3_financial_report.txt`) |

---
*Documentation generated for Enterprise Document Research Agent repository.*
