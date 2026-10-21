"""Codex 服务端回归；所有 MeoW 请求均为 mock，使用 fake 账号。"""

import asyncio
import json
import threading
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import httpx
import requests
from fastapi.testclient import TestClient

from app import create_app
from app.codex import ANSWER_MAX_LENGTH, TASK_MAX_LENGTH, TITLE_MAX_LENGTH
from app.config import Settings

EVENT_TYPE = "agent-turn-complete"
RECEIVED_AT = datetime(2026, 10, 21, 18, 30, tzinfo=timezone(timedelta(hours=8)))


def meow_response(status=200, data=None, content_type="application/json"):
    response = requests.Response()
    response.status_code = status
    response.headers["content-type"] = content_type
    response._content = (
        json.dumps(data if data is not None else {"success": True}).encode()
        if content_type == "application/json" else b"unavailable"
    )
    return response


class CodexTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(miao_nickname="fake-account", miao_api_base="https://meow.invalid")
        self.client = TestClient(create_app(self.settings))
        self.addCleanup(self.client.close)
        upstream = patch("app.meow.requests.post", return_value=meow_response())
        self.upstream = upstream.start()
        self.addCleanup(upstream.stop)
        clock = patch("app.codex.datetime")
        self.clock = clock.start()
        self.clock.now.return_value = RECEIVED_AT
        self.addCleanup(clock.stop)

    def send(self, **fields):
        return self.client.post("/payload_codex", json={"type": EVENT_TYPE, **fields})

    def sent(self):
        return self.upstream.call_args.kwargs["json"]

    def test_standard_event_and_meow_arguments(self):
        response = self.send(**{
            "thread-id": "thread-example", "turn-id": "turn-example",
            "cwd": "/Users/mack/projects/reviewx-server",
            "input-messages": ["修复筛选条件联动问题，并执行相关测试"],
            "last-assistant-message": "已修复筛选条件联动问题，相关测试通过。",
            "device-name": "Mac",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "meow_result": {
            "http_status": 200, "resp": {"success": True},
        }})
        self.upstream.assert_called_once_with(
            "https://meow.invalid/fake-account", timeout=10, json={
                "title": "Codex 本轮完成 · reviewx-server",
                "msg": "设备：Mac\n项目：reviewx-server\n任务：修复筛选条件联动问题，并执行相关测试\n"
                       "回答：已修复筛选条件联动问题，相关测试通过。\n接收时间：2026-10-21 18:30:00 +08:00",
            },
        )
        self.clock.now.assert_called_once_with(timezone(timedelta(hours=8)))

    def test_only_type_produces_fallback_without_success_claims(self):
        self.assertEqual(self.send().status_code, 200)
        self.assertEqual(self.sent(), {
            "title": "Codex 本轮完成 · 未知项目",
            "msg": "项目：未知项目\n回答：本轮处理已结束，未提供回答正文\n接收时间：2026-10-21 18:30:00 +08:00",
        })
        for phrase in ("全部完成", "开发成功", "测试通过", "耗时", "完成时间"):
            self.assertNotIn(phrase, self.sent()["title"] + self.sent()["msg"])

    def test_missing_null_blank_and_empty_optional_fields(self):
        for value in (None, "", " \t\r\n "):
            with self.subTest(value=value):
                response = self.send(**{
                    "thread-id": value, "turn-id": value, "cwd": value,
                    "input-messages": None, "last-assistant-message": value, "device-name": value,
                })
                self.assertEqual(response.status_code, 200)
                self.assertEqual(self.sent()["title"], "Codex 本轮完成 · 未知项目")
                self.assertIn("回答：本轮处理已结束，未提供回答正文", self.sent()["msg"])
                self.assertNotIn("任务：", self.sent()["msg"])
                self.assertNotIn("设备：", self.sent()["msg"])
        for messages in ([], ["", "  ", "\t\n"]):
            self.assertEqual(self.send(**{"input-messages": messages}).status_code, 200)
            self.assertNotIn("任务：", self.sent()["msg"])

    def test_multiple_chinese_messages_are_joined_in_order(self):
        response = self.send(**{"input-messages": [" \t 修复\n筛选  ", "", " \n ", " 并执行\t测试 "]})
        self.assertEqual(response.status_code, 200)
        self.assertIn("任务：修复 筛选 并执行 测试\n", self.sent()["msg"])

    def test_answer_preserves_newlines_and_original_status_words(self):
        original = "  本轮未执行测试。\r\n\r\n  保留  两个空格。  \r\n需要后续核验。\n "
        self.send(**{"last-assistant-message": original})
        self.assertIn("回答：本轮未执行测试。\n\n  保留  两个空格。\n需要后续核验。\n接收时间：", self.sent()["msg"])
        self.assertEqual(self.sent()["title"], "Codex 本轮完成 · 未知项目")

    def test_task_and_answer_truncation_include_ellipsis(self):
        for limit, field, label in (
            (TASK_MAX_LENGTH, "input-messages", "任务："),
            (ANSWER_MAX_LENGTH, "last-assistant-message", "回答："),
        ):
            for length in (limit - 1, limit, limit + 1, limit * 3):
                with self.subTest(field=field, length=length):
                    text = "测" * length
                    self.send(**{field: [text] if field == "input-messages" else text})
                    excerpt = next(line[len(label):] for line in self.sent()["msg"].splitlines() if line.startswith(label))
                    self.assertEqual(excerpt, text if length <= limit else "测" * (limit - 1) + "…")
                    self.assertLessEqual(len(excerpt), limit)

    def test_title_limit_includes_prefix_and_ellipsis(self):
        prefix = "Codex 本轮完成 · "
        for size in (TITLE_MAX_LENGTH - len(prefix), TITLE_MAX_LENGTH * 2):
            self.send(cwd="/Users/fake/" + "项" * size)
            title = prefix + "项" * size
            self.assertEqual(self.sent()["title"], title if len(title) <= TITLE_MAX_LENGTH else title[:TITLE_MAX_LENGTH - 1] + "…")
            self.assertLessEqual(len(self.sent()["title"]), 80)

    def test_unix_windows_mixed_and_trailing_path_separators(self):
        for cwd, expected in (
            ("/Users/fake/projects/reviewx-server", "reviewx-server"),
            ("/Users/fake/projects/reviewx-server///", "reviewx-server"),
            ("C:\\Users\\fake\\reviewx-front\\", "reviewx-front"),
            ("C:/Users\\fake/projects/reviewx-front/\\", "reviewx-front"),
            ("\\\\nas\\share\\project\\", "project"),
            ("relative-project/", "relative-project"),
        ):
            with self.subTest(cwd=cwd):
                self.send(cwd=cwd)
                self.assertEqual(self.sent()["title"], f"Codex 本轮完成 · {expected}")
                self.assertIn(f"项目：{expected}\n", self.sent()["msg"])
                if cwd != expected:
                    self.assertNotIn(cwd, self.sent()["msg"])

    def test_roots_and_unusable_path_names_are_unknown(self):
        for cwd in ("/", "///", "\\", "C:\\", "D:/", ".", "..", "/ \t / "):
            with self.subTest(cwd=cwd):
                self.send(cwd=cwd)
                self.assertEqual(self.sent()["title"], "Codex 本轮完成 · 未知项目")

    def test_device_is_explicit_and_receipt_time_is_timezone_aware(self):
        self.send(**{"device-name": "  Mac\n Studio\t "})
        self.assertTrue(self.sent()["msg"].startswith("设备：Mac Studio\n"))
        self.assertRegex(self.sent()["msg"], r"接收时间：\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \+08:00$")
        self.client.post("/payload_codex", json={"type": EVENT_TYPE}, headers={"User-Agent": "Windows-device"})
        self.assertNotIn("设备：", self.sent()["msg"])

    def test_configured_jump_url_is_used_without_path_or_id_links(self):
        with TestClient(create_app(Settings(
            miao_nickname="fake-account", miao_api_base="https://meow.invalid",
            default_jump_url="https://example.invalid/codex",
        ))) as client:
            response = client.post("/payload_codex", json={
                "type": EVENT_TYPE, "cwd": "/private/project", "thread-id": "thread-link", "turn-id": "turn-link",
            })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.sent()["url"], "https://example.invalid/codex")
        for text in ("/private/project", "thread-link", "turn-link"):
            self.assertNotIn(text, self.sent()["msg"])
        self.send(cwd="/private/project", **{"thread-id": "thread-link"})
        self.assertNotIn("url", self.sent())

    def test_unknown_fields_cannot_override_account_or_notification(self):
        response = self.send(**{
            "nickname": "attacker", "url": "https://attacker.invalid", "title": "全部完成",
            "secret": "body-secret", "future-data": {"nested": [1, True, None]},
            "last_assistant_message": "wrong-field-name",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.upstream.call_args.args[0], "https://meow.invalid/fake-account")
        self.assertNotIn("url", self.sent())
        self.assertIn("未提供回答正文", self.sent()["msg"])
        self.assertNotIn("全部完成", self.sent()["title"])

    def test_unsupported_events_are_ignored_without_push(self):
        for event_type in ("approval-requested", "future-event", " agent-turn-complete "):
            with self.subTest(event_type=event_type):
                response = self.send(type=event_type, **{"last-assistant-message": "never send"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), {"ok": True, "ignored": True, "reason": "unsupported event type"})
        self.upstream.assert_not_called()
        self.clock.now.assert_not_called()

    def test_missing_or_invalid_type_never_pushes(self):
        for body in ({}, {"event_type": EVENT_TYPE}, *({"type": value} for value in (None, "", " \n\t", 1, True, [], {}))):
            with self.subTest(body=body):
                self.assertEqual(self.client.post("/payload_codex", json=body).status_code, 422)
        self.upstream.assert_not_called()

    def test_optional_field_type_errors_never_push(self):
        for field in ("thread-id", "turn-id", "cwd", "last-assistant-message", "device-name"):
            for value in (False, 12, 1.2, [], {}, ["string"]):
                with self.subTest(field=field, value=value):
                    self.assertEqual(self.send(**{field: value}).status_code, 422)
        for value in ("string", 1, False, {}, [None], [1], [True], ["valid", {}]):
            with self.subTest(input_messages=value):
                self.assertEqual(self.send(**{"input-messages": value}).status_code, 422)
        # 不支持的类型也先验证请求结构，不掩盖字段类型错误。
        self.assertEqual(self.send(type="future-event", cwd=[]).status_code, 422)
        self.upstream.assert_not_called()

    def test_non_json_non_objects_and_invalid_encoding_never_push(self):
        for raw in (b"", b"not JSON", b"{", b"null", b"[]", b"42", b"true", b'"text"', b"\xff"):
            with self.subTest(raw=raw):
                response = self.client.post("/payload_codex", content=raw, headers={"Content-Type": "application/json"})
                self.assertEqual(response.status_code, 422)
        self.upstream.assert_not_called()

    def test_secret_missing_wrong_and_body_value_are_rejected(self):
        with TestClient(create_app(Settings(
            webhook_secret="test-key", miao_nickname="fake-account", miao_api_base="https://meow.invalid",
        ))) as client:
            for query in (None, "wrong", ""):
                response = client.post("/payload_codex", params={"secret": query} if query is not None else None,
                                       json={"type": EVENT_TYPE, "secret": "test-key"})
                self.assertEqual(response.status_code, 401)
            self.upstream.assert_not_called()
            response = client.post("/payload_codex?secret=test-key", json={"type": EVENT_TYPE})
            self.assertEqual(response.status_code, 200)
            self.upstream.assert_called_once()

    def test_empty_secret_allows_requests_with_or_without_query(self):
        for params in (None, {"secret": "anything"}):
            response = self.client.post("/payload_codex", params=params, json={"type": EVENT_TYPE})
            self.assertEqual(response.status_code, 200)
        self.assertEqual(self.upstream.call_count, 2)

    def test_non_2xx_and_business_failure_are_preserved(self):
        for status, body in ((503, {"error": "upstream unavailable"}), (200, {"success": False, "message": "unknown account"})):
            with self.subTest(status=status):
                self.upstream.return_value = meow_response(status, body)
                response = self.send()
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), {"ok": True, "meow_result": {"http_status": status, "resp": body}})
        self.upstream.return_value = meow_response(502, content_type="text/plain")
        self.assertEqual(self.send().json()["meow_result"], {"http_status": 502, "resp": {"text": "unavailable"}})

    def test_timeout_result_is_preserved(self):
        self.upstream.side_effect = requests.Timeout("fake timeout")
        response = self.send()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "meow_result": {"http_status": 0, "error": "fake timeout"}})

    def test_logs_only_include_identifiers_type_and_status(self):
        with self.assertLogs("acr-notifier", level="INFO") as logs:
            self.send(**{
                "thread-id": "thread-log", "turn-id": "turn-log", "cwd": "/sensitive/project",
                "input-messages": ["private-input"], "last-assistant-message": "private-answer",
                "device-name": "private-device",
            })
        output = "\n".join(logs.output)
        for expected in (EVENT_TYPE, "thread-log", "turn-log", "http_status=200"):
            self.assertIn(expected, output)
        for forbidden in ("/sensitive/project", "private-input", "private-answer", "private-device", "fake-account", "meow.invalid"):
            self.assertNotIn(forbidden, output)

    def test_openapi_preserves_hyphenated_fields_and_existing_routes(self):
        paths = self.client.get("/openapi.json").json()["paths"]
        schema = paths["/payload_codex"]["post"]["requestBody"]["content"]["application/json"]["schema"]
        self.assertEqual(set(schema["properties"]), {
            "type", "thread-id", "turn-id", "cwd", "input-messages", "last-assistant-message", "device-name",
        })
        self.assertEqual(schema["required"], ["type"])
        self.assertTrue({"/health", "/notify", "/payload_acr", "/payload_codex"}.issubset(paths))
        self.assertNotIn("/payload", paths)


class CodexConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_health_responds_during_codex_push(self):
        started, release = threading.Event(), threading.Event()

        def slow_post(*args, **kwargs):
            started.set()
            if not release.wait(timeout=5):
                raise requests.Timeout("test did not release push")
            return meow_response()

        app = create_app(Settings(miao_nickname="fake-account", miao_api_base="https://meow.invalid"))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            with patch("app.meow.requests.post", side_effect=slow_post):
                push = asyncio.create_task(client.post("/payload_codex", json={"type": EVENT_TYPE}))
                try:
                    self.assertTrue(await asyncio.to_thread(started.wait, 2))
                    self.assertFalse(push.done())
                    health = await asyncio.wait_for(client.get("/health"), timeout=1)
                    self.assertEqual(health.status_code, 200)
                    self.assertFalse(push.done())
                finally:
                    release.set()
                    response = await push
                self.assertEqual(response.json()["meow_result"]["http_status"], 200)


if __name__ == "__main__":
    unittest.main()
