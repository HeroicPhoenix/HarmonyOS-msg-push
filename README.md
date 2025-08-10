# ACR Webhook → MeoW Notifier

本项目是一个基于 **FastAPI** 的 Web 服务，用于接收 **阿里云容器镜像服务（ACR）** 的 Webhook 推送，并将推送信息格式化后发送到 **MeoW 消息推送平台**。

支持三种使用方式：
1. **健康检查接口**
2. **手动触发通知**
3. **自动接收 ACR Webhook 并转发到 MeoW**

---

## 🚀 功能特点
- 接收 **ACR 镜像推送** webhook 并转发到 MeoW
- 支持 **手动调用通知**（GET/POST）
- 可选 **secret 校验**，防止未授权调用
- 通过 **环境变量** 灵活配置
- 返回 JSON 格式结果，便于调试和集成

---

## 📦 安装与运行

### 1. 克隆项目
```bash
git clone https://github.com/HeroicPhoenix/holiday
```

### 2. 安装依赖
```bash
pip install -r requirements.txt
```

### 3. 配置环境变量
在 `.env` 或系统环境变量中配置以下内容：
| 变量名 | 说明 | 是否必填 | 默认值 |
| ------ | ---- | -------- | ------ |
| `MIAO_NICKNAME` | MeoW 昵称（必须先在 MeoW 平台上存在） | ✅ | 无 |
| `MIAO_API_BASE` | MeoW API 基地址 | ❌ | `https://api.chuckfang.com` |
| `DEFAULT_TITLE` | 默认通知标题 | ❌ | `MeoW` |
| `WEBHOOK_SECRET` | Webhook 校验密钥 | ❌ | 空 |
| `DEFAULT_JUMP_URL` | 点击通知跳转的链接 | ❌ | 空 |

### 4. 启动服务
```bash
uvicorn app:app --host 0.0.0.0 --port 12082 --reload
```

---

## 📡 API 说明

### 1. 健康检查
```
GET /health
```
返回服务运行状态及当前配置。

---

### 2. 手动触发通知（GET）
```
GET /notify
```
参数：
| 参数 | 说明 | 必填 |
| ---- | ---- | ---- |
| `title` | 通知标题 | 否 |
| `msg` | 通知内容 | ✅ |
| `url` | 点击跳转链接 | 否 |
| `nickname` | MeoW 昵称 | 否 |
| `secret` | 如果设置了 `WEBHOOK_SECRET`，则必填 | 否 |

示例：
```bash
curl "http://localhost:12082/notify?msg=测试消息&title=ACR测试"
```

---

### 3. 手动触发通知（POST）
```
POST /notify
Content-Type: application/json
```
Body 示例：
```json
{
  "title": "测试标题",
  "msg": "测试内容",
  "url": "https://example.com"
}
```

---

### 4. 接收 ACR Webhook
```
POST /payload
```
此接口用于接收阿里云 ACR 推送的 JSON 数据，并转发到 MeoW。

在阿里云 ACR 控制台中配置 Webhook URL，例如：
```
https://your-server.com/payload?secret=你的密钥
```

---

## 🐾 MeoW 推送示例
收到推送后，你的 MeoW 将显示类似：
```
镜像推送: myrepo/app:latest
仓库：myrepo/app
区域：cn-shanghai
Tag：latest
Digest：sha256:xxxxxx
时间：2025-08-10 12:34:56
```

---

## 📄 许可证
MIT License
