# -*- coding: utf-8 -*-
import os
import json
import logging
import urllib.parse
from typing import Optional, Dict, Any

import requests
from fastapi import FastAPI, Request, Query, Header, HTTPException
from fastapi.responses import JSONResponse

# ---------------- 日志初始化（尽量少改，支持环境变量控制级别） ----------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("acr-notifier")

app = FastAPI(title="ACR Webhook → MeoW Notifier", version="1.0.0")

# ============= 可配置项（环境变量） =============
MIAO_NICKNAME = os.getenv("MIAO_NICKNAME", "")  # 你的 MeoW 昵称（必须在 MeoW 上先存在）
MIAO_API_BASE = os.getenv("MIAO_API_BASE", "https://api.chuckfang.com")  # MeoW API 基地址
DEFAULT_TITLE = os.getenv("DEFAULT_TITLE", "MeoW")  # 默认标题
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")  # 可选：共享密钥，校验 ?secret=xxx
DEFAULT_JUMP_URL = os.getenv("DEFAULT_JUMP_URL", "")  # 可选：点开通知跳转链接（比如你的服务地址）

# ============= 工具：把通知发到 MeoW =============
def push_meow(nickname: str, title: str, msg: str, url: Optional[str] = None) -> Dict[str, Any]:
    """
    使用 MeoW 的 POST JSON 方式推送（更稳，不用担心中文 URL 编码）。
    文档：https://www.chuckfang.com/MeoW/api_doc.html
    """
    endpoint = f"{MIAO_API_BASE.rstrip('/')}/{urllib.parse.quote(nickname)}"
    payload = {
        "title": title or DEFAULT_TITLE,
        "msg": msg,
    }
    if url:
        payload["url"] = url

    logger.info("[push_meow] endpoint=%s payload=%s", endpoint, payload)
    try:
        resp = requests.post(endpoint, json=payload, timeout=10)
        ctype = resp.headers.get("content-type", "")
        data = resp.json() if ctype.startswith("application/json") else {"text": resp.text}
        logger.info("[push_meow] status=%s resp=%s", resp.status_code, data)
        return {"http_status": resp.status_code, "resp": data}
    except Exception as e:
        logger.exception("[push_meow] exception occurred")
        return {"http_status": 0, "error": str(e)}

# ============= 健康检查 =============
@app.get("/health")
async def health():
    return {"ok": True, "nickname": MIAO_NICKNAME, "api_base": MIAO_API_BASE}

# ============= 手动触发（GET/POST） =============
@app.get("/notify")
async def notify_get(
    title: str = Query(DEFAULT_TITLE, description="通知标题"),
    msg: str = Query(..., description="通知内容"),
    url: Optional[str] = Query(None, description="点击跳转链接"),
    nickname: Optional[str] = Query(None, description="MeoW 昵称，默认使用环境变量"),
    secret: Optional[str] = Query(None, description="如果配置了 WEBHOOK_SECRET，需匹配")
):
    logger.info("[GET /notify] title=%s msg=%s url=%s nickname=%s", title, msg, url, nickname)
    if WEBHOOK_SECRET and secret != WEBHOOK_SECRET:
        logger.warning("[GET /notify] secret invalid")
        raise HTTPException(status_code=401, detail="secret invalid")
    res = push_meow(nickname or MIAO_NICKNAME, title, msg, url or DEFAULT_JUMP_URL or None)
    return res

@app.post("/notify")
async def notify_post(body: Dict[str, Any], secret: Optional[str] = Query(None)):
    """
    JSON 格式：
    {
      "title": "可选标题",
      "msg": "必填内容",
      "url": "可选链接",
      "nickname": "可选，缺省用环境变量"
    }
    """
    logger.info("[POST /notify] body=%s", body)
    if WEBHOOK_SECRET and secret != WEBHOOK_SECRET:
        logger.warning("[POST /notify] secret invalid")
        raise HTTPException(status_code=401, detail="secret invalid")

    title = str(body.get("title") or DEFAULT_TITLE)
    msg = str(body.get("msg") or "")
    if not msg:
        logger.warning("[POST /notify] msg is required")
        raise HTTPException(status_code=400, detail="msg is required")
    url = body.get("url") or DEFAULT_JUMP_URL or None
    nickname = body.get("nickname") or MIAO_NICKNAME

    res = push_meow(nickname, title, msg, url)
    return res

# ============= Webhook：接收 ACR 推送 =============
@app.post("/payload")
async def acr_payload(request: Request, secret: Optional[str] = Query(None), user_agent: Optional[str] = Header(None)):
    """
    接收阿里云 ACR Webhook（示例载荷见你的描述）
    将其格式化后转发到 MeoW 消息推送。
    """
    # 先读取原始报文，便于调试（重要：读一次后用本地变量解析）
    raw_bytes = await request.body()
    raw_text = raw_bytes.decode("utf-8", errors="ignore")
    logger.info("[POST /payload] UA=%s", user_agent)
    logger.info("[POST /payload] RAW=%s", raw_text[:4000])  # 防爆日志，最多打印 4000 字符

    if WEBHOOK_SECRET and secret != WEBHOOK_SECRET:
        logger.warning("[POST /payload] secret invalid")
        raise HTTPException(status_code=401, detail="secret invalid")

    # 尝试按 JSON 解析；失败则按 text 兜底
    try:
        data = json.loads(raw_text) if raw_text else {}
    except Exception:
        logger.warning("[POST /payload] invalid JSON, fallback to raw text")
        data = {"raw": raw_text}

    push_data = data.get("push_data", {}) if isinstance(data, dict) else {}
    repo = data.get("repository", {}) if isinstance(data, dict) else {}

    tag = push_data.get("tag", "")
    digest = push_data.get("digest", "")
    pushed_at = push_data.get("pushed_at", "")
    repo_full = repo.get("repo_full_name") or f"{repo.get('namespace','')}/{repo.get('name','')}".strip("/")
    region = repo.get("region", "")

    # 组装标题与内容
    title = f"镜像推送: {repo_full}:{tag or 'latest'}"
    msg_lines = [
        f"仓库：{repo_full}" if repo_full else None,
        f"区域：{region}" if region else None,
        f"Tag：{tag}" if tag else None,
        f"Digest：{digest}" if digest else None,
        f"时间：{pushed_at}" if pushed_at else None,
    ]
    msg = "\n".join([x for x in msg_lines if x]) or "收到 ACR 推送"

    # 生成一个可点击的跳转链接（可选）
    jump_url = DEFAULT_JUMP_URL or repo_full  # 你也可以换成 ACR 控制台具体地址

    logger.info("[POST /payload] title=%s msg=%s jump_url=%s", title, msg, jump_url)
    res = push_meow(MIAO_NICKNAME, title or DEFAULT_TITLE, msg, jump_url)
    return JSONResponse(content={"ok": True, "meow_result": res, "user_agent": user_agent}, status_code=200)

# ============= 兼容：根路径也当作 /payload 来处理（适配 ACR 不带路径回调） =============
@app.post("/")
async def root_payload(request: Request, secret: Optional[str] = Query(None), user_agent: Optional[str] = Header(None)):
    logger.info("[POST /] redirect to /payload")
    return await acr_payload(request, secret, user_agent)

# 直接 python app.py 运行（开发用）
if __name__ == "__main__":
    import uvicorn
    logger.info("Starting uvicorn at 0.0.0.0:12082")
    uvicorn.run("app:app", host="0.0.0.0", port=12082, reload=True)
