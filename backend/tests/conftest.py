"""Pytest fixtures for backend test suite."""

import socket
from collections.abc import Generator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.db.session import get_engine, get_session_factory
from app.main import create_app
from app.schemas.trip import TripRequest


@pytest.fixture(autouse=True)
def prevent_real_network_sockets(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prohibit unit tests from opening real network sockets.

    Integration-marked tests that talk to the local database remain allowed.
    Internal socketpair creation for asyncio loopback pipes on Windows is preserved.
    """
    if request.node.get_closest_marker("integration") is not None:
        return

    orig_connect = socket.socket.connect
    orig_connect_ex = socket.socket.connect_ex
    orig_socketpair = socket.socketpair
    in_socketpair = False

    def guarded_socketpair(
        *args: object, **kwargs: object
    ) -> tuple[socket.socket, socket.socket]:
        nonlocal in_socketpair
        in_socketpair = True
        try:
            return orig_socketpair(*args, **kwargs)  # type: ignore[arg-type]
        finally:
            in_socketpair = False

    def guarded_connect(
        self: socket.socket, address: tuple | str, *args: object, **kwargs: object
    ) -> None:
        if in_socketpair:
            orig_connect(self, address, *args, **kwargs)
            return
        raise RuntimeError(
            f"Network socket connection prohibited in unit tests: {address}. "
            "Mock external network calls or mark with @pytest.mark.integration."
        )

    def guarded_connect_ex(
        self: socket.socket, address: tuple | str, *args: object, **kwargs: object
    ) -> int:
        if in_socketpair:
            return orig_connect_ex(self, address, *args, **kwargs)
        raise RuntimeError(
            f"Network socket connection prohibited in unit tests: {address}. "
            "Mock external network calls or mark with @pytest.mark.integration."
        )

    monkeypatch.setattr(socket, "socketpair", guarded_socketpair)
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)


@pytest.fixture(autouse=True)
def isolate_test_state() -> Generator[None, None, None]:
    """Ensure test ordering independence by clearing global/cached state."""
    TripRequest.set_test_today(None)
    get_engine.cache_clear()
    get_session_factory.cache_clear()
    yield
    TripRequest.set_test_today(None)
    get_engine.cache_clear()
    get_session_factory.cache_clear()


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
