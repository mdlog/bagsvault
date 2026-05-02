from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config import settings

client: AsyncIOMotorClient = AsyncIOMotorClient(settings.mongo_url)
db: AsyncIOMotorDatabase = client[settings.db_name]


async def close_db() -> None:
    client.close()


def get_db() -> AsyncIOMotorDatabase:
    return db
