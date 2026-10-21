"""配置仅在创建应用时读取；本地运行不自动加载 .env。"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    miao_nickname: str = ""
    miao_api_base: str = "https://api.chuckfang.com"
    default_title: str = "MeoW"
    webhook_secret: str = ""
    default_jump_url: str = ""
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            miao_nickname=os.getenv("MIAO_NICKNAME", ""),
            miao_api_base=os.getenv("MIAO_API_BASE", "https://api.chuckfang.com"),
            default_title=os.getenv("DEFAULT_TITLE", "MeoW"),
            webhook_secret=os.getenv("WEBHOOK_SECRET", ""),
            default_jump_url=os.getenv("DEFAULT_JUMP_URL", ""),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )
