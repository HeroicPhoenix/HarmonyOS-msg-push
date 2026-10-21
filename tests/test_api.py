"""接口回归：所有 MeoW 请求均替换为本地 mock，不发送真实通知。"""

import asyncio
import json
import os
import threading
import unittest
from unittest.mock import patch

import httpx
import requests
from fastapi.testclient import TestClient

from app import create_app
from app.config import Settings


def meow_response(status=200, body=None, content_type="application/json"):
    response = requests.Response()
    response.status_code = status
    response.headers["content-type"] = content_type
    response._content = (
        json.dumps(body if body is not None else {"success": True}).encode()
        if content_type.startswith("application/json")
        else b"upstream unavailable"
    )
    return response


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(miao_nickname="测试/昵称", default_title="默认标题")
        self.client = TestClient(create_app(self.settings))
        self.post = patch("app.meow.requests.post", return_value=meow_response())
        self.upstream = self.post.start()
        self.addCleanup(self.post.stop)
        self.addCleanup(self.client.close)

    def test_health_requires_no_secret_and_sends_no_notification(self):
        client = TestClient(create_app(Settings(webhook_secret="key")))
        with client:
            response = client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.upstream.assert_not_called()

    def test_get_notify_defaults_and_encoded_nickname(self):
        response = self.client.get("/notify", params={"msg": "中文 & 内容"})
        self.assertEqual(response.json(), {"http_status": 200, "resp": {"success": True}})
        endpoint = self.upstream.call_args.args[0]
        self.assertEqual(endpoint, "https://api.chuckfang.com/%E6%B5%8B%E8%AF%95%2F%E6%98%B5%E7%A7%B0")
        self.assertEqual(self.upstream.call_args.kwargs, {
            "json": {"title": "默认标题", "msg": "中文 & 内容"}, "timeout": 10,
        })

    def test_notify_overrides_for_both_methods(self):
        values = {"title": "标题", "msg": "内容", "url": "https://example.com", "nickname": "another"}
        for method in ("get", "post"):
            with self.subTest(method=method):
                response = (
                    self.client.get("/notify", params=values)
                    if method == "get" else self.client.post("/notify", json=values)
                )
                self.assertEqual(response.status_code, 200)
                self.assertTrue(self.upstream.call_args.args[0].endswith("/another"))
                self.assertEqual(self.upstream.call_args.kwargs["json"], {
                    "title": "标题", "msg": "内容", "url": "https://example.com",
                })

    def test_notify_default_jump_url_and_post_defaults(self):
        with TestClient(create_app(Settings(miao_nickname="name", default_jump_url="https://example.com"))) as client:
            for method in ("get", "post"):
                response = client.request(method, "/notify", **(
                    {"params": {"msg": "test"}} if method == "get" else {"json": {"msg": "test"}}
                ))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(self.upstream.call_args.kwargs["json"], {
                    "title": "MeoW", "msg": "test", "url": "https://example.com",
                })

    def test_missing_message_never_pushes(self):
        self.assertEqual(self.client.get("/notify").status_code, 422)
        for body in ({}, {"msg": ""}, {"msg": None}):
            self.assertEqual(self.client.post("/notify", json=body).status_code, 400)
        self.upstream.assert_not_called()

    def test_secret_protects_all_notification_routes(self):
        with TestClient(create_app(Settings(webhook_secret="中文密钥", miao_nickname="name"))) as client:
            for method, path, kwargs in (
                ("GET", "/notify?msg=test", {}),
                ("POST", "/notify", {"json": {"msg": "test"}}),
                ("POST", "/payload_acr", {"json": {}}),
            ):
                for secret in (None, "wrong"):
                    with self.subTest(method=method, path=path, secret=secret):
                        self.upstream.reset_mock()
                        response = client.request(method, path, params={"secret": secret} if secret else None, **kwargs)
                        self.assertEqual(response.status_code, 401)
                        self.upstream.assert_not_called()
                response = client.request(method, path, params={"secret": "中文密钥", "msg": "test"}, **kwargs)
                self.assertEqual(response.status_code, 200)

    def test_acr_full_payload_and_response_contract(self):
        payload = {
            "repository": {"repo_full_name": "team/app", "region": "cn-shanghai"},
            "push_data": {"tag": "v1", "digest": "sha256:abc", "pushed_at": "2026-10-21 12:00:00"},
        }
        response = self.client.post("/payload_acr", json=payload, headers={"User-Agent": "acr-test"})
        self.assertEqual(response.json(), {
            "ok": True, "meow_result": {"http_status": 200, "resp": {"success": True}},
            "user_agent": "acr-test",
        })
        self.assertEqual(self.upstream.call_args.kwargs["json"], {
            "title": "镜像自动构建完成: team/app:v1",
            "msg": "仓库：team/app\n区域：cn-shanghai\nTag：v1\nDigest：sha256:abc\n时间：2026-10-21 12:00:00",
            "url": "team/app",
        })

    def test_acr_namespace_fallback_and_configured_jump(self):
        with TestClient(create_app(Settings(default_jump_url="https://example.com"))) as client:
            response = client.post("/payload_acr", json={"repository": {"namespace": "team", "name": "app"}})
        self.assertEqual(response.status_code, 200)
        sent = self.upstream.call_args.kwargs["json"]
        self.assertEqual(sent["title"], "镜像自动构建完成: team/app:latest")
        self.assertEqual(sent["url"], "https://example.com")

    def test_acr_empty_invalid_and_nonobject_payloads_remain_accepted(self):
        for raw in (b"", b"invalid", b"null", b"[]", b"42", b'"string"',
                    b'{"push_data": null, "repository": null}',
                    b'{"push_data": [], "repository": "invalid"}', b"\xff"):
            with self.subTest(raw=raw):
                response = self.client.post("/payload_acr", content=raw)
                self.assertEqual(response.status_code, 200)
                sent = self.upstream.call_args.kwargs["json"]
                self.assertEqual(sent["msg"], "收到 ACR 推送")
                self.assertNotIn("url", sent)

    def test_old_acr_route_removed_and_openapi_updated(self):
        self.assertEqual(self.client.post("/payload", json={}).status_code, 404)
        paths = self.client.get("/openapi.json").json()["paths"]
        self.assertIn("/payload_acr", paths)
        self.assertNotIn("/payload", paths)
        self.upstream.assert_not_called()

    def test_upstream_non_success_is_preserved(self):
        self.upstream.return_value = meow_response(503, content_type="text/plain")
        result = self.client.post("/payload_acr", json={}).json()
        self.assertTrue(result["ok"])
        self.assertEqual(result["meow_result"], {
            "http_status": 503, "resp": {"text": "upstream unavailable"},
        })

    def test_upstream_timeout_is_reported_without_server_error(self):
        self.upstream.side_effect = requests.Timeout("timed out")
        self.assertEqual(self.client.post("/notify", json={"msg": "test"}).json(), {
            "http_status": 0, "error": "timed out",
        })

    def test_invalid_upstream_json_is_reported(self):
        response = meow_response(content_type="text/plain")
        response.headers["content-type"] = "application/json"
        self.upstream.return_value = response
        self.assertEqual(self.client.get("/notify?msg=test").json()["http_status"], 0)

    def test_env_settings_and_application_instances_are_isolated(self):
        with patch.dict(os.environ, {"MIAO_NICKNAME": "env-name", "DEFAULT_TITLE": "env-title"}):
            app = create_app()
        with TestClient(app) as client:
            self.assertEqual(client.get("/health").json()["nickname"], "env-name")
            client.get("/notify?msg=test")
            self.assertEqual(self.upstream.call_args.kwargs["json"]["title"], "env-title")
        self.assertEqual(self.client.get("/health").json()["nickname"], "测试/昵称")


class ConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_health_responds_while_acr_push_is_waiting(self):
        started, release = threading.Event(), threading.Event()

        def slow_post(*args, **kwargs):
            started.set()
            if not release.wait(timeout=3):
                raise requests.Timeout("test did not release push")
            return meow_response()

        app = create_app(Settings(miao_nickname="test"))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            with patch("app.meow.requests.post", side_effect=slow_post):
                push = asyncio.create_task(client.post("/payload_acr", json={}))
                try:
                    self.assertTrue(await asyncio.to_thread(started.wait, 2))
                    health = await asyncio.wait_for(client.get("/health"), timeout=0.5)
                    self.assertEqual(health.status_code, 200)
                finally:
                    release.set()
                    response = await push
                self.assertEqual(response.json()["meow_result"]["http_status"], 200)


if __name__ == "__main__":
    unittest.main()
