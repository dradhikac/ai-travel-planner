"""Tests for application settings and environment parsing."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_default_settings() -> None:
    """Settings must have sensible defaults for local development."""
    settings = Settings()
    assert settings.APP_ENV in ("development", "test", "production")
    assert settings.LOG_LEVEL == "INFO"
    assert "http://localhost:3000" in settings.CORS_ORIGINS
    assert "http://127.0.0.1:3000" in settings.CORS_ORIGINS


def test_cors_origins_comma_separated_parsing() -> None:
    """CORS_ORIGINS passed as comma-separated string must parse to clean list."""
    settings = Settings(
        CORS_ORIGINS="http://localhost:3000, http://localhost:8080 ,https://frontend.travel.local",
    )
    assert settings.CORS_ORIGINS == [
        "http://localhost:3000",
        "http://localhost:8080",
        "https://frontend.travel.local",
    ]


def test_custom_app_env() -> None:
    """APP_ENV accepts valid environment values."""
    settings = Settings(APP_ENV="production")
    assert settings.APP_ENV == "production"


def test_invalid_app_env_raises_validation_error() -> None:
    """APP_ENV with invalid value raises ValidationError."""
    with pytest.raises(ValidationError):
        Settings(APP_ENV="invalid_environment")
