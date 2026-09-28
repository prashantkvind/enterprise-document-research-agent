import io
import os
import uuid
import logging
from typing import List, Dict, Any

import psycopg2
from psycopg2.extras import execute_values
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from pinecone import Pinecone, ServerlessSpec

from config import settings

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Google Drive API Scopes
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


def get_gdrive_service():
    """
    Authenticate and return Google Drive API service using OAuth 2.0 flow.
    Handles token creation, refreshing, and persistence.
    """
    creds = None
    token_path = settings.gdrive_token_file
    credentials_path = settings.gdrive_credentials_file

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("Refreshing expired Google Drive OAuth token...")
            creds.refresh(Request())
        else:
            if not os.path.exists(credentials_path):
                raise FileNotFoundError(
                    f"Google credentials file '{credentials_path}' not found. "
                    "Please obtain credentials.json from Google Cloud Console."
                )
            logger.info("Initiating Google Drive OAuth 2.0 authorization flow...")
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(token_path, "w") as token:
            token.write(creds.to_json())

    return build("drive", "v3", credentials=creds)


def list_files_in_folder(service, folder_id: str) -> List[Dict[str, Any]]:
    """
    List all accessible files within the specified Google Drive folder.
    """
    query = f"'{folder_id}' in parents and trashed = false"
    results = service.files().list(
        q=query,
        fields="nextPageToken, files(id, name, mimeType)"
    ).execute()
    files = results.get("files", [])
    logger.info(f"Retrieved {len(files)} files from Google Drive Folder ID: {folder_id}")
    return files


def list_local_files(directory_path: str) -> List[Dict[str, Any]]:
    """
    List files in specified local directory location for ingestion.
    """
    files = []
    if not os.path.exists(directory_path):
        logger.warning(f"Local directory path '{directory_path}' does not exist.")
        return files

    for root, _, filenames in os.walk(directory_path):
        for name in filenames:
            full_path = os.path.join(root, name)
            files.append({
                "id": f"local_{abs(hash(full_path))}",
                "name": name,
                "path": full_path,
                "mimeType": "text/plain"
            })
    logger.info(f"Retrieved {len(files)} local files from: {directory_path}")
    return files



def download_file_content(service, file_id: str, mime_type: str) -> str:
    """
    Download or export file content from Google Drive as plain text.
    """
    try:
        if mime_type.startswith("application/vnd.google-apps."):
            # Google Docs / Sheets / Slides - export as text
            request = service.files().export_media(fileId=file_id, mimeType="text/plain")
        else:
            request = service.files().get_media(fileId=file_id)

        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()

        fh.seek(0)
        content = fh.read().decode("utf-8", errors="ignore")
        return content
    except Exception as e:
        logger.error(f"Failed to download/extract file {file_id} ({mime_type}): {e}")
        return ""


def get_db_connection():
    """
    Establish connection to PostgreSQL metadata database.
    """
    return psycopg2.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        dbname=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password
    )


def initialize_pinecone():
    """
    Initialize Pinecone client and ensure target vector index exists.
    """
    pc = Pinecone(api_key=settings.pinecone_api_key)
    index_name = settings.pinecone_index_name

    existing_indexes = [index_info["name"] for index_info in pc.list_indexes()]
    if index_name not in existing_indexes:
        logger.info(f"Creating Pinecone Index '{index_name}'...")
        pc.create_index(
            name=index_name,
            dimension=1536,  # text-embedding-ada-002 dimension
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1")
        )

    return pc.Index(index_name)


def run_ingestion():
    """
    Main ingestion execution workflow:
    1. Fetch files from Google Drive
    2. Split documents into chunks using RecursiveCharacterTextSplitter
    3. Generate text embeddings using OpenAI text-embedding-ada-002
    4. Upsert vectors to Pinecone VDB
    5. Save metadata and chunk mappings in PostgreSQL MDB
    """
    logger.info("Starting Enterprise Document Ingestion Service...")

    if not settings.gdrive_folder_id:
        raise ValueError("GDRIVE_FOLDER_ID environment variable is not configured.")

    drive_service = get_gdrive_service()
    files = list_files_in_folder(drive_service, settings.gdrive_folder_id)

    if not files:
        logger.warning("No files found in specified Google Drive folder.")
        return

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap
    )

    embeddings = OpenAIEmbeddings(
        model="text-embedding-ada-002",
        openai_api_key=settings.openai_api_key
    )

    pinecone_index = initialize_pinecone()
    db_conn = get_db_connection()
    db_cursor = db_conn.cursor()

    total_chunks_processed = 0

    for file in files:
        file_id = file["id"]
        file_name = file["name"]
        mime_type = file.get("mimeType", "unknown")

        logger.info(f"Processing document: '{file_name}' (ID: {file_id})")
        content = download_file_content(drive_service, file_id, mime_type)

        if not content.strip():
            logger.warning(f"Skipping empty or non-extractable file: '{file_name}'")
            continue

        # Record document metadata in PostgreSQL
        db_cursor.execute(
            """
            INSERT INTO documents (file_id, file_name, mime_type)
            VALUES (%s, %s, %s)
            ON CONFLICT (file_id) DO UPDATE 
            SET file_name = EXCLUDED.file_name, mime_type = EXCLUDED.mime_type;
            """,
            (file_id, file_name, mime_type)
        )
        db_conn.commit()

        # Split document into chunks
        chunks = text_splitter.split_text(content)
        logger.info(f"Document '{file_name}' split into {len(chunks)} chunks.")

        if not chunks:
            continue

        # Generate embeddings
        chunk_embeddings = embeddings.embed_documents(chunks)

        pinecone_vectors = []
        pg_chunk_records = []

        for idx, (chunk_text, embedding) in enumerate(zip(chunks, chunk_embeddings)):
            vector_id = f"vec_{file_id}_{idx}_{uuid.uuid4().hex[:8]}"
            chunk_id = f"chunk_{file_id}_{idx}"

            # Prepare Pinecone vector object
            pinecone_vectors.append({
                "id": vector_id,
                "values": embedding,
                "metadata": {
                    "file_id": file_id,
                    "file_name": file_name,
                    "chunk_id": chunk_id,
                    "chunk_index": idx
                }
            })

            # Prepare PostgreSQL metadata chunk record
            pg_chunk_records.append((
                chunk_id,
                vector_id,
                file_id,
                idx,
                chunk_text
            ))

        # Upsert vectors into Pinecone
        pinecone_index.upsert(vectors=pinecone_vectors)

        # Record chunk metadata and vector mapping in PostgreSQL
        execute_values(
            db_cursor,
            """
            INSERT INTO document_chunks (chunk_id, vector_id, file_id, chunk_index, chunk_text)
            VALUES %s
            ON CONFLICT (chunk_id) DO UPDATE 
            SET vector_id = EXCLUDED.vector_id, chunk_text = EXCLUDED.chunk_text;
            """,
            pg_chunk_records
        )
        db_conn.commit()

        total_chunks_processed += len(chunks)
        logger.info(f"Successfully indexed document '{file_name}' ({len(chunks)} chunks).")

    db_cursor.close()
    db_conn.close()

    logger.info(f"Ingestion complete. Total documents: {len(files)}, Total chunks indexed: {total_chunks_processed}.")


if __name__ == "__main__":
    run_ingestion()
