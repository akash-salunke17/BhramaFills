"""Master API router aggregating all version 1 route modules."""

from fastapi import APIRouter

from app.api.routes import evidence, gaps, health, projects, sources, web

api_router = APIRouter()

# Register health check routes
api_router.include_router(health.router)

# Register research projects CRUD routes
api_router.include_router(projects.router)

# Register web extraction routes
api_router.include_router(web.router)

# Register project sources routes
api_router.include_router(sources.router)

# Register evidence persistence and retrieval routes
api_router.include_router(evidence.router)

# Register information gap detection, persistence, retrieval, and review routes
api_router.include_router(gaps.router)
