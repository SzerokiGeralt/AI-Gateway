"""Konfiguracja aplikacji oparta na pydantic-settings."""
from functools import lru_cache
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Wszystkie zmienne środowiskowe w jednym typowanym obiekcie."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ---------- Aplikacja ----------
    APP_NAME: str = "Big Brother Proxy"
    APP_ENV: str = "development"
    DEBUG: bool = False
    ALLOWED_ORIGINS: str = "http://localhost:3000"

    # ---------- JWT ----------
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60

    # ---------- Database ----------
    DATABASE_URL: str

    # ---------- Redis ----------
    REDIS_URL: str = "redis://redis:6379/0"

    # ---------- Anthropic ----------
    ANTHROPIC_API_KEY: str
    ANTHROPIC_MODEL_NAME: str = "claude-sonnet-4-5"

    # ---------- DLP ----------
    # mpnet (768-dim) daje lepszy contrast niz MiniLM (384-dim) dla polskich tekstow.
    DLP_CLASSIFIER_MODEL: str = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
    # cosine similarity, 0.55 = umiarkowane semantyczne dopasowanie
    DLP_CLASSIFIER_THRESHOLD: float = 0.55

    # ---------- SMTP ----------
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""
    SMTP_TO: str = ""
    SMTP_USE_TLS: bool = True
    SMTP_USE_SSL: bool = False  # SSL/TLS bezpośrednie (port 465)

    # ---------- Rate limiting ----------
    CHAT_RATE_LIMIT: str = "30/minute"

    # ---------- Initial admin (seed) ----------
    INITIAL_ADMIN_USERNAME: str = "admin"
    INITIAL_ADMIN_PASSWORD: str = "ChangeMeNow!"

    @field_validator("JWT_SECRET_KEY")
    @classmethod
    def _validate_jwt_secret(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError(
                "JWT_SECRET_KEY musi mieć min. 32 znaki — wygeneruj losowy ciąg."
            )
        return v

    @property
    def cors_origins(self) -> List[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cache instancji ustawień — czytamy .env raz."""
    return Settings()


settings = get_settings()
