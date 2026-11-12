from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = Path(__file__).resolve().parent.parent

ENV_FILES = [
    str(ROOT_DIR / ".env"),
    str(BACKEND_DIR / ".env"),
]


class Settings(BaseSettings):
    APP_NAME: str = "IntentLock"
    ENVIRONMENT: str = "development"
    DATABASE_URL: str = "sqlite:///./intentlock.db"
    INTENTLOCK_SIGNING_SECRET: str = "intentlock-dev-hmac-secret-key-2026-change-in-prod-99a8b7c6"
    JWT_ALGORITHM: str = "HS256"
    DEFAULT_APPROVAL_TTL_MINUTES: int = 30
    MERCHANT_ID: str = "MERCH-ACME-001"
    MERCHANT_NAME: str = "Acme Workspace Supplies"
    CURRENCY: str = "USD"
    MAX_ORDER_CENTS: int = 500000  # $5,000.00 ceiling

    # Multi-LLM Failover API keys & models
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"
    GEMINI_FALLBACK_MODEL: str = "gemini-2.5-flash-lite"
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "openai/gpt-oss-120b"
    XAI_API_KEY: str = ""
    XAI_MODEL: str = "grok-2-latest"
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_MODEL: str = "google/gemma-4-31b-it:free"
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"

    # PayPal Sandbox Configuration
    PAYPAL_CLIENT_ID: str = ""
    PAYPAL_CLIENT_SECRET: str = ""
    PAYPAL_MODE: str = "sandbox"
    PAYPAL_BASE_URL: str = "https://api-m.sandbox.paypal.com"
    PAYPAL_MCP_ENABLED: bool = True

    model_config = SettingsConfigDict(
        env_file=ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()


@lru_cache()
def get_settings() -> Settings:
    return settings
