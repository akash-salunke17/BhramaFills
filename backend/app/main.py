"""FastAPI application entry point and factory for Bharmafills backend."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.auth import SupabaseJWTVerifier, get_jwt_verifier
from app.core.config import Settings, get_settings
from app.db.connection import DatabaseManager, get_db_manager
from app.services.ai import OpenRouterClient, get_ai_provider


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

    db_manager = DatabaseManager(settings=settings)
    ai_provider = OpenRouterClient(settings=settings)
    jwt_verifier = SupabaseJWTVerifier(settings=settings)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        """Manage application startup and shutdown lifecycle events."""
        if db_manager.is_configured:
            await db_manager.initialize()
        yield
        await ai_provider.close()
        await db_manager.close()

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
        lifespan=lifespan,
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

    # Attach settings, db manager, ai provider, and jwt verifier to dependency overrides
    application.dependency_overrides[get_settings] = lambda: settings
    application.dependency_overrides[get_db_manager] = lambda: db_manager
    application.dependency_overrides[get_ai_provider] = lambda: ai_provider
    application.dependency_overrides[get_jwt_verifier] = lambda: jwt_verifier

    return application


# Canonical app instance for Uvicorn ASGI server
app = create_app()
