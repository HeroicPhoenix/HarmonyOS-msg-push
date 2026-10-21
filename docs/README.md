# 项目概览与源码索引

更新日期：2026-10-21。

这是一个无状态的 FastAPI 消息转发服务：接收阿里云 ACR Webhook，将仓库、区域、标签、摘要和推送时间格式化后，以 JSON POST 发送至 MeoW。也提供 GET/POST 手动通知及健康检查。

当前代码不直接调用 HarmonyOS SDK，不拉取镜像、不执行部署，没有数据库、持久化文件、任务队列或自动重试。手机端实际收件依赖 MeoW 服务与账号配置。

实际部署链路为：外部 HTTPS 请求 → 公网 Nginx（HTTPS 终止）→ 同机 FRPS → NAS 侧 FRPC → NAS 应用容器（HTTP 12082）。应用向 MeoW 发起出站请求。具体连接要求见 [NAS、FRP 与公网 HTTPS 部署说明](部署指南.md#nasfrp-与公网-https-链路)。

## 文档导航

| 文档 | 用途 |
| --- | --- |
| [接口说明](接口说明.md) | 请求参数、响应、ACR 示例、异常与兼容约定 |
| [部署指南](部署指南.md) | 配置、独立构建、Compose 部署、升级与回滚 |
| [开发记忆](开发记忆.md) | 需求约束、设计决策、后续 Agent 工作入口 |
| [开发进度](开发进度.md) | 已完成改动、实际验证结果与待核验事项 |

根目录只保留 README 导航和 AGENTS 工作入口；详细项目文档统一放在本目录。

## 源码索引

```text
main.py                    main:app 兼容入口及开发启动
app/
  __init__.py              create_app，日志初始化、配置注入与路由注册
  config.py                Settings，集中读取环境变量
  dependencies.py          获取当前应用配置及可选 secret 校验
  meow.py                  requests POST、超时、上游结果封装
  acr.py                   ACR 报文解析及通知格式化，不访问网络
  routes/
    health.py              GET /health
    notify.py              GET /notify、POST /notify
    acr.py                 POST /payload_acr
Dockerfile                 基础镜像、依赖与运行代码打包
requirements.txt           Python 3.10 容器验证后的完整依赖版本
requirements-dev.txt       运行依赖与测试专用 httpx
.dockerignore              构建上下文排除规则
docker-compose.yml        镜像引用、启动、端口、环境、健康检查、重启
tests/
  test_api.py             mock 外部推送的接口与并发回归
  compose_smoke.py         实际容器及模拟 MeoW 的 HTTP 转发验证
```

## 调用链

- 手动通知：`main:app → notify 路由 → verify_secret → push_meow → MeoW`。
- ACR：`main:app → acr 路由 → verify_secret → format_acr_notification → 线程池 push_meow → MeoW`。
- 健康检查：`health 路由 → 当前应用配置`，不调用 MeoW。

配置在创建应用时读取，并保存在 `app.state.settings`。`create_app(Settings(...))` 可以建立互相隔离的测试应用。同步手动通知路由由 FastAPI 在线程池执行，ACR 异步路由读取请求体后显式将同步推送放入线程池。

## 配置

| 环境变量 | 默认值 | 用途 |
| --- | --- | --- |
| `MIAO_NICKNAME` | 空 | 默认 MeoW 昵称，实际推送前需填写有效账号 |
| `MIAO_API_BASE` | `https://api.chuckfang.com` | MeoW API 基地址 |
| `DEFAULT_TITLE` | `MeoW` | 手动通知默认标题 |
| `WEBHOOK_SECRET` | 空 | 非空时校验通知接口的 `secret` 查询参数 |
| `DEFAULT_JUMP_URL` | 空 | 默认点击跳转地址 |
| `LOG_LEVEL` | `INFO` | Python 日志级别，未知值回退 INFO |

部署配置值直接维护在 `docker-compose.yml`：`image` 指定 ACR 镜像，`ports` 指定宿主机映射，`environment` 填写上表的应用配置。项目不依赖额外环境文件或配置模板。Python 直接启动时由 shell 提供环境变量；修改 Compose 配置后用 `up -d` 重新创建容器。

日常工作流：修改源码 → 用户推送 Git → 阿里云 ACR 根据 Dockerfile 自动构建 → 部署主机通过 Compose 拉取并运行。后续代码修改默认做 Python 检查与 Compose 配置校验，不主动打包 Docker 或启动容器。
