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
    yield
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
app.include_router(api_router)
