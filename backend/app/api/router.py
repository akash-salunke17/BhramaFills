"""Master API router aggregating all version 1 route modules."""

from fastapi import APIRouter

from app.api.routes import health

api_router = APIRouter()

# Register health check routes
api_router.include_router(health.router)
