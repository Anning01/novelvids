import asyncio
import os
import time
import logging
from pathlib import Path
from typing import Generator, List, Dict, Any
import pytest
from tortoise import Tortoise
from tortoise.contrib.test import finalizer, initializer
from httpx import AsyncClient, ASGITransport
from main import app
from pyinstrument import Profiler

# Configure logging to capture SQL
logging.basicConfig(level=logging.INFO)
# 测试时抑制噪音日志，只保留 CRITICAL
for _logger_name in ("httpx", "httpcore", "tortoise", "tortoise.db_client", "services.ai_task_executor"):
    _lg = logging.getLogger(_logger_name)
    _lg.setLevel(logging.CRITICAL)
    _lg.propagate = False


# --- 美化测试结果输出 ---

def pytest_runtest_logreport(report):
    """每个测试阶段结束后打印美化结果。"""
    if report.when != "call":
        return

    nodeid = report.nodeid
    # 提取文件短名 + 测试函数名
    parts = nodeid.split("::")
    file_part = parts[0].split("/")[-1].replace(".py", "")
    test_name = parts[-1] if len(parts) > 1 else nodeid

    duration = f"{report.duration:.3f}s"

    if report.passed:
        print(f"\n  \033[32m PASS \033[0m {file_part} > {test_name}  ({duration})")
    elif report.failed:
        short_err = ""
        if report.longrepr:
            lines = str(report.longrepr).strip().splitlines()
            short_err = lines[-1] if lines else ""
        print(f"\n  \033[31m FAIL \033[0m {file_part} > {test_name}  ({duration})")
        if short_err:
            print(f"         {short_err}")
    elif report.skipped:
        print(f"\n  \033[33m SKIP \033[0m {file_part} > {test_name}")


def _load_test_env() -> dict:
    """从 test/.test.env 加载测试配置。"""
    env_path = Path(__file__).parent / ".test.env"
    config = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, value = line.partition("=")
            config[key.strip()] = value.strip()
    return config


TEST_ENV = _load_test_env()


@pytest.fixture(scope="session")
def test_env() -> dict:
    """返回 .test.env 配置字典。"""
    return TEST_ENV

# Removed explicit event_loop fixture to rely on pytest-asyncio's auto loop management
# consistent with asyncio_default_fixture_loop_scope="session" in pyproject.toml

@pytest.fixture(scope="session", autouse=True)
async def initialize_db():
    """Initialize DB for the test session."""
    # Use in-memory SQLite
    db_url = "sqlite://:memory:"

    # Initialize Tortoise
    # We need to discover models. Based on models/__init__.py logic or explicit list.
    # The main.py uses [f"models.{module}" for module in __import__("models").__all__]
    # We replicate similar logic or hardcode common ones if imports are tricky in tests.
    # Let's try to load dynamically as the app does.
    import models
    model_modules = [f"models.{module}" for module in models.__all__]

    await Tortoise.init(
        db_url=db_url,
        modules={"models": model_modules},
        timezone="Asia/Shanghai"
    )
    await Tortoise.generate_schemas()

    yield

    await Tortoise.close_connections()

@pytest.fixture(scope="function", autouse=True)
async def clear_db():
    """Clear data between tests but keep schema."""
    # Manual cleanup for core models we use in tests
    from models.novel import Novel
    from models.chapter import Chapter
    from models.asset import Asset
    from models.scene import Scene
    from models.ai_task import AiTask
    from models.config import AiModelConfig
    from models.video import Video

    await Video.all().delete()
    await AiTask.all().delete()
    await Scene.all().delete()
    await Chapter.all().delete()
    await Asset.all().delete()
    await Novel.all().delete()
    await AiModelConfig.all().delete()


@pytest.fixture(scope="module")
async def client() -> AsyncClient:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c

# --- Performance & SQL Profiling Fixtures ---

class SQLQueryRecorder(logging.Handler):
    def __init__(self):
        super().__init__()
        self.queries: List[Dict[str, Any]] = []

    def emit(self, record):
        # Tortoise logs SQL at DEBUG level in tortoise.db_client
        # Format usually: "sql" or similar.
        # Actually Tortoise logs via `tortoise.db_client`.
        # We capture the message.
        if hasattr(record, 'sql'):
             self.queries.append({
                'sql': record.sql,
                'time': getattr(record, 'duration', 0), # Some drivers might add duration
                'timestamp': time.time()
            })
        else:
            # Fallback for standard parsing if custom attributes aren't present
            # Tortoise standard log message: query params
            self.queries.append({
                'msg': record.getMessage(),
                'timestamp': time.time()
            })

@pytest.fixture
async def sql_profiler():
    """
    Fixture to capture SQL queries.
    Usage:
        async with sql_profiler as p:
            await do_something()
        print(p.queries)
    """

    # We need to enable DEBUG logging for tortoise.db_client to see SQL
    logger = logging.getLogger("tortoise.db_client")
    original_level = logger.level
    logger.setLevel(logging.DEBUG)

    recorder = SQLQueryRecorder()
    logger.addHandler(recorder)

    class ProfilerContext:
        def __init__(self):
            self.recorder = recorder
            self.start_time = 0
            self.end_time = 0

        @property
        def queries(self):
            return self.recorder.queries

        @property
        def query_count(self):
            return len(self.recorder.queries)

        @property
        def duration(self):
            return self.end_time - self.start_time

        async def __aenter__(self):
            self.recorder.queries = []
            self.start_time = time.time()
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            self.end_time = time.time()
            # Restore logger
            logger.removeHandler(recorder)
            logger.setLevel(original_level)

    return ProfilerContext()

@pytest.fixture
async def performance_profiler():
    """
    Fixture using pyinstrument to profile code execution.
    Usage:
        async with performance_profiler as p:
            await code()
        p.print()
    """
    profiler = Profiler()

    class InstrumentContext:
        async def __aenter__(self):
            profiler.start()
            return profiler

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            profiler.stop()
            # Auto print or save? Let user decide in test or just print to stdout
            # print(profiler.output_text(unicode=True, color=True))

    return InstrumentContext()
