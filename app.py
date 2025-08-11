# -*- coding: utf-8 -*-
import os
import json
import logging
import urllib.parse
from typing import Optional, Dict, Any

import requests
from fastapi import FastAPI, Request, Query, Header, HTTPException
from fastapi.responses import JSONResponse

# docker SDK
import docker
from docker.errors import APIError, NotFound

# ---------------- 日志初始化（支持 LOG_LEVEL 环境变量） ----------------
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
DEFAULT_JUMP_URL = os.getenv("DEFAULT_JUMP_URL", "")  # 可选：点开通知跳转链接

# ===== ACR & 本地镜像配置 =====
ACR_REGISTRY = os.getenv("ACR_REGISTRY", "crpi-v2fmzydhnzmlpzjc.cn-shanghai.personal.cr.aliyuncs.com")
# 强烈建议在部署环境里以环境变量注入以下两项
ACR_USERNAME = os.getenv("ACR_USERNAME", "")            # 例如：诺亚星耀
ACR_PASSWORD = os.getenv("ACR_PASSWORD", "")            # 例如：ma199991102

# 可选：只放行某个命名空间；为空不过滤
ALLOW_NAMESPACE = os.getenv("ALLOW_NAMESPACE", "").strip()

# 本地镜像名与 tag：LOCAL_IMAGE_NAME 若未设置，默认用 repo_full 的最后一段（简称）
LOCAL_IMAGE_NAME = os.getenv("LOCAL_IMAGE_NAME", "").strip()
LOCAL_TAG = os.getenv("LOCAL_TAG", "latest")

# 忽略 ACR 内部缓存 tag
IGNORE_TAG = "__ACR_BUILD_SERVICE_INTERNAL_IMAGE_CACHE"


# ============= 工具：把通知发到 MeoW =============
def push_meow(nickname: str, title: str, msg: str, url: Optional[str] = None) -> Dict[str, Any]:
    endpoint = f"{MIAO_API_BASE.rstrip('/')}/{urllib.parse.quote(nickname)}"
    payload = {"title": title or DEFAULT_TITLE, "msg": msg}
    if url:
        payload["url"] = url

    logger.info("[push_meow] endpoint=%s payload=%s", endpoint, payload)
    try:
        resp = requests.post(endpoint, json=payload, timeout=10)
        ctype = resp.headers.get("content-type", "")
        data = resp.json() if ctype.startswith("application/json") else {"text": resp.text}
        logger.info("[push_meow] status=%s resp=%s", resp.status_code, data)
        return {"http_status": resp.status_code, "resp": data}
    except Exception:
        logger.exception("[push_meow] exception occurred")
        return {"http_status": 0, "error": "push_meow exception, see logs"}


# ============= Docker 操作：login → pull → tag → rmi（仅本地） =============
def normalize_tag(tag: str) -> str:
    # 把误写的 lastest 兜底修正为 latest；空则默认 latest
    if tag and tag.lower() == "lastest":
        return "latest"
    return tag or "latest"

def docker_login_pull_tag_remove(repo_full: str, tag: str, local_image_name: Optional[str] = None) -> Dict[str, Any]:
    """
    等价于：
      docker login --username=<user> <registry>
      docker pull <registry>/<repo_full>:<tag>
      docker tag  <remote>  <local_image_name>:<LOCAL_TAG>
      docker rmi  <remote>
    ——全部是本地操作，不修改远端仓库。
    """
    results: Dict[str, Any] = {"steps": []}
    tag = normalize_tag(tag)
    local_image = (local_image_name or LOCAL_IMAGE_NAME or repo_full.split("/")[-1]).strip()
    if not local_image:
        return {"steps": [{"error": "local image name resolved empty"}], "rc": -1}

    remote = f"{ACR_REGISTRY}/{repo_full}:{tag}"
    local = f"{local_image}:{LOCAL_TAG}"

    logger.info("[docker] start: remote=%s -> local=%s", remote, local)
    client = docker.from_env()

    # 1) login（若无凭据则跳过，依赖已有登录）
    try:
        if not ACR_USERNAME or not ACR_PASSWORD:
            logger.warning("[docker] skip login: no creds; relying on existing login")
            results["steps"].append({"login": "skipped"})
        else:
            login_resp = client.login(username=ACR_USERNAME, password=ACR_PASSWORD, registry=ACR_REGISTRY)
            logger.info("[docker] login ok: %s", login_resp)
            results["steps"].append({"login": "ok"})
    except APIError as e:
        logger.exception("[docker] login failed")
        results["steps"].append({"login": f"failed: {getattr(e, 'explanation', str(e))}"})
        return results

    # 2) pull
    try:
        logger.info("[docker] pulling %s", remote)
        img = client.images.pull(remote)
        if isinstance(img, list) and img:
            img = img[0]
        results["steps"].append({"pull": "ok", "id": getattr(img, "id", "")})
    except APIError as e:
        logger.exception("[docker] pull failed")
        results["steps"].append({"pull": f"failed: {getattr(e, 'explanation', str(e))}"})
        return results

    # 3) tag
    try:
        logger.info("[docker] tagging %s -> %s", remote, local)
        (img if 'img' in locals() else client.images.get(remote)).tag(local_image, tag=LOCAL_TAG)
        results["steps"].append({"tag": "ok", "local": local})
    except (APIError, NotFound) as e:
        logger.exception("[docker] tag failed")
        results["steps"].append({"tag": f"failed: {str(e)}"})
        # 清理远端命名（本地）
        try:
            client.images.remove(remote)
        except Exception:
            pass
        return results

    # 4) rmi（删除本地的“远端命名”标签，保留本地简称标签）
    try:
        logger.info("[docker] removing %s", remote)
        client.images.remove(remote)
        results["steps"].append({"rmi": "ok"})
    except APIError as e:
        logger.warning("[docker] rmi failed: %s", getattr(e, 'explanation', str(e)))
        results["steps"].append({"rmi": f"failed: {getattr(e, 'explanation', str(e))}"})

    logger.info("[docker] done.")
    results["remote"] = remote
    results["local"] = local
    return results


# ============= 健康检查 =============
@app.get("/health")
async def health():
    return {
        "ok": True,
        "nickname": MIAO_NICKNAME,
        "api_base": MIAO_API_BASE,
        "registry": ACR_REGISTRY,
        "allow_namespace": ALLOW_NAMESPACE or "(no limit)",
        "local_image": f"{LOCAL_IMAGE_NAME or '<auto-from-repo>'}:{LOCAL_TAG}"
    }


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


# ============= Webhook：接收 ACR 推送（按结果决定消息文案） =============
@app.post("/payload")
async def acr_payload(request: Request, secret: Optional[str] = Query(None), user_agent: Optional[str] = Header(None)):
    # 读原始报文
    raw_bytes = await request.body()
    raw_text = raw_bytes.decode("utf-8", errors="ignore")
    logger.info("[POST /payload] UA=%s", user_agent)
    logger.info("[POST /payload] RAW=%s", raw_text[:4000])

    if WEBHOOK_SECRET and secret != WEBHOOK_SECRET:
        logger.warning("[POST /payload] secret invalid")
        raise HTTPException(status_code=401, detail="secret invalid")

    # 解析 JSON
    try:
        data = json.loads(raw_text) if raw_text else {}
    except Exception:
        logger.warning("[POST /payload] invalid JSON, fallback to raw text")
        data = {"raw": raw_text}

    push_data = data.get("push_data", {}) if isinstance(data, dict) else {}
    repo = data.get("repository", {}) if isinstance(data, dict) else {}

    tag = push_data.get("tag", "") or "latest"
    digest = push_data.get("digest", "")
    pushed_at = push_data.get("pushed_at", "")
    repo_full = repo.get("repo_full_name") or f"{repo.get('namespace','')}/{repo.get('name','')}".strip("/")
    namespace = (repo.get("namespace") or "").strip()
    region = repo.get("region", "")

    # 触发 docker：仅本地操作；忽略内部 tag；若设置了 ALLOW_NAMESPACE 则只放行该命名空间
    if not repo_full:
        deploy_result = {"skipped": True, "reason": "empty repo_full"}
    elif tag == IGNORE_TAG:
        deploy_result = {"skipped": True, "reason": f"ignored tag {IGNORE_TAG}"}
    elif ALLOW_NAMESPACE and namespace != ALLOW_NAMESPACE:
        deploy_result = {"skipped": True, "reason": f"namespace not allowed: {namespace}"}
    else:
        local_image_name = LOCAL_IMAGE_NAME or repo_full.split("/")[-1]
        logger.info("[deploy] repo=%s tag=%s local_image=%s", repo_full, tag, local_image_name)
        deploy_result = docker_login_pull_tag_remove(repo_full, tag, local_image_name)

    # 根据 docker 拉取结果决定消息文案（先拉取，再发消息）
    if deploy_result.get("skipped"):
        status_msg = "镜像自动构建完成（未触发自动拉取）"
    else:
        pull_step = next((s for s in deploy_result.get("steps", []) if "pull" in s), None)
        if pull_step and pull_step.get("pull") == "ok":
            status_msg = "镜像自动构建完成、自动拉取成功"
        else:
            status_msg = "镜像自动构建完成，未自动拉取成功"

    # 组装并发送消息
    msg_lines = [
        f"仓库：{repo_full}" if repo_full else None,
        f"区域：{region}" if region else None,
        f"Tag：{tag}" if tag else None,
        f"Digest：{digest}" if digest else None,
        f"时间：{pushed_at}" if pushed_at else None,
        f"状态：{status_msg}"
    ]
    msg = "\n".join([x for x in msg_lines if x]) or status_msg
    jump_url = DEFAULT_JUMP_URL or repo_full
    meow_res = push_meow(MIAO_NICKNAME, status_msg, msg, jump_url)

    return JSONResponse(
        content={
            "ok": True,
            "meow_result": meow_res,
            "deploy": deploy_result,
            "user_agent": user_agent
        },
        status_code=200
    )


# ============= 兼容：根路径也当作 /payload 来处理（适配 ACR 不带路径回调） =============
@app.post("/")
async def root_payload(request: Request, secret: Optional[str] = Query(None), user_agent: Optional[str] = Header(None)):
    logger.info("[POST /] redirect to /payload")
    return await acr_payload(request, secret, user_agent)


# 本地直接运行（开发用）
if __name__ == "__main__":
    import uvicorn
    logger.info("Starting uvicorn at 0.0.0.0:12082")
    uvicorn.run("app:app", host="0.0.0.0", port=12082, reload=True)
