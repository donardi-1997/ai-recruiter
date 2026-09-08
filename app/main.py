"""FastAPI application — PostgreSQL-backed AI Recruiter."""

import logging
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db import Base, get_engine
from app.health import router as health_router
from app.auth_routes import router as auth_router
from app.deps import get_current_user, get_db
from app.domains.jobs.router import router as jobs_router
from app.domains.candidates.router import router as candidates_router, assign_router
from app.domains.evaluations.router import router as evaluations_router
from app.domains.ranking.router import router as ranking_router

logger = logging.getLogger(__name__)

app = FastAPI(
    title="AI Recruiter API (PostgreSQL)",
    description="Ranking de candidatos con PostgreSQL + advisory locks",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:5175",
        "https://ai.adrianguerra.net",
        "https://air.adrianguerra.net",
    ],
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


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled error on %s %s: %s", request.method, request.url.path, exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Error interno del servidor."},
    )


@app.on_event("startup")
def on_startup() -> None:
    db_url = os.getenv("DATABASE_URL", "")
    if "sqlite" in db_url or not db_url:
        logger.info("Skipping table creation (non-PostgreSQL URL).")
        return
    logger.info("Creating tables if not present ...")
    Base.metadata.create_all(bind=get_engine())
    logger.info("Tables ready.")