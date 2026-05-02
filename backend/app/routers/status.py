from datetime import datetime

from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.database import get_db
from app.models.status import StatusCheck, StatusCheckCreate

router = APIRouter(prefix="/status", tags=["status"])


@router.post("", response_model=StatusCheck)
async def create_status_check(
    payload: StatusCheckCreate,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> StatusCheck:
    status_obj = StatusCheck(**payload.model_dump())
    doc = status_obj.model_dump()
    doc["timestamp"] = doc["timestamp"].isoformat()
    await db.status_checks.insert_one(doc)
    return status_obj


@router.get("", response_model=list[StatusCheck])
async def list_status_checks(
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> list[StatusCheck]:
    raw = await db.status_checks.find({}, {"_id": 0}).to_list(1000)
    for check in raw:
        if isinstance(check.get("timestamp"), str):
            check["timestamp"] = datetime.fromisoformat(check["timestamp"])
    return [StatusCheck(**check) for check in raw]
