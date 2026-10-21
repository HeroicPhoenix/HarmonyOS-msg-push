"""ACR 请求解析和通知格式化；不执行网络请求。"""

import json
from dataclasses import dataclass

from app.config import Settings


@dataclass(frozen=True)
class AcrNotification:
    title: str
    msg: str
    url: str


def format_acr_notification(raw: bytes, settings: Settings) -> AcrNotification:
    raw_text = raw.decode("utf-8", errors="ignore")
    try:
        data = json.loads(raw_text) if raw_text else {}
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}

    push_data = data.get("push_data")
    repo = data.get("repository")
    push_data = push_data if isinstance(push_data, dict) else {}
    repo = repo if isinstance(repo, dict) else {}

    tag = push_data.get("tag", "")
    repo_full = repo.get("repo_full_name") or (
        f"{repo.get('namespace') or ''}/{repo.get('name') or ''}".strip("/")
    )
    fields = [
        ("仓库", repo_full),
        ("区域", repo.get("region")),
        ("Tag", tag),
        ("Digest", push_data.get("digest")),
        ("时间", push_data.get("pushed_at")),
    ]
    msg = "\n".join(f"{label}：{value}" for label, value in fields if value)
    return AcrNotification(
        title=f"镜像自动构建完成: {repo_full}:{tag or 'latest'}",
        msg=msg or "收到 ACR 推送",
        url=settings.default_jump_url or repo_full,
    )
