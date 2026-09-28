-- ==============================================================================
-- Enterprise Document Research Agent (ERA) - Metadata Database Setup
-- ==============================================================================

-- Table for storing ingested document level metadata
CREATE TABLE IF NOT EXISTS documents (
    file_id VARCHAR(255) PRIMARY KEY,
    file_name VARCHAR(512) NOT NULL,
    mime_type VARCHAR(255),
    ingested_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Table for storing chunk level metadata and vector ID mapping
CREATE TABLE IF NOT EXISTS document_chunks (
    chunk_id VARCHAR(255) PRIMARY KEY,
    vector_id VARCHAR(255) NOT NULL UNIQUE,
    file_id VARCHAR(255) NOT NULL REFERENCES documents(file_id) ON DELETE CASCADE,
    chunk_index INT NOT NULL,
    chunk_text TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Indexes to ensure high-performance citation lookups during agent retrieval
CREATE INDEX IF NOT EXISTS idx_document_chunks_vector_id ON document_chunks(vector_id);
CREATE INDEX IF NOT EXISTS idx_document_chunks_file_id ON document_chunks(file_id);
