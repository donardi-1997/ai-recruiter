"""FastAPI application factory and composition root."""

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.auth_routes import router as auth_router
from app.config import CORS_ORIGINS, get_database_url
from app.db import Base, get_engine
from app.domains.candidate_imports.router import router as candidate_imports_router
from app.domains.candidates.router import assign_router, router as candidates_router
from app.domains.evaluations.router import router as evaluations_router
from app.domains.jobs.router import router as jobs_router
from app.domains.ranking.router import router as ranking_router
from app.health import router as health_router

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Build the FastAPI application without changing its public contract."""
    app = FastAPI(
        title="AI Recruiter API (PostgreSQL)",
        description="Ranking de candidatos con PostgreSQL + advisory locks",
        version="2.0.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(CORS_ORIGINS),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(jobs_router)
    app.include_router(candidates_router)
    app.include_router(assign_router)
    app.include_router(evaluations_router)
    app.include_router(ranking_router)
    app.include_router(candidate_imports_router)

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(
            "Unhandled error on %s %s: %s",
            request.method,
            request.url.path,
            exc,
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Error interno del servidor."},
        )

    @app.on_event("startup")
    def on_startup() -> None:
        db_url = get_database_url()
        if "sqlite" in db_url or not db_url:
            logger.info("Skipping table creation (non-PostgreSQL URL).")
            return
        logger.info("Creating tables if not present ...")
        Base.metadata.create_all(bind=get_engine())
        logger.info("Tables ready.")

    return app
