"""FastAPI application entry point and factory for Bharmafills backend."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure an isolated FastAPI application instance.

    Args:
        settings: Optional custom Settings instance (useful for testing overrides).
                  If omitted, uses the cached application settings.

    Returns:
        Configured FastAPI application instance.
    """
    if settings is None:
        settings = get_settings()

    # Determine documentation visibility based on environment
    docs_url = settings.DOCS_URL if not settings.is_production else None
    redoc_url = settings.REDOC_URL if not settings.is_production else None
    openapi_url = settings.OPENAPI_URL if not settings.is_production else None

    application = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        description=settings.DESCRIPTION,
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
    )

    # Configure CORS Middleware
    if settings.CORS_ORIGINS:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=settings.CORS_ORIGINS,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["*"],
        )

    # Register API v1 Router with configured prefix
    application.include_router(api_router, prefix=settings.API_V1_PREFIX)

    # Attach settings to dependency overrides if custom settings provided
    application.dependency_overrides[get_settings] = lambda: settings

    return application


# Canonical app instance for Uvicorn ASGI server
app = create_app()
