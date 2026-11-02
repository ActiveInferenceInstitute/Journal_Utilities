"""Settings management for JournalRAG."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "JournalRAG"
    version: str = "0.1.0"
    debug: bool = False

    # Cohere API
    # Optional (empty default) so importing this module never crashes without a
    # secret; consumers validate the value when they actually call the API.
    cohere_api_key: str = Field(default="", description="Cohere API key")
    cohere_model: str = Field(
        default="command-a-03-2025",
        description="Cohere model to use",
    )

    # SurrealDB
    surrealdb_url: str = Field(default="ws://localhost:8000/rpc", description="SurrealDB URL")
    surrealdb_namespace: str = Field(default="active_inference", description="SurrealDB namespace")
    surrealdb_database: str = Field(default="journal", description="SurrealDB database")
    surrealdb_username: str = Field(default="root", description="SurrealDB username")
    surrealdb_password: str = Field(default="", description="SurrealDB password")

    # Processing
    batch_size: int = Field(default=10, description="Batch size for processing transcripts")
    max_retries: int = Field(default=3, description="Maximum retries for API calls")


settings = Settings()
