# 保留原有 ACR 基础镜像；需要时可用 --build-arg BASE_IMAGE=python:3.10-slim 替换。
ARG BASE_IMAGE=crpi-v2fmzydhnzmlpzjc.cn-shanghai.personal.cr.aliyuncs.com/machenkai/python:3.10-slim
FROM ${BASE_IMAGE}

WORKDIR /app

# 依赖先单独复制，源码变化时可复用依赖安装层。
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    -i https://mirrors.aliyun.com/pypi/simple/

COPY main.py ./
COPY app/ ./app/

# 此处只构建镜像；应用命令、端口、环境和健康检查由 Compose 指定。
