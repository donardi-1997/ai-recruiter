from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import CORS_ORIGINS, logger
from core.aws_clients import ensure_rankings_table_exists

from routers import auth, health, candidates, jobs, evaluations, rankings


# ============================================================
# LIFESPAN
# ============================================================


@asynccontextmanager
async def lifespan(app):
    logger.info("Starting AI Recruiter API...")
    ensure_rankings_table_exists()
    yield
    logger.info("Shutting down AI Recruiter API.")


# ============================================================
# FASTAPI APP
# ============================================================

app = FastAPI(
    title="AI Recruiter API",
    description=(
        "API de gesti\u00f3n y consulta de candidatos "
        "usando Amazon Bedrock Knowledge Bases"
    ),
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# INCLUDE ROUTERS
# ============================================================

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(candidates.router)
app.include_router(jobs.router)
app.include_router(evaluations.router)
app.include_router(rankings.router)
