"""MeoW HTTP 推送；调用方负责通过线程池隔离同步网络请求。"""

import logging
from typing import Any, Dict, Optional
from urllib.parse import quote

import requests

from app.config import Settings

logger = logging.getLogger("acr-notifier.meow")


def push_meow(
    settings: Settings,
    nickname: str,
    title: str,
    msg: str,
    url: Optional[str] = None,
) -> Dict[str, Any]:
    endpoint = f"{settings.miao_api_base.rstrip('/')}/{quote(nickname, safe='')}"
    payload = {"title": title or settings.default_title, "msg": msg}
    if url:
        payload["url"] = url

    try:
        response = requests.post(endpoint, json=payload, timeout=10)
        with response:
            content_type = response.headers.get("content-type", "")
            data = (
                response.json()
                if content_type.startswith("application/json")
                else {"text": response.text}
            )
            logger.info("MeoW response status=%s", response.status_code)
            return {"http_status": response.status_code, "resp": data}
    except (requests.RequestException, ValueError) as exc:
        logger.warning("MeoW request failed: %s", type(exc).__name__)
        return {"http_status": 0, "error": str(exc)}
