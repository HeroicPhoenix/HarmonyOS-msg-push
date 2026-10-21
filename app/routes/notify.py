from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.config import Settings
from app.dependencies import get_settings, verify_secret
from app.meow import push_meow

router = APIRouter(dependencies=[Depends(verify_secret)])


@router.get("/notify")
def notify_get(
    msg: str = Query(..., description="通知内容"),
    title: Optional[str] = Query(None, description="通知标题"),
    url: Optional[str] = Query(None, description="点击跳转链接"),
    nickname: Optional[str] = Query(None, description="MeoW 昵称，默认使用环境变量"),
    settings: Settings = Depends(get_settings),
):
    # 同步路由由 FastAPI 在线程池执行，避免 requests 阻塞事件循环。
    return push_meow(
        settings,
        nickname or settings.miao_nickname,
        title or settings.default_title,
        msg,
        url or settings.default_jump_url or None,
    )


@router.post("/notify")
def notify_post(body: Dict[str, Any], settings: Settings = Depends(get_settings)):
    msg = str(body.get("msg") or "")
    if not msg:
        raise HTTPException(status_code=400, detail="msg is required")
    return push_meow(
        settings,
        str(body.get("nickname") or settings.miao_nickname),
        str(body.get("title") or settings.default_title),
        msg,
        body.get("url") or settings.default_jump_url or None,
    )
