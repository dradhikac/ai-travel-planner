"""Application configuration and typed settings."""

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings backed by environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_ENV: Literal["development", "test", "production"] = "development"
    LOG_LEVEL: str = "INFO"
    CORS_ORIGINS: list[str] | str = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    DATABASE_URL: str | None = None

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def empty_str_to_none(cls, v: str | None) -> str | None:
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("CORS_ORIGINS", mode="after")
    @classmethod
    def assemble_cors_origins(cls, v: list[str] | str) -> list[str]:
        if isinstance(v, str):
            origins = [i.strip() for i in v.split(",") if i.strip()]
        elif isinstance(v, list):
            origins = [str(i).strip() for i in v if str(i).strip()]
        else:
            return []

        for origin in origins:
            if origin == "*":
                raise ValueError(
                    "Wildcard '*' is not permitted in CORS_ORIGINS; "
                    "specify explicit origins."
                )
        return origins


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings singleton."""
    return Settings()
