# HarmonyOS 消息推送

基于 FastAPI 接收阿里云 ACR Webhook 或手动通知，并通过 MeoW 推送消息。

项目说明、接口、部署步骤和 Agent 续接记忆统一保存在 [docs/](docs/README.md)。

- [项目概览与源码索引](docs/README.md)
- [接口说明](docs/接口说明.md)：ACR 地址为 `POST /payload_acr`
- [构建与部署](docs/部署指南.md)：Dockerfile 构建，Docker Compose 部署
- [开发记忆与约定](docs/开发记忆.md)
- [开发进度与验证记录](docs/开发进度.md)
