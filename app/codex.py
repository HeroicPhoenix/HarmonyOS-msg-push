"""Codex notify 请求模型与原文摘录格式化，不访问网络或推断任务状态。"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

SUPPORTED_EVENT_TYPE = "agent-turn-complete"
TITLE_MAX_LENGTH = 80
TASK_MAX_LENGTH = 120
ANSWER_MAX_LENGTH = 800
ELLIPSIS = "…"
RECEIVED_TIMEZONE = timezone(timedelta(hours=8))
FALLBACK_ANSWER = "本轮处理已结束，未提供回答正文"


class CodexEvent(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")

    event_type: str = Field(alias="type", min_length=1)
    thread_id: Optional[str] = Field(default=None, alias="thread-id")
    turn_id: Optional[str] = Field(default=None, alias="turn-id")
    cwd: Optional[str] = None
    input_messages: Optional[list[str]] = Field(default=None, alias="input-messages")
    last_assistant_message: Optional[str] = Field(default=None, alias="last-assistant-message")
    device_name: Optional[str] = Field(default=None, alias="device-name")

    @field_validator("event_type")
    @classmethod
    def require_nonblank_type(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("type must not be blank")
        return value


@dataclass(frozen=True)
class CodexNotification:
    title: str
    msg: str


def truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit - len(ELLIPSIS)] + ELLIPSIS


def single_line(text: Optional[str]) -> str:
    return " ".join((text or "").split())


def project_name(cwd: Optional[str]) -> str:
    parts = [part.strip() for part in re.split(r"[\\/]+", cwd or "") if part.strip()]
    name = parts[-1] if parts else ""
    # 不把根目录、Windows 盘符或相对目录标记当作项目名称。
    if not name or name in (".", "..") or re.fullmatch(r"[A-Za-z]:", name):
        return "未知项目"
    return single_line(name)


def format_codex_notification(event: CodexEvent) -> CodexNotification:
    received_at = datetime.now(RECEIVED_TIMEZONE)
    project = project_name(event.cwd)
    task = single_line(" ".join(event.input_messages or []))
    # 统一 CRLF 等换行，清理行尾及首尾空白，保留正文换行和行内原文。
    answer = "\n".join(
        line.rstrip() for line in (event.last_assistant_message or "").splitlines()
    ).strip() or FALLBACK_ANSWER

    lines = []
    device = single_line(event.device_name)
    if device:
        lines.append(f"设备：{device}")
    lines.append(f"项目：{project}")
    if task:
        lines.append(f"任务：{truncate(task, TASK_MAX_LENGTH)}")
    lines.append(f"回答：{truncate(answer, ANSWER_MAX_LENGTH)}")
    lines.append(f"接收时间：{received_at:%Y-%m-%d %H:%M:%S} +08:00")
    return CodexNotification(
        title=truncate(f"Codex 本轮完成 · {project}", TITLE_MAX_LENGTH),
        msg="\n".join(lines),
    )
