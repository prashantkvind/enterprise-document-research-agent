import os
import re
import glob
import logging
from typing import List, Dict, Any, Optional

try:
    import psycopg2
except ImportError:
    psycopg2 = None
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
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

from config import settings

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# FastAPI Application
app = FastAPI(
    title="Enterprise Document Research Agent (ERA)",
    description="Intelligent RAG agent with primary document retrieval, local location search, and web search fallback.",
    version="1.1.0"
)


# Pydantic Models for Request and Response
class QueryRequest(BaseModel):
    query: str = Field(..., description="User question or research query", example="What is our Q3 revenue retention rate?")
    location: Optional[str] = Field(None, description="Optional directory location to search documents in", example="./documents")


class MatchDetail(BaseModel):
    file_name: str = Field(..., description="Name of matching document file")
    file_path: str = Field(..., description="Full path or relative location of document file")
    score: float = Field(..., description="Relevance or similarity score")
    snippet: str = Field(..., description="Excerpt or snippet from matching document chunk")


class QueryResponse(BaseModel):
    answer: str = Field(..., description="Synthesized answer to the user query")
    source_type: str = Field(..., description="Source type used: 'Internal Documents' or 'External Search'")
    sources: List[str] = Field(..., description="List of document names or search sources used for citation")
    matches: Optional[List[MatchDetail]] = Field(default=[], description="Detailed document match snippets and scores")



# Helper Service Classes
class RAGRetriever:
    """
    Handles Vector DB (Pinecone) k-NN similarity search and Metadata DB (PostgreSQL) citation retrieval.
    Includes graceful exception handling when keys/DB are unconfigured or unavailable.
    """
    def __init__(self):
        self.pc_key = settings.pinecone_api_key
        self.openai_key = settings.openai_api_key

    def search_chunks(self, query: str, top_k: int = 5) -> Dict[str, Any]:
        """
        Embed query, execute Pinecone k-NN search, and filter results by SIMILARITY_THRESHOLD.
        Returns empty chunks list on missing/invalid keys to trigger seamless web fallback.
        """
        if not Pinecone or not OpenAIEmbeddings or not self.pc_key or "your_" in self.pc_key.lower():
            logger.warning("Pinecone/OpenAI packages or API key unconfigured. Routing to Local Directory Searcher.")
            return {"chunks": [], "sources": []}

        try:
            pc = Pinecone(api_key=self.pc_key)
            index = pc.Index(settings.pinecone_index_name)
            embeddings = OpenAIEmbeddings(
                model="text-embedding-ada-002",
                openai_api_key=self.openai_key if (self.openai_key and "your_" not in self.openai_key.lower()) else None
            )

            logger.info(f"Executing Pinecone vector search for query: '{query}'")
            query_vector = embeddings.embed_query(query)

            search_response = index.query(
                vector=query_vector,
                top_k=top_k,
                include_metadata=True
            )

            matches = search_response.get("matches", [])
            logger.info(f"Retrieved {len(matches)} raw vector matches from Pinecone.")

            # Filter by threshold (0.75)
            filtered_matches = [
                m for m in matches if m.get("score", 0.0) >= settings.similarity_threshold
            ]
            logger.info(f"{len(filtered_matches)} matches passed SIMILARITY_THRESHOLD ({settings.similarity_threshold}).")

            if not filtered_matches:
                return {"chunks": [], "sources": []}

            # Retrieve detailed text and document metadata from PostgreSQL
            vector_ids = [m["id"] for m in filtered_matches]
            return self._get_metadata_for_vectors(vector_ids)
        except Exception as e:
            logger.warning(f"Vector retrieval unavailable or unconfigured ({e}). Falling back to external search.")
            return {"chunks": [], "sources": []}

    def _get_metadata_for_vectors(self, vector_ids: List[str]) -> Dict[str, Any]:
        """
        Fetch chunk text and document title metadata from PostgreSQL database for citation mapping.
        """
        if not psycopg2:
            logger.warning("psycopg2 module not installed; skipping PostgreSQL metadata lookup.")
            return {"chunks": [], "sources": []}
        try:
            conn = psycopg2.connect(
                host=settings.postgres_host,
                port=settings.postgres_port,
                dbname=settings.postgres_db,
                user=settings.postgres_user,
                password=settings.postgres_password
            )
            cursor = conn.cursor()

            query = """
                SELECT dc.vector_id, dc.chunk_text, d.file_name, d.file_id 
                FROM document_chunks dc
                JOIN documents d ON dc.file_id = d.file_id
                WHERE dc.vector_id IN %s;
            """
            cursor.execute(query, (tuple(vector_ids),))
            rows = cursor.fetchall()

            chunks = []
            source_files = set()

            for row in rows:
                vector_id, chunk_text, file_name, file_id = row
                chunks.append(f"[Source: {file_name}]\n{chunk_text}")
                source_files.add(file_name)

            cursor.close()
            conn.close()

            return {
                "chunks": chunks,
                "sources": list(source_files)
            }
        except Exception as e:
            logger.error(f"Error querying PostgreSQL metadata database: {e}")
            return {"chunks": [], "sources": []}


class LocalDirectoryRetriever:
    """
    Scans and searches documents in a specified local directory location (e.g. ./documents or custom path).
    Provides hybrid keyword matching and text scoring across local files (.txt, .md, .csv, .json, .py, etc.).
    """
    def search_location(self, query: str, location: Optional[str] = None, top_k: int = 5) -> Dict[str, Any]:
        target_dir = location if (location and os.path.exists(location)) else settings.documents_dir
        if not target_dir or not os.path.exists(target_dir):
            logger.warning(f"Target document location '{target_dir}' does not exist.")
            return {"chunks": [], "sources": [], "matches": []}

        query_terms = [t.lower() for t in re.findall(r'\w+', query) if len(t) > 2]
        if not query_terms:
            query_terms = [query.lower()]

        supported_extensions = ['.txt', '.md', '.markdown', '.json', '.csv', '.py', '.html', '.rst', '.log', '.doc', '.pdf']
        file_paths = []
        for root, _, files in os.walk(target_dir):
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in supported_extensions or not ext:
                    file_paths.append(os.path.join(root, file))

        scored_chunks = []
        for file_path in file_paths:
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()

                if not content.strip():
                    continue

                rel_path = os.path.relpath(file_path, target_dir)
                file_name = os.path.basename(file_path)

                paragraphs = [p.strip() for p in re.split(r'\n\s*\n', content) if p.strip()]
                for idx, para in enumerate(paragraphs):
                    para_lower = para.lower()
                    matches_count = sum(1 for term in query_terms if term in para_lower)

                    if matches_count > 0:
                        score = min(0.99, (matches_count / len(query_terms)) * 0.75 + 0.20)
                        scored_chunks.append({
                            "chunk_text": f"[Source: {file_name} ({rel_path})]\n{para}",
                            "file_name": file_name,
                            "file_path": file_path,
                            "snippet": para[:300] + ("..." if len(para) > 300 else ""),
                            "score": round(score, 3)
                        })
            except Exception as e:
                logger.error(f"Error reading file {file_path}: {e}")

        scored_chunks.sort(key=lambda x: x["score"], reverse=True)
        top_matches = scored_chunks[:top_k]

        chunks = [m["chunk_text"] for m in top_matches]
        sources = list(set([m["file_name"] for m in top_matches]))
        match_details = [
            MatchDetail(
                file_name=m["file_name"],
                file_path=m["file_path"],
                score=m["score"],
                snippet=m["snippet"]
            )
            for m in top_matches
        ]

        logger.info(f"LocalDirectoryRetriever found {len(top_matches)} relevant matches in location '{target_dir}'.")
        return {
            "chunks": chunks,
            "sources": sources,
            "matches": match_details
        }


class AgentOrchestrator:
    """
    Orchestrates Vector Search (Pinecone/PG), Local Directory Search, Fallback Search, and Final Synthesis.
    """
    def __init__(self):
        self.retriever = RAGRetriever()
        self.local_retriever = LocalDirectoryRetriever()
        openai_key = settings.openai_api_key if (settings.openai_api_key and "your_" not in settings.openai_api_key.lower()) else None
        self.llm = ChatOpenAI(
            model="gpt-4-turbo",
            temperature=0.0,
            openai_api_key=openai_key
        ) if (ChatOpenAI and openai_key) else None
        try:
            self.ddg_search = DuckDuckGoSearchRun() if DuckDuckGoSearchRun else None
        except Exception as e:
            logger.warning(f"DuckDuckGo search tool initialization skipped: {e}")
            self.ddg_search = None

    def process_query(self, query: str, location: Optional[str] = None) -> QueryResponse:
        logger.info(f"Processing query: '{query}' (Target Location: '{location or settings.documents_dir}')")

        # Step 1: Primary Search (RAG against Pinecone & PostgreSQL)
        rag_data = self.retriever.search_chunks(query)
        chunks = rag_data.get("chunks", [])
        internal_sources = rag_data.get("sources", [])
        matches = rag_data.get("matches", [])

        # Step 2: Fallback to Local Directory Search if Pinecone returned 0 results or failed
        if not chunks:
            logger.info("Pinecone/Vector DB returned 0 chunks or is unconfigured. Querying Local Directory Retriever.")
            local_data = self.local_retriever.search_location(query, location=location)
            chunks = local_data.get("chunks", [])
            internal_sources = local_data.get("sources", [])
            matches = local_data.get("matches", [])

        if chunks:
            context_block = "\n\n---\n\n".join(chunks)
            if self.llm:
                system_prompt = (
                    "You are the Enterprise Document Research Agent (ERA).\n"
                    "Your job is to answer the user's query using ONLY the provided internal document context.\n\n"
                    "STRICT INSTRUCTIONS:\n"
                    "1. If the answer CANNOT be fully and accurately generated using ONLY the provided context, "
                    "you MUST respond with the exact string: [CONTEXT_INSUFFICIENT]\n"
                    "2. Do NOT use outside knowledge or assumptions if the context is missing key details.\n"
                    "3. If sufficient, provide a concise, factual, and complete answer with source citations."
                )

                messages = [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=f"Context:\n{context_block}\n\nUser Question: {query}")
                ]

                try:
                    llm_response = self.llm.invoke(messages)
                    llm_text = llm_response.content.strip()

                    if "[CONTEXT_INSUFFICIENT]" not in llm_text and llm_text != "":
                        logger.info("Document context was sufficient. Returning internal document answer.")
                        return QueryResponse(
                            answer=llm_text,
                            source_type="Internal Documents",
                            sources=internal_sources,
                            matches=matches
                        )
                    else:
                        logger.info("LLM reported [CONTEXT_INSUFFICIENT]. Triggering external fallback path.")
                except Exception as e:
                    logger.warning(f"LLM invocation failed ({e}). Returning extracted document snippets.")

            # Fallback if LLM key is absent: return structured document search matches
            formatted_answer = f"Found {len(chunks)} relevant document matches in specified location:\n\n" + "\n\n".join([f"📄 **{m.file_name}** (Relevance: {int(m.score*100)}%):\n\"{m.snippet}\"" for m in matches])
            return QueryResponse(
                answer=formatted_answer,
                source_type="Internal Documents",
                sources=internal_sources,
                matches=matches
            )

        # Step 3: Fallback Mechanism (DuckDuckGo Search)
        return self._execute_fallback(query)


    def _execute_fallback(self, query: str) -> QueryResponse:
        """
        Execute DuckDuckGo search fallback when RAG context is missing or insufficient.
        """
        if self.ddg_search:
            try:
                search_results = self.ddg_search.run(query)
            except Exception as e:
                logger.error(f"DuckDuckGo search execution failed: {e}")
                search_results = "No external search results could be retrieved at this time."
        else:
            search_results = "External web search tool is unconfigured or not installed."

        if self.llm:
            fallback_system_prompt = (
                "You are the Enterprise Document Research Agent (ERA).\n"
                "Internal company documents did not contain sufficient context to answer the user's question.\n"
                "Synthesize a clear, helpful, and accurate response using the provided web search results."
            )

            messages = [
                SystemMessage(content=fallback_system_prompt),
                HumanMessage(content=f"External Web Search Results:\n{search_results}\n\nUser Question: {query}")
            ]

            try:
                synthesized_response = self.llm.invoke(messages)
                answer_text = synthesized_response.content.strip()
            except Exception as e:
                logger.warning(f"LLM synthesis failed during fallback ({e}). Returning raw search summary.")
                answer_text = f"External search results summary:\n{search_results}"
        else:
            answer_text = f"External search results summary:\n{search_results}"

        return QueryResponse(
            answer=answer_text,
            source_type="External Search",
            sources=["External Web Search (DuckDuckGo)"]
        )


# Instantiate Agent Orchestrator lazily when needed
_orchestrator: Optional[AgentOrchestrator] = None

def get_orchestrator() -> AgentOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = AgentOrchestrator()
    return _orchestrator


@app.get("/health", status_code=status.HTTP_200_OK)
def health_check():
    """
    Health check endpoint for container readiness and liveness probes.
    """
    return {"status": "healthy", "service": "Enterprise Document Research Agent"}


@app.post("/query", response_model=QueryResponse, status_code=status.HTTP_200_OK)
def query_agent(request: QueryRequest):
    """
    Primary endpoint to query the Enterprise Document Research Agent.
    """
    if not request.query.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Query string cannot be empty."
        )

    try:
        response = get_orchestrator().process_query(request.query, location=request.location)
        return response
    except Exception as e:
        logger.exception("An error occurred while processing the agent query.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred in agent orchestration: {str(e)}"
        )


@app.get("/search", response_model=QueryResponse, status_code=status.HTTP_200_OK)
def search_documents(query: str, location: Optional[str] = None):
    """
    Direct endpoint to search documents in a specified location directory.
    """
    if not query.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Query string cannot be empty.")
    try:
        return get_orchestrator().process_query(query, location=location)
    except Exception as e:
        logger.exception("An error occurred during document search.")
@app.get("/.well-known/agent-card.json")
@app.get("/a2a/app/.well-known/agent-card.json")
def get_agent_card():
    """
    Returns A2A Agent Card metadata for agent discovery and registry.
    """
    return {
        "name": "Enterprise Document Research Agent (ERA)",
        "description": "Intelligent RAG agent with primary document retrieval and web search fallback.",
        "version": "1.0.0",
        "protocol_version": "0.3.0",
        "capabilities": {
            "search": True,
            "document_retrieval": True,
            "web_fallback": True
        },
        "endpoints": {
            "query": "/query",
            "search": "/search",
            "health": "/health"
        }
    }


@app.get("/", response_class=HTMLResponse)
@app.get("/playground", response_class=HTMLResponse)
def serve_playground():
    """
    Serves a modern, interactive web playground for chatting with the agent.
    """
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Enterprise Document Research Agent (ERA) Playground</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
        <style>
            * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Inter', sans-serif; }
            body { background: #0f172a; color: #f8fafc; display: flex; flex-direction: column; height: 100vh; overflow: hidden; }
            header { background: #1e293b; padding: 1.2rem 2rem; border-bottom: 1px solid #334155; display: flex; align-items: center; justify-content: space-between; }
            header h1 { font-size: 1.25rem; font-weight: 600; color: #38bdf8; display: flex; align-items: center; gap: 0.5rem; }
            header .status-badge { font-size: 0.8rem; padding: 0.25rem 0.75rem; background: #064e3b; color: #34d399; border-radius: 9999px; border: 1px solid #059669; }
            main { flex: 1; overflow-y: auto; padding: 2rem; display: flex; flex-direction: column; gap: 1.5rem; max-width: 900px; width: 100%; margin: 0 auto; }
            .chat-bubble { display: flex; flex-direction: column; gap: 0.5rem; max-width: 80%; }
            .chat-bubble.user { align-self: flex-end; }
            .chat-bubble.agent { align-self: flex-start; }
            .message { padding: 1rem 1.25rem; border-radius: 12px; font-size: 0.95rem; line-height: 1.5; white-space: pre-wrap; }
            .user .message { background: #0284c7; color: #ffffff; border-bottom-right-radius: 2px; }
            .agent .message { background: #1e293b; color: #e2e8f0; border: 1px solid #334155; border-bottom-left-radius: 2px; }
            .meta-card { margin-top: 0.5rem; padding: 0.75rem 1rem; background: #0f172a; border-radius: 8px; border: 1px solid #334155; font-size: 0.85rem; }
            .source-tag { display: inline-block; padding: 0.2rem 0.6rem; border-radius: 4px; font-size: 0.75rem; font-weight: 600; margin-bottom: 0.4rem; }
            .tag-internal { background: #1e1b4b; color: #a5b4fc; border: 1px solid #4338ca; }
            .tag-external { background: #451a03; color: #fde047; border: 1px solid #b45309; }
            .sources-list { color: #94a3b8; font-size: 0.8rem; }
            .sources-list li { margin-left: 1.2rem; }
            footer { padding: 1.2rem 2rem; background: #1e293b; border-top: 1px solid #334155; }
            .input-box { max-width: 900px; margin: 0 auto; display: flex; gap: 0.75rem; }
            input[type="text"] { flex: 1; background: #0f172a; border: 1px solid #334155; border-radius: 8px; padding: 0.85rem 1.2rem; color: #f8fafc; font-size: 0.95rem; outline: none; }
            input[type="text"]:focus { border-color: #38bdf8; }
            button { background: #0284c7; color: white; border: none; border-radius: 8px; padding: 0.85rem 1.5rem; font-size: 0.95rem; font-weight: 500; cursor: pointer; transition: background 0.2s; }
            button:hover { background: #0369a1; }
            button:disabled { background: #334155; cursor: not-allowed; }
            .loading { font-style: italic; color: #94a3b8; }
        </style>
    </head>
    <body>
        <header>
            <h1>🔍 Enterprise Document Research Agent (ERA)</h1>
            <span class="status-badge">● API Online</span>
        </header>
        <main id="chat-window">
            <div class="chat-bubble agent">
                <div class="message">
                    👋 Hello! I am the <b>Enterprise Document Research Agent</b>.<br><br>
                    Ask me any question. I will search internal company documents first (RAG), and seamlessly fall back to web search if needed.
                </div>
            </div>
        </main>
        <footer>
            <div class="input-box">
                <input type="text" id="query-input" placeholder="Type your research question..." onkeydown="if(event.key==='Enter') sendQuery()">
                <button id="send-btn" onclick="sendQuery()">Send Query</button>
            </div>
        </footer>

        <script>
            async function sendQuery() {
                const input = document.getElementById('query-input');
                const btn = document.getElementById('send-btn');
                const chatWindow = document.getElementById('chat-window');
                const query = input.value.trim();

                if (!query) return;

                // Add User Message
                const userBubble = document.createElement('div');
                userBubble.className = 'chat-bubble user';
                userBubble.innerHTML = `<div class="message">${escapeHtml(query)}</div>`;
                chatWindow.appendChild(userBubble);

                input.value = '';
                input.disabled = true;
                btn.disabled = true;

                // Add Loading Agent Message
                const agentBubble = document.createElement('div');
                agentBubble.className = 'chat-bubble agent';
                agentBubble.innerHTML = `<div class="message loading">Searching internal documents & synthesizing response...</div>`;
                chatWindow.appendChild(agentBubble);
                chatWindow.scrollTop = chatWindow.scrollHeight;

                try {
                    const response = await fetch('/query', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ query: query })
                    });

                    const data = await response.json();

                    if (response.ok) {
                        const isInternal = data.source_type === "Internal Documents";
                        const tagClass = isInternal ? "tag-internal" : "tag-external";
                        const sourcesList = data.sources.map(s => `<li>${escapeHtml(s)}</li>`).join('');

                        agentBubble.innerHTML = `
                            <div class="message">${escapeHtml(data.answer)}</div>
                            <div class="meta-card">
                                <span class="source-tag ${tagClass}">${escapeHtml(data.source_type)}</span>
                                <div class="sources-list">
                                    <b>Sources Used:</b>
                                    <ul>${sourcesList}</ul>
                                </div>
                            </div>
                        `;
                    } else {
                        agentBubble.innerHTML = `<div class="message" style="color:#f87171;">Error: ${escapeHtml(data.detail || 'Failed to get response.')}</div>`;
                    }
                } catch (err) {
                    agentBubble.innerHTML = `<div class="message" style="color:#f87171;">Network Error: ${escapeHtml(err.message)}</div>`;
                } finally {
                    input.disabled = false;
                    btn.disabled = false;
                    input.focus();
                    chatWindow.scrollTop = chatWindow.scrollHeight;
                }
            }

            function escapeHtml(text) {
                return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
            }
        </script>
    </body>
    </html>
    """


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "agent_service:app",
        host=settings.host,
        port=settings.port,
        reload=False
    )
