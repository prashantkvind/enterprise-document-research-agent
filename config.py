import os
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application Settings loaded from environment variables and .env file.
    """
    # OpenAI Settings
    openai_api_key: str = Field(default="", validation_alias="OPENAI_API_KEY")

    # Pinecone Vector DB Settings
    pinecone_api_key: str = Field(default="", validation_alias="PINECONE_API_KEY")
    pinecone_index_name: str = Field(default="era-index", validation_alias="PINECONE_INDEX_NAME")

    # PostgreSQL Metadata DB Settings
    postgres_host: str = Field(default="localhost", validation_alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, validation_alias="POSTGRES_PORT")
    postgres_db: str = Field(default="era_db", validation_alias="POSTGRES_DB")
    postgres_user: str = Field(default="postgres", validation_alias="POSTGRES_USER")
    postgres_password: str = Field(default="postgres", validation_alias="POSTGRES_PASSWORD")

    # Google Drive Settings
    gdrive_folder_id: str = Field(default="", validation_alias="GDRIVE_FOLDER_ID")
    gdrive_credentials_file: str = Field(default="credentials.json", validation_alias="GDRIVE_CREDENTIALS_FILE")
    gdrive_token_file: str = Field(default="token.json", validation_alias="GDRIVE_TOKEN_FILE")

    # Local Documents Directory Settings
    documents_dir: str = Field(default="./documents", validation_alias="DOCUMENTS_DIR")

    # Processing & Retrieval Settings
    chunk_size: int = Field(default=1000, validation_alias="CHUNK_SIZE")
    chunk_overlap: int = Field(default=200, validation_alias="CHUNK_OVERLAP")
    similarity_threshold: float = Field(default=0.75, validation_alias="SIMILARITY_THRESHOLD")

    # Demo & Fallback Settings
    demo_mode: bool = Field(default=True, validation_alias="DEMO_MODE")

    # Server API Settings
    port: int = Field(default=8000, validation_alias="PORT")
    host: str = Field(default="0.0.0.0", validation_alias="HOST")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def postgres_connection_string(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
