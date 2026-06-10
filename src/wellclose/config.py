"""Settings (Brief §11/§16.5). All values overridable via env / .env; prefix WC_."""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WC_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://wellclose:wellclose@localhost:5432/wellclose"
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "wellclose"
    minio_secret_key: str = "wellclose-secret"
    minio_secure: bool = False
    bucket_raw: str = "wc-raw"
    bucket_derived: str = "wc-derived"

    llm_base_url: str = "http://localhost:4000/v1"   # LiteLLM gateway
    llm_api_key: str = "wellclose-local"
    model_vision: str = "qwen-vl"
    model_text: str = "qwen-text"
    model_small: str = "qwen-small"
    escalation_tier: str = "none"                     # §16.4: none | api
    escalation_model: str = ""

    temporal_target: str = "localhost:7233"           # ADR-001
    temporal_namespace: str = "default"
    task_queue: str = "wellclose-mvp"

    ocr_engine: str = "tesseract"                     # ADR-003: tesseract | doctr
    t_auto: float = 0.95                              # §9.4 batch-approve threshold
    review_oidc_issuer: str = ""                      # §12 Keycloak; blank disables auth (dev only)

    render_dpi: int = 300                             # §7 Stage B
    rate_limit_rps: float = 1.0                       # §4.5 politeness
    user_agent: str = "WellCloseBot/0.1 (+contact: ops@wellclose.local; purpose: public well records research)"


@lru_cache
def settings() -> Settings:
    return Settings()
