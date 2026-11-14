"""Validate and store completed external decomposition without scheduling model calls."""
import asyncio
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from exceptions.remake import RemakeError
from models.remake_source import RemakeSource
from schemas.work_package import Shot
from services.remake.media import RemakeMediaValidator


def validate_shot_source(shot: Shot, source_duration: float | None):
    if source_duration is None:
        if shot.source_range is not None:
            raise ValueError('普通剧本镜头不能携带重制来源时间段')
    elif shot.source_range is None or shot.source_range.end > source_duration:
        raise ValueError('重制镜头必须提供原视频范围内的来源时间段')


async def validate_source(files, manifest, board):
    if manifest.remake_source is None:
        for shot in board.shots:
            validate_shot_source(shot, None)
        return None
    if not board.shots:
        raise ValueError('重制导入需要已完成的拆解镜头')
    filename = manifest.remake_source.path
    data = files.read(filename)

    def probe():
        # Probe exactly the bounded bytes that will be archived, not a mutable source path.
        with TemporaryDirectory(prefix='mcp-remake-') as directory:
            path = Path(directory) / Path(filename).name
            path.write_bytes(data)
            return RemakeMediaValidator().validate_path(path, original_filename=path.name)

    try:
        media = await asyncio.to_thread(probe)
    except RemakeError as error:
        raise ValueError(error.message) from error
    for shot in board.shots:
        validate_shot_source(shot, media.duration_seconds)
    return media


async def persist_source(project, chapter, media, url):
    return await RemakeSource.create(
        novel_id=project.id, chapter_id=chapter.id, episode_number=chapter.number,
        source_kind='upload', storage_provider='local', object_key=url.removeprefix('/media/'),
        media_status='completed', team_id=project.team_id, created_by=project.created_by,
        **asdict(media),
    )


def shot_metadata(source, shot):
    validate_shot_source(shot, source.duration_seconds if source else None)
    if source is None:
        return {}
    return {'analysis_source': 'work_package', 'remake_source_id': source.id,
            'source_file': '/media/' + source.object_key,
            'source_range': shot.source_range.model_dump()}
