"""Pytest fixtures for backend test suite."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.main import create_app


@pytest.fixture
def settings() -> Settings:
    """Return test settings instance."""
    return Settings(
        APP_ENV="test",
        LOG_LEVEL="DEBUG",
        CORS_ORIGINS=["http://localhost:3000"],
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    """Return application instance configured with test settings."""
    test_app = create_app(settings=settings)
    test_app.dependency_overrides[get_settings] = lambda: settings

    # Add test-only routes to verify validation and internal error handlers
    @test_app.get("/test/validation")
    def sample_validation_route(item_id: int) -> dict[str, int]:
        return {"item_id": item_id}

    @test_app.get("/test/induced-500")
    def sample_error_route() -> None:
        raise RuntimeError("Induced unexpected internal server failure")

    return test_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """Return FastAPI TestClient with server exceptions caught."""
    return TestClient(app, raise_server_exceptions=False)
