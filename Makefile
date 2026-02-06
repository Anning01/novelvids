.PHONY: help install install-dev add add-dev dev start stop clean test format lint

# 默认目标
help:
	@echo "Server - 可用命令 (Powered by uv):"
	@echo ""
	@echo "  install     - 安装依赖"
	@echo "  install-dev - 安装开发依赖"
	@echo "  add         - 添加依赖 (用法: make add pkg=package_name)"
	@echo "  add-dev     - 添加开发依赖 (用法: make add-dev pkg=package_name)"
	@echo ""
	@echo "  dev         - 开发模式启动 (默认 0.0.0.0:8000)"
	@echo "  start       - 生产模式启动"
	@echo "  stop        - 停止服务"
	@echo ""
	@echo "  test        - 运行测试"
	@echo "  format      - 格式化代码"
	@echo "  lint        - 代码检查"
	@echo ""
	@echo "  clean       - 清理临时文件"
	@echo ""


# --- 依赖管理 ---
install:
	@echo "安装依赖 (uv)..."
	uv sync

install-dev:
	@echo "安装开发依赖 (uv)..."
	uv sync --dev

add:
	@if [ -z "$(pkg)" ]; then echo "用法: make add pkg=package_name"; exit 1; fi
	uv add $(pkg)

add-dev:
	@if [ -z "$(pkg)" ]; then echo "用法: make add-dev pkg=package_name"; exit 1; fi
	uv add --dev $(pkg)

# --- 服务运行 ---
# 允许通过环境变量覆盖: make dev HOST=127.0.0.1 PORT=8080
HOST ?= 0.0.0.0
PORT ?= 8000

dev:
	@echo "启动开发服务器..."
	uv run uvicorn main:app --host $(HOST) --port $(PORT) --reload

start:
	@echo "启动生产服务器..."
	uv run uvicorn main:app --host $(HOST) --port $(PORT) --log-config logging.yaml

stop:
	@echo "停止服务..."
	pkill -f "uvicorn main:app" || true

# --- 代码质量 ---
test:
	@echo "运行测试..."
	uv run pytest

format:
	@echo "格式化代码..."
	uv run ruff format .
	uv run ruff check --fix --select I .

lint:
	@echo "检查代码..."
	uv run flake8 . --exclude=.venv,migrations
	uv run mypy . --exclude=.venv

clean:
	@echo "清理临时文件..."
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} + || true

