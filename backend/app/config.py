from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://pricebot:pricebot@postgres:5432/pricebot"
    minio_endpoint: str = "http://host.docker.internal:9020"
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_bucket: str = "supermarket-lakehouse"
    minio_prefix: str = "gold"
    ollama_base_url: str = "http://host.docker.internal:11434"
    ollama_model: str = "qwen2.5:3b"
    ollama_answer_generation: bool = True
    ollama_answer_timeout_seconds: int = 15
    ollama_answer_evaluation: bool = True
    ollama_eval_timeout_seconds: int = 10
    ollama_eval_pass_score: float = 3.5
    ollama_max_refine_attempts: int = 1
    embedding_model: str = "bge-m3:latest"
    embedding_batch_size: int = 24
    embedding_timeout_seconds: int = 60
    embedding_sync_limit: int = 120
    cors_origins: str = "http://localhost:3000"
    hudi_packages: str = "org.apache.hudi:hudi-spark3.5-bundle_2.12:1.2.0,org.apache.hadoop:hadoop-aws:3.3.4"

    @property
    def origins(self) -> list[str]:
        return [value.strip() for value in self.cors_origins.split(",") if value.strip()]

@lru_cache
def get_settings() -> Settings:
    return Settings()
