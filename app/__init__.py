"""组装应用，配置、路由和外部推送分别维护。"""

import logging
from typing import Optional

from fastapi import FastAPI

from app.config import Settings
from app.routes import acr, health, notify


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings if settings is not None else Settings.from_env()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    app = FastAPI(title="ACR Webhook → MeoW Notifier", version="1.1.0")
    app.state.settings = settings
    app.include_router(health.router)
    app.include_router(notify.router)
    app.include_router(acr.router)
    return app
