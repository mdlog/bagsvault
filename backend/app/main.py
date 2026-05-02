import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import APIRouter, FastAPI
from starlette.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import close_db, ensure_indexes
from app.exceptions import register_exception_handlers
from app.routers import (
    anonymity,
    bags,
    compliance,
    deposits,
    health,
    proofs,
    relayers,
    root,
    status,
    tokens,
    withdrawals,
)

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logger.info(
        "Starting BagsVault backend (db=%s, cluster=%s)",
        settings.db_name,
        settings.solana_cluster,
    )
    await ensure_indexes()

    # Phase 3: spawn the merkle-root indexer worker. Wrapped in a broad
    # try/except so a worker startup failure (e.g. a misconfigured RPC
    # URL) never blocks the API from coming up.
    worker = None
    if settings.indexer_enabled and settings.bagsvault_program_id:
        try:
            from app.services.indexer_worker import get_indexer_worker

            worker = get_indexer_worker()
            await worker.start()
        except Exception:  # noqa: BLE001 — degrade gracefully on startup
            logger.exception("Failed to start IndexerWorker — continuing without it.")
            worker = None

    yield

    if worker is not None:
        try:
            await worker.stop()
        except Exception:  # noqa: BLE001 — never block shutdown
            logger.exception("IndexerWorker.stop raised — continuing shutdown.")

    await close_db()
    logger.info("Mongo client closed")


app = FastAPI(
    title="BagsVault API",
    description="Backend service for the BagsVault privacy protocol.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)

api_router = APIRouter(prefix="/api")
api_router.include_router(root.router)
api_router.include_router(health.router)
api_router.include_router(status.router)
api_router.include_router(compliance.router)
api_router.include_router(bags.router)
api_router.include_router(tokens.router)
api_router.include_router(deposits.router)
api_router.include_router(withdrawals.router)
api_router.include_router(relayers.router)
api_router.include_router(anonymity.router)
api_router.include_router(proofs.router)
app.include_router(api_router)
