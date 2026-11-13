"""通过现有 SSH 连接卸载重制的本地媒体计算。"""

from __future__ import annotations

import asyncio
import logging
import shlex
from contextlib import nullcontext
from pathlib import Path, PurePosixPath
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from schemas.remake_media import MediaWorkerRequest, MediaScenes, PreparedMedia
from utils.messages import localized_message

logger = logging.getLogger(__name__)
SSH_OPTIONS = ["-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
               "-o", "ConnectTimeout=15", "-o", "ServerAliveInterval=15",
               "-o", "ServerAliveCountMax=3"]


class RemoteMediaError(RuntimeError):
    error_code = "REMAKE_MEDIA_WORKER_FAILED"


class MediaWorkerConnection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    host: str = Field(pattern=r"^(?:[a-zA-Z0-9_][a-zA-Z0-9_.-]*@)?[a-zA-Z0-9][a-zA-Z0-9.-]*$")
    root: str = Field(default="/opt/novelvids-media-worker", pattern=r"^/[a-zA-Z0-9_/-]+$")
    timeout_seconds: int = Field(default=3600, ge=60)
    memory_mb: int = Field(default=2048, ge=256)
    cpu_percent: int = Field(default=100, ge=1)


class RemoteMediaSession:
    def __init__(self, connection: MediaWorkerConnection):
        self.connection = connection
        self.job_id = uuid4()
        self.work = PurePosixPath(connection.root) / "jobs" / self.job_id.hex

    async def __aenter__(self):
        await self._command("create")
        return self

    async def __aexit__(self, *_error):
        try:
            await asyncio.shield(self._command("cleanup", timeout=30))
        except Exception:
            logger.warning("remake_worker_cleanup_failed job=%s", self.job_id.hex)

    async def _run(self, *command: str, timeout: int | None = None) -> bytes:
        process = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout or self.connection.timeout_seconds,
            )
        except BaseException as error:
            if process.returncode is None:
                process.kill()
            await process.communicate()
            if isinstance(error, TimeoutError):
                raise RemoteMediaError(localized_message("重制媒体工作服务器处理超时，请稍后重试")) from None
            raise
        if process.returncode:
            logger.warning("remake_worker_command_failed job=%s returncode=%s detail=%s",
                           self.job_id.hex, process.returncode, stderr.decode(errors="replace")[-2000:])
            raise RemoteMediaError(localized_message("重制媒体工作服务器处理失败，请检查连接或工作进程日志"))
        return stdout

    async def _command(self, action: str, *, extension: str = ".mp4", max_bytes: int = 35_000_000,
                       timeout: int | None = None) -> bytes:
        cfg = self.connection
        request = MediaWorkerRequest(action=action, job_id=self.job_id, extension=extension, max_bytes=max_bytes)
        command = [f"{cfg.root}/.venv/bin/python", "-m", "services.remake.media_worker",
                   "--root", cfg.root, request.model_dump_json()]
        if action in {"prepare", "split", "process"}:
            command = [
                "systemd-run", "--quiet", "--wait", "--pipe", "--collect",
                f"--unit=novelvids-remake-{self.job_id.hex}-{action}",
                f"--working-directory={cfg.root}/current",
                f"--property=MemoryMax={cfg.memory_mb}M", "--property=MemorySwapMax=0",
                f"--property=CPUQuota={cfg.cpu_percent}%", "--property=TasksMax=32",
                "--property=KillMode=control-group", "--property=TimeoutStopSec=10",
                f"--property=RuntimeMaxSec={cfg.timeout_seconds}",
                "--setenv=OPENBLAS_NUM_THREADS=1", "--setenv=OMP_NUM_THREADS=1",
                "flock", "-w", str(cfg.timeout_seconds), f"{cfg.root}/media.lock", *command,
            ]
        shell = f"cd {shlex.quote(cfg.root + '/current')} && {shlex.join(command)}"
        return await self._run("ssh", *SSH_OPTIONS, cfg.host, shell, timeout=timeout)

    async def prepare(self, source: Path, work_dir: Path, *, max_bytes: int) -> Path:
        extension = ".mov" if source.suffix.lower() == ".mov" else ".mp4"
        await self._run("scp", "-q", *SSH_OPTIONS, str(source.resolve()),
                        f"{self.connection.host}:{self.work}/source{extension}")
        prepared = PreparedMedia.model_validate_json(
            await self._command("prepare", extension=extension, max_bytes=max_bytes),
        )
        if prepared.size_bytes > max_bytes:
            raise RemoteMediaError(localized_message("远程处理的视频超过模型输入大小上限"))
        work_dir.mkdir(parents=True, exist_ok=True)
        destination = work_dir / prepared.filename
        await self._run("scp", "-q", *SSH_OPTIONS,
                        f"{self.connection.host}:{self.work}/{prepared.filename}", str(destination.resolve()))
        if not destination.is_file() or destination.stat().st_size != prepared.size_bytes:
            raise RemoteMediaError(localized_message("远程处理的视频传输不完整"))
        return destination

    async def split(self, destination: Path) -> tuple[list[Path], list[float]]:
        result = MediaScenes.model_validate_json(await self._command("split"))
        destination.mkdir(parents=True, exist_ok=True)
        # Copy the directory in one transfer; media bytes stay on disk rather than in JSON/stdout.
        await self._run("scp", "-q", "-r", *SSH_OPTIONS,
                        f"{self.connection.host}:{self.work}/scenes/.", str(destination.resolve()))
        paths = [destination / scene.filename for scene in result.scenes]
        if any(not path.is_file() or path.stat().st_size == 0 for path in paths):
            raise RemoteMediaError(localized_message("远程切分的视频传输不完整"))
        return paths, [scene.duration_seconds for scene in result.scenes]


def media_session():
    from config import settings

    if not settings.REMAKE_MEDIA_SSH_HOST:
        return nullcontext(None)
    return RemoteMediaSession(MediaWorkerConnection(
        host=settings.REMAKE_MEDIA_SSH_HOST, root=settings.REMAKE_MEDIA_WORKER_PATH,
        timeout_seconds=settings.REMAKE_MEDIA_TIMEOUT_SECONDS,
        memory_mb=settings.REMAKE_MEDIA_MEMORY_MB, cpu_percent=settings.REMAKE_MEDIA_CPU_PERCENT,
    ))
