import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.codex import CodexEvent, SUPPORTED_EVENT_TYPE, format_codex_notification
from app.config import Settings
from app.dependencies import get_settings, verify_secret
from app.meow import push_meow

logger = logging.getLogger("acr-notifier.codex")
router = APIRouter(dependencies=[Depends(verify_secret)])


@router.post("/payload_codex", openapi_extra={
    "requestBody": {
        "required": True,
        "content": {"application/json": {"schema": CodexEvent.model_json_schema()}},
    },
})
async def codex_payload(request: Request, settings: Settings = Depends(get_settings)):
    # 本接口自行验证原始 JSON，使编码错误也返回 422；不改变旧接口的解析行为。
    try:
        event = CodexEvent.model_validate_json(await request.body())
    except ValidationError as exc:
        errors = exc.errors(include_input=False, include_context=False, include_url=False)
        for error in errors:
            error["loc"] = ["body", *error["loc"]]
        raise HTTPException(status_code=422, detail=errors) from exc

    if event.event_type != SUPPORTED_EVENT_TYPE:
        logger.info(
            "Codex event type=%r thread_id=%r turn_id=%r ignored=true",
            event.event_type, event.thread_id, event.turn_id,
        )
        return {"ok": True, "ignored": True, "reason": "unsupported event type"}

    notification = format_codex_notification(event)
    # 同步推送放入线程池；接收账号和跳转地址只读取服务端配置。
    result = await run_in_threadpool(
        push_meow,
        settings,
        settings.miao_nickname,
        notification.title,
        notification.msg,
        settings.default_jump_url or None,
    )
    logger.info(
        "Codex event type=%r thread_id=%r turn_id=%r http_status=%s",
        event.event_type, event.thread_id, event.turn_id, result["http_status"],
    )
    return {"ok": True, "meow_result": result}
