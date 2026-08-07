from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://finsight:change_me_locally@localhost:5433/finsight"

    anthropic_api_key: str = ""
    # Model routing per the design plan: Haiku for classification/simple lookups,
    # Sonnet for chat answer generation. Swap CHAT_MODEL to claude-opus-5 if answer
    # quality on multi-step questions matters more than the per-token cost.
    chat_model: str = "claude-sonnet-5"
    classify_model: str = "claude-haiku-4-5"

    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = 384

    inbox_dir: Path = Path("/inbox")

    # Retrieval depth for semantic questions.
    retrieval_top_k: int = 20


@lru_cache
def get_settings() -> Settings:
    return Settings()
