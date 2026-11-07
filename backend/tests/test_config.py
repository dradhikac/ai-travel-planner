"""Tests for application settings and environment parsing."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings


def test_default_settings() -> None:
    """Settings must have sensible defaults for local development."""
    settings = Settings()
    assert settings.APP_ENV == "development"
    assert settings.LOG_LEVEL == "INFO"
    assert settings.CORS_ORIGINS == [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]


def test_override_via_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings must respect environment variable overrides."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    monkeypatch.setenv(
        "CORS_ORIGINS",
        "https://concierge.travel, https://app.travel",
    )

    settings = Settings()
    assert settings.APP_ENV == "production"
    assert settings.LOG_LEVEL == "WARNING"
    assert settings.CORS_ORIGINS == [
        "https://concierge.travel",
        "https://app.travel",
    ]


def test_invalid_app_env_raises_validation_error() -> None:
    """APP_ENV with invalid value raises ValidationError."""
    with pytest.raises(ValidationError):
        Settings(APP_ENV="staging")


def test_cors_origins_wildcard_rejected() -> None:
    """CORS_ORIGINS containing wildcard '*' must raise ValidationError."""
    with pytest.raises(ValidationError, match="Wildcard '\\*' is not permitted"):
        Settings(CORS_ORIGINS="*")

    with pytest.raises(ValidationError, match="Wildcard '\\*' is not permitted"):
        Settings(CORS_ORIGINS="http://localhost:3000, *")

    with pytest.raises(ValidationError, match="Wildcard '\\*' is not permitted"):
        Settings(CORS_ORIGINS=["*"])


def test_cors_origins_trimming_and_dropping_empties() -> None:
    """CORS_ORIGINS must trim whitespace and omit empty items."""
    settings = Settings(
        CORS_ORIGINS=" http://localhost:3000 , , http://localhost:8080 , ",
    )
    assert settings.CORS_ORIGINS == [
        "http://localhost:3000",
        "http://localhost:8080",
    ]


def test_get_settings_cached() -> None:
    """get_settings must return cached singleton instance."""
    get_settings.cache_clear()
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2
    get_settings.cache_clear()
