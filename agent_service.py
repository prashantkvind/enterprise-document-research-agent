import logging
from typing import List, Dict, Any, Optional

import psycopg2
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field
from pinecone import Pinecone

from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_community.tools import DuckDuckGoSearchRun
from langchain_core.messages import SystemMessage, HumanMessage

from config import settings

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# FastAPI Application
app = FastAPI(
    title="Enterprise Document Research Agent (ERA)",
    description="Intelligent RAG agent with primary document retrieval and web search fallback.",
    version="1.0.0"
)


# Pydantic Models for Request and Response
class QueryRequest(BaseModel):
    query: str = Field(..., description="User question or research query", example="What is our Q3 revenue retention rate?")


class QueryResponse(BaseModel):
    answer: str = Field(..., description="Synthesized answer to the user query")
    source_type: str = Field(..., description="Source type used: 'Internal Documents' or 'External Search'")
    sources: List[str] = Field(..., description="List of document names or search sources used for citation")


# Helper Service Classes
class RAGRetriever:
    """
    Handles Vector DB (Pinecone) k-NN similarity search and Metadata DB (PostgreSQL) citation retrieval.
    """
    def __init__(self):
        self.pc = Pinecone(api_key=settings.pinecone_api_key)
        self.index = self.pc.Index(settings.pinecone_index_name)
        self.embeddings = OpenAIEmbeddings(
            model="text-embedding-ada-002",
            openai_api_key=settings.openai_api_key
        )

    def search_chunks(self, query: str, top_k: int = 5) -> Dict[str, Any]:
        """
        Embed query, execute Pinecone k-NN search, and filter results by SIMILARITY_THRESHOLD.
        """
        logger.info(f"Executing Pinecone vector search for query: '{query}'")
        query_vector = self.embeddings.embed_query(query)

        search_response = self.index.query(
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

    def _get_metadata_for_vectors(self, vector_ids: List[str]) -> Dict[str, Any]:
        """
        Fetch chunk text and document title metadata from PostgreSQL database for citation mapping.
        """
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


class AgentOrchestrator:
    """
    Orchestrates Primary Search (RAG), Failure Detection ([CONTEXT_INSUFFICIENT]), Fallback Search, and Final Synthesis.
    """
    def __init__(self):
        self.retriever = RAGRetriever()
        self.llm = ChatOpenAI(
            model="gpt-4-turbo",
            temperature=0.0,
            openai_api_key=settings.openai_api_key
        )
        self.ddg_search = DuckDuckGoSearchRun()

    def process_query(self, query: str) -> QueryResponse:
        logger.info(f"Processing query: '{query}'")

        # Step 1: Primary Search (RAG against Pinecone & PostgreSQL)
        rag_data = self.retriever.search_chunks(query)
        chunks = rag_data["chunks"]
        internal_sources = rag_data["sources"]

        if chunks:
            # Step 2: Attempt answer generation using internal document context
            context_block = "\n\n---\n\n".join(chunks)
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

            llm_response = self.llm.invoke(messages)
            llm_text = llm_response.content.strip()

            # Step 3: Check for failure signal
            if "[CONTEXT_INSUFFICIENT]" not in llm_text and llm_text != "":
                logger.info("RAG context was sufficient. Returning internal document answer.")
                return QueryResponse(
                    answer=llm_text,
                    source_type="Internal Documents",
                    sources=internal_sources
                )
            else:
                logger.info("LLM reported [CONTEXT_INSUFFICIENT]. Triggering external fallback path.")
        else:
            logger.info("No internal chunks met the SIMILARITY_THRESHOLD. Triggering external fallback path.")

        # Step 4: Fallback Mechanism (DuckDuckGo Search)
        return self._execute_fallback(query)

    def _execute_fallback(self, query: str) -> QueryResponse:
        """
        Execute DuckDuckGo search fallback when RAG context is missing or insufficient.
        """
        logger.info(f"Executing DuckDuckGo web search fallback for query: '{query}'")
        try:
            search_results = self.ddg_search.run(query)
        except Exception as e:
            logger.error(f"DuckDuckGo search execution failed: {e}")
            search_results = "No external search results could be retrieved at this time."

        fallback_system_prompt = (
            "You are the Enterprise Document Research Agent (ERA).\n"
            "Internal company documents did not contain sufficient context to answer the user's question.\n"
            "Synthesize a clear, helpful, and accurate response using the provided web search results."
        )

        messages = [
            SystemMessage(content=fallback_system_prompt),
            HumanMessage(content=f"External Web Search Results:\n{search_results}\n\nUser Question: {query}")
        ]

        synthesized_response = self.llm.invoke(messages)

        return QueryResponse(
            answer=synthesized_response.content.strip(),
            source_type="External Search",
            sources=["External Web Search (DuckDuckGo)"]
        )


# Instantiate Agent Orchestrator
orchestrator = AgentOrchestrator()


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
        response = orchestrator.process_query(request.query)
        return response
    except Exception as e:
        logger.exception("An error occurred while processing the agent query.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred in agent orchestration: {str(e)}"
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "agent_service:app",
        host=settings.host,
        port=settings.port,
        reload=False
    )
