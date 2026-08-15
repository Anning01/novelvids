# 后端镜像：FastAPI + Tortoise ORM（Python 3.12 + uv）
# 构建：docker build -t novelvids-backend .
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app

# 先只复制依赖清单，利用 Docker 层缓存
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
# 只安装运行时依赖，不安装本项目自身（代码在仓库根目录，运行时直接 import）
RUN uv sync --frozen --no-dev --no-install-project

FROM python:3.12-slim AS runtime

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

# 复制虚拟环境与应用代码
COPY --from=builder /app/.venv /app/.venv
COPY . .

# 数据与媒体目录（生产环境通过 docker-compose 挂载卷持久化）
RUN mkdir -p /app/data /app/media

EXPOSE 8000

# 注：SQLite 直接写入挂载卷，故容器以 root 运行以保证写权限；
# 若需加固，可改用命名卷并创建非 root 用户。
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
