"""用已构建的镜像验证真实 Compose 与 HTTP 转发，全程使用模拟 MeoW。

运行：python tests/compose_smoke.py --image harmonyos-msg-push:local
仅创建独立项目的临时容器和网络，结束时自动清理，不拉取或发布镜像。
"""

import argparse
import json
from pathlib import Path
import socket
import subprocess
import tempfile
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener
import uuid

ROOT = Path(__file__).resolve().parents[1]
STUB = """
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'ok')

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({'path': self.path, 'payload': data}).encode())

ThreadingHTTPServer(('0.0.0.0', 8080), Handler).serve_forever()
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="harmonyos-msg-push:local")
    parser.add_argument("--config-only", action="store_true", help="仅检查临时 Compose 配置，不启动容器")
    args = parser.parse_args()
    # 本机探测直连临时容器，避免系统代理拦截 localhost。
    opener = build_opener(ProxyHandler({}))
    project = f"harmonyos-smoke-{uuid.uuid4().hex[:10]}"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    # 仅在手动执行本脚本时生成独立测试配置，不修改实际部署配置。
    configuration = json.loads(subprocess.run(
        ["docker", "compose", "-f", str(ROOT / "docker-compose.yml"), "config", "--format", "json"],
        capture_output=True, text=True, check=True, timeout=15,
    ).stdout)
    configuration.pop("name", None)
    configuration["networks"] = {"default": {}}
    service = configuration["services"]["path-scanner"]
    service.update({
        "image": args.image,
        "container_name": f"{project}-app",
        "ports": [{"target": 12082, "published": str(port), "host_ip": "127.0.0.1", "protocol": "tcp"}],
        "depends_on": {"meow-stub": {"condition": "service_healthy"}},
    })
    service["environment"].update({
        "MIAO_NICKNAME": "compose-test", "MIAO_API_BASE": "http://meow-stub:8080",
        "WEBHOOK_SECRET": "compose-test-secret", "DEFAULT_TITLE": "Compose test",
        "DEFAULT_JUMP_URL": "", "LOG_LEVEL": "INFO",
    })
    configuration["services"]["meow-stub"] = {
        "image": args.image, "command": ["python", "-u", "-c", STUB],
        "healthcheck": {
            "test": ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2).close()"],
            "interval": "1s", "timeout": "3s", "retries": 10,
        },
    }
    with tempfile.TemporaryDirectory(prefix="harmonyos-smoke-") as directory:
        test_file = Path(directory) / "compose.json"
        test_file.write_text(json.dumps(configuration))
        command = ["docker", "compose", "-p", project, "-f", str(test_file)]

        def compose(*arguments, check=True):
            return subprocess.run(command + list(arguments), check=check, timeout=90)

        def request(method, path, body=None, auth=True):
            if auth:
                path += ("&" if "?" in path else "?") + urlencode({"secret": "compose-test-secret"})
            req = Request(f"http://127.0.0.1:{port}{path}", method=method,
                          data=json.dumps(body).encode() if body is not None else None,
                          headers={"Content-Type": "application/json", "User-Agent": "compose-smoke"})
            try:
                with opener.open(req, timeout=15) as response:
                    return response.status, json.load(response)
            except HTTPError as exc:
                with exc:
                    return exc.code, json.load(exc)

        if args.config_only:
            compose("config", "--quiet")
            print("PASS: isolated Compose configuration is valid; no containers started")
            return

        try:
            compose("config", "--quiet")
            compose("up", "-d", "--pull", "never", "--wait", "--wait-timeout", "60")
            status, data = request("GET", "/health", auth=False)
            assert status == 200 and data["nickname"] == "compose-test", (status, data)
            print("PASS: Compose starts application and healthcheck becomes healthy", flush=True)

            for method, path, body in (("GET", "/notify?msg=blocked", None),
                                       ("POST", "/notify", {"msg": "blocked"}),
                                       ("POST", "/payload_acr", {})):
                status, data = request(method, path, body, auth=False)
                assert status == 401, (status, data)
            print("PASS: all notification routes enforce configured secret", flush=True)

            status, data = request("GET", "/notify?" + urlencode({"msg": "中文测试"}))
            assert status == 200 and data["http_status"] == 200, (status, data)
            assert data["resp"] == {"path": "/compose-test", "payload": {"title": "Compose test", "msg": "中文测试"}}, data
            print("PASS: GET notify forwards UTF-8 JSON over real HTTP", flush=True)

            status, data = request("POST", "/notify", {"msg": "post-test", "nickname": "other", "url": "https://example.com"})
            assert status == 200 and data["resp"]["path"] == "/other", (status, data)
            assert data["resp"]["payload"]["url"] == "https://example.com", data
            print("PASS: POST notify forwards nickname and jump URL", flush=True)

            status, data = request("POST", "/payload_acr", {
                "repository": {"repo_full_name": "team/app", "region": "cn-shanghai"},
                "push_data": {"tag": "v1", "digest": "sha256:test", "pushed_at": "2026-10-21"},
            })
            assert status == 200 and data["ok"] and data["user_agent"] == "compose-smoke", (status, data)
            assert data["meow_result"]["resp"]["payload"] == {
                "title": "镜像自动构建完成: team/app:v1", "url": "team/app",
                "msg": "仓库：team/app\n区域：cn-shanghai\nTag：v1\nDigest：sha256:test\n时间：2026-10-21",
            }, data
            print("PASS: /payload_acr formats and forwards ACR webhook", flush=True)

            status, data = request("POST", "/payload_acr", {"repository": None, "push_data": []})
            assert status == 200 and data["meow_result"]["resp"]["payload"]["msg"] == "收到 ACR 推送", (status, data)
            print("PASS: malformed ACR fields do not crash application", flush=True)

            status, data = request("POST", "/payload", {})
            assert status == 404, (status, data)
            print("PASS: previous webhook URL is removed", flush=True)
        except BaseException:
            compose("logs", "--no-color", check=False)
            raise
        finally:
            compose("down", "--volumes", check=False)


if __name__ == "__main__":
    main()
