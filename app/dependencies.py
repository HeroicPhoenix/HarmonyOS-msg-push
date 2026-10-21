"""路由共用的配置获取与可选密钥校验。"""

import secrets
from typing import Optional

from fastapi import Depends, HTTPException, Query, Request

from app.config import Settings


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def verify_secret(
    secret: Optional[str] = Query(None),
    settings: Settings = Depends(get_settings),
) -> None:
    if settings.webhook_secret and not secrets.compare_digest(
        (secret or "").encode("utf-8"), settings.webhook_secret.encode("utf-8")
    ):
        raise HTTPException(status_code=401, detail="secret invalid")
