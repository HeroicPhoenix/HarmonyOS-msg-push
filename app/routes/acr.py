import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, Request
from starlette.concurrency import run_in_threadpool

from app.acr import format_acr_notification
from app.config import Settings
from app.dependencies import get_settings, verify_secret
from app.meow import push_meow

logger = logging.getLogger("acr-notifier.acr")
router = APIRouter(dependencies=[Depends(verify_secret)])


@router.post("/payload_acr")
async def acr_payload(
    request: Request,
    user_agent: Optional[str] = Header(None),
    settings: Settings = Depends(get_settings),
):
    notification = format_acr_notification(await request.body(), settings)
    logger.info("ACR notification title=%s", notification.title)
    result = await run_in_threadpool(
        push_meow,
        settings,
        settings.miao_nickname,
        notification.title,
        notification.msg,
        notification.url,
    )
    # 保留原有响应契约：ok 表示 Webhook 已处理，推送状态看 meow_result。
    return {"ok": True, "meow_result": result, "user_agent": user_agent}
