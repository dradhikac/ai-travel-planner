"""Main application entry point with app factory and module-level app."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import health, version
from app.core.config import Settings, get_settings
from app.core.errors import register_error_handlers
from app.core.logging import setup_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure FastAPI application instance."""
    if settings is None:
        settings = get_settings()

    setup_logging(settings.LOG_LEVEL)

    application = FastAPI(
        title="AI Travel Concierge Backend",
        version="0.1.0",
        docs_url="/docs" if settings.APP_ENV != "production" else None,
        redoc_url=None,
    )

    # Configure CORS middleware with explicit origins from settings
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register centralized error handlers
    register_error_handlers(application)

    # Register API route endpoints
    application.include_router(health.router)
    application.include_router(version.router)

    return application


app = create_app()
