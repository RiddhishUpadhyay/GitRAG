import os

# Clear any invalid global Hugging Face tokens to force anonymous access for public models
os.environ.pop("HF_TOKEN", None)
os.environ.pop("HF_API_KEY", None)

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# Base directory of the project
BASE_DIR = Path(__file__).resolve().parent.parent

class Settings(BaseSettings):
    GROQ_API_KEY: str = "dummy_groq_key"
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: str | None = None
    REDIS_URL: str = "redis://localhost:6379"
    MAX_REPO_SIZE_MB: int = 50
    ENV: str = "development"
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "gitrag2026"
    
    # Store temporary git checkouts inside the workspace
    TEMP_DIR: str = str(BASE_DIR / "temp")

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()

# Ensure temp directory exists
os.makedirs(settings.TEMP_DIR, exist_ok=True)
