from contextlib import asynccontextmanager
import asyncio
import logging

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
import asyncpg

from rest_server import __version__
from rest_server.database import close_pool, get_pool, init_pool
from rest_server.errors import database_unavailable
from rest_server.features.weekly_report.service import run_scheduler_loop as run_weekly_report_loop
from rest_server.routes import agent_tools, ask_patra, assets, datasheets, experiments, hf_import, model_cards, users
from shared.config import (
    get_db_startup_timeout_seconds,
    is_ask_patra_enabled,
    is_domain_experiments_enabled,
    is_hf_import_enabled,
    is_weekly_report_enabled,
)

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Starting Patra FastAPI backend")
    pool = None
    db_startup_timeout = get_db_startup_timeout_seconds()
    try:
        pool = await asyncio.wait_for(init_pool(), timeout=db_startup_timeout)
    except Exception:
        log.exception("Database initialization failed within startup timeout; starting in degraded mode")

    weekly_report_task: asyncio.Task | None = None
    if is_weekly_report_enabled():
        weekly_report_task = asyncio.create_task(run_weekly_report_loop())
        log.info("Weekly report scheduler enabled")
    else:
        log.info("Weekly report scheduler disabled")

    yield

    log.info("Stopping Patra FastAPI backend")
    if weekly_report_task is not None:
        weekly_report_task.cancel()
        try:
            await weekly_report_task
        except asyncio.CancelledError:
            pass
    await close_pool()


app = FastAPI(
    title="Patra Privacy API",
    description="API for model cards and datasheets with JWT-aware privacy",
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(model_cards.router)
app.include_router(datasheets.router)
app.include_router(assets.router)
app.include_router(agent_tools.router)
app.include_router(users.router)

if is_ask_patra_enabled():
    app.include_router(ask_patra.router)
    log.info("Ask Patra routes enabled")
else:
    log.info("Ask Patra routes disabled")

if is_domain_experiments_enabled():
    app.include_router(experiments.router)
    log.info("Experiment routes enabled")
else:
    log.info("Experiment routes disabled")

if is_hf_import_enabled():
    app.include_router(hf_import.router)
    log.info("HF import routes enabled")
else:
    log.info("HF import routes disabled")


@app.get("/")
async def root():
    return {"message": "Welcome to the Patra Privacy API", "version": __version__}


@app.get("/healthz")
async def healthz():
    """Liveness probe: confirms the process is up."""
    return {"status": "ok"}


@app.get("/readyz")
async def readyz(pool: asyncpg.Pool = Depends(get_pool)):
    """Readiness probe: confirms the API can still talk to PostgreSQL."""
    try:
        async with pool.acquire() as conn:
            value = await conn.fetchval("SELECT 1")
    except Exception as exc:
        log.exception("Readiness check failed: %s", exc)
        raise database_unavailable()
    if value != 1:
        raise database_unavailable()
    return {"status": "ok"}
