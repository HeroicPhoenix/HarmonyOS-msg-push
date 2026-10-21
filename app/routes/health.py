from fastapi import APIRouter, Depends

from app.config import Settings
from app.dependencies import get_settings

router = APIRouter()


@router.get("/health")
def health(settings: Settings = Depends(get_settings)):
    return {
        "ok": True,
        "nickname": settings.miao_nickname,
        "api_base": settings.miao_api_base,
    }
