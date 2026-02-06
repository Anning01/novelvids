.PHONY: help install install-dev add add-dev dev start stop clean test test-client pytest format lint db-init db-migrate db-upgrade

# 默认目标
help:
	@echo "Server - 可用命令:"
	@echo ""
	@echo "  install     - 安装依赖"
	@echo "  install-dev - 安装开发依赖"
	@echo "  add         - 添加依赖 (用法: make add pkg=package_name)"
	@echo "  add-dev     - 添加开发依赖 (用法: make add-dev pkg=package_name)"
	@echo ""
	@echo "  dev         - 开发模式启动"
	@echo "  start       - 生产模式启动"
	@echo "  stop        - 停止服务"
	@echo ""
	@echo "  test        - 运行API测试"
	@echo "  pytest      - 运行pytest测试"
	@echo "  format      - 格式化代码"
	@echo "  lint        - 代码检查"
	@echo ""
	@echo "  clean       - 清理临时文件"
	@echo ""
	@echo "  db-init     - 初始化数据库"
	@echo "  db-migrate  - 运行数据库迁移"
	@echo "  db-upgrade  - 应用迁移到数据库"

# 安装依赖
install:
	@echo "安装Python依赖..."
	@if command -v uv >/dev/null 2>&1; then \
		echo "使用uv安装依赖..."; \
		uv sync; \
	else \
		echo "uv未安装，使用pip安装依赖..."; \
		pip install -r requirements.txt; \
	fi

# 安装开发依赖
install-dev:
	@echo "安装开发依赖..."
	@if command -v uv >/dev/null 2>&1; then \
		echo "使用uv安装开发依赖..."; \
		uv sync --dev; \
	else \
		echo "uv未安装，使用pip安装开发依赖..."; \
		pip install -r requirements.txt; \
		pip install pytest pytest-asyncio httpx black isort flake8 mypy pre-commit aiohttp requests; \
	fi

# 添加依赖
add:
	@echo "添加新依赖..."
	@if [ -z "$(pkg)" ]; then \
		echo "用法: make add pkg=package_name"; \
		exit 1; \
	fi
	@if command -v uv >/dev/null 2>&1; then \
		uv add $(pkg); \
	else \
		pip install $(pkg); \
		pip freeze > requirements.txt; \
	fi

# 添加开发依赖
add-dev:
	@echo "添加开发依赖..."
	@if [ -z "$(pkg)" ]; then \
		echo "用法: make add-dev pkg=package_name"; \
		exit 1; \
	fi
	@if command -v uv >/dev/null 2>&1; then \
		uv add --dev $(pkg); \
	else \
		pip install $(pkg); \
		pip freeze > requirements.txt; \
	fi

# 开发模式启动
dev:
	@echo "启动开发服务器..."
	@HOST=$$(grep -E '^HOST=' cut -d '=' -f2); \
	PORT=$$(grep -E '^PORT=' cut -d '=' -f2); \
	if [ -z "$$HOST" ]; then HOST=0.0.0.0; fi; \
	if [ -z "$$PORT" ]; then PORT=8000; fi; \
	if command -v uv >/dev/null 2>&1; then \
		uv run uvicorn main:app --host $$HOST --port $$PORT --reload; \
	else \
		uvicorn main:app --host $$HOST --port $$PORT --reload; \
	fi

# 生产模式启动
start:
	@echo "启动生产服务器..."
	@if [ ! -f .env ]; then \
		echo "创建.env文件..."; \
		cp .env.example .env; \
		echo "请编辑.env文件后重新运行"; \
		exit 1; \
	fi
	@HOST=$$(grep -E '^HOST=' .env | cut -d '=' -f2); \
	PORT=$$(grep -E '^PORT=' .env | cut -d '=' -f2); \
	if [ -z "$$HOST" ]; then HOST=0.0.0.0; fi; \
	if [ -z "$$PORT" ]; then PORT=8000; fi; \
	if command -v uv >/dev/null 2>&1; then \
		uv run uvicorn main:app --host $$HOST --port $$PORT --log-config logging.yaml; \
	else \
		uvicorn main:app --host $$HOST --port $$PORT --log-config logging.yaml; \
	fi

# 停止服务
stop:
	@echo "停止服务..."
	pkill -f "uvicorn main:app" || true

# 清理临时文件
clean:
	@echo "清理临时文件..."
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} + || true

# 运行pytest测试
test:
	@echo "运行pytest测试..."
	@if command -v uv >/dev/null 2>&1; then \
		uv run pytest; \
	else \
		pytest; \
	fi

# 运行pytest测试
pytest:
	@echo "运行pytest测试..."
	@if command -v uv >/dev/null 2>&1; then \
		uv run pytest; \
	else \
		pytest; \
	fi

# 代码格式化
format:
	@echo "格式化代码..."
	@if command -v uv >/dev/null 2>&1; then \
		uv run black . --exclude='.venv|migrations' && uv run isort . --skip=.venv --skip=migrations; \
	else \
		black . --exclude='.venv|migrations' && isort . --skip=.venv --skip=migrations; \
	fi

# 代码检查
lint:
	@echo "检查代码..."
	@if command -v uv >/dev/null 2>&1; then \
		uv run flake8 . --exclude=.venv,migrations && uv run mypy . --exclude=.venv; \
	else \
		flake8 . --exclude=.venv,migrations && mypy . --exclude=.venv; \
	fi

# 初始化数据库
db-init:
	@echo "初始化数据库迁移..."
	@if command -v uv >/dev/null 2>&1; then \
		uv run aerich init -t main.tortoise_config && uv run aerich init-db; \
	else \
		aerich init -t main.tortoise_config && aerich init-db; \
	fi

# 运行数据库迁移
db-migrate:
	@echo "生成数据库迁移文件..."
	@if command -v uv >/dev/null 2>&1; then \
		uv run aerich migrate; \
	else \
		aerich migrate; \
	fi

# 应用迁移到数据库
db-upgrade:
	@echo "应用迁移到数据库..."
	@if command -v uv >/dev/null 2>&1; then \
		uv run aerich upgrade; \
	else \
		aerich upgrade; \
	fi

# 快速设置（首次运行）
setup: install
	@echo "快速设置..."
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "已创建.env文件，请根据需要修改配置"; \
	fi
	@echo "设置完成！"
	@echo "运行 'make dev' 启动开发服务器"
	@echo "或运行 'make test' 运行测试"
