from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING

from app.config import settings

client: AsyncIOMotorClient = AsyncIOMotorClient(settings.mongo_url)
db: AsyncIOMotorDatabase = client[settings.db_name]


async def close_db() -> None:
    client.close()


def get_db() -> AsyncIOMotorDatabase:
    return db


async def ensure_indexes() -> None:
    """Idempotent index creation. Safe to call on every startup."""

    # commitments — uniqueness on commitment hash, lookup by merkle index
    await db.commitments.create_index([("commitment", ASCENDING)], unique=True)
    await db.commitments.create_index([("merkle_index", ASCENDING)], unique=True)
    await db.commitments.create_index([("created_at", DESCENDING)])

    # withdrawals — uniqueness on nullifier (double-spend guard)
    await db.withdrawals.create_index([("nullifier_hash", ASCENDING)], unique=True)
    await db.withdrawals.create_index([("created_at", DESCENDING)])
    await db.withdrawals.create_index([("relayer_id", ASCENDING)])

    # risk_scans — TTL 30 days (results revalidated periodically)
    await db.risk_scans.create_index([("address", ASCENDING)])
    await db.risk_scans.create_index(
        [("scanned_at", ASCENDING)], expireAfterSeconds=60 * 60 * 24 * 30
    )

    # relayers — unique by relayer id and pubkey
    await db.relayers.create_index([("relayer_id", ASCENDING)], unique=True)
    await db.relayers.create_index([("pubkey", ASCENDING)], unique=True)

    # merkle_roots — recent roots cache
    await db.merkle_roots.create_index([("root", ASCENDING)], unique=True)
    await db.merkle_roots.create_index([("indexed_at", DESCENDING)])

    # creators — unique by wallet pubkey
    await db.creators.create_index([("wallet", ASCENDING)], unique=True)

    # tokens — project token registry; one entry per token mint
    await db.tokens.create_index([("mint", ASCENDING)], unique=True)
    await db.tokens.create_index([("creator_wallet", ASCENDING)])

    # idempotency keys — TTL 24h
    await db.idempotency_keys.create_index([("key", ASCENDING)], unique=True)
    await db.idempotency_keys.create_index(
        [("created_at", ASCENDING)], expireAfterSeconds=60 * 60 * 24
    )
