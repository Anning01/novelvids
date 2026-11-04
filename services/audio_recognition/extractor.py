"""从剪辑草稿 (EditDocument) 提取对齐时间线的主轨音频供 ASR 识别。"""
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from fastapi import HTTPException

from config import settings
from schemas.video_edit import EditDocument, VideoClip
from services.video_editor.assets import editor_storage
from services.video_editor.render import tempo
from services.video_editor.sources import EditSources, source_key
from utils.messages import localized_message as msg


async def _run_command(args: list[str], cwd: Path) -> None:
    process = await asyncio.create_subprocess_exec(
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        await asyncio.wait_for(process.communicate(), timeout=180)
    except BaseException:
        if process.returncode is None:
            process.kill()
            await process.wait()
        raise
    if process.returncode != 0:
        raise RuntimeError("FFmpeg 处理音频失败，请检查素材")


async def extract_timeline_audio(
    document: EditDocument,
    chapter_id: int,
    novel_id: int,
) -> tuple[bytes, float]:
    """提取时间线主视频轨的原声音频，按时间线绝对位置对齐。

    返回: (audio_bytes, duration_seconds)
    格式: 16000Hz 16-bit 单声道 MP3。
    """
    videos: list[VideoClip] = sorted(
        [c for c in document.clips if c.type == "video"],
        key=lambda c: c.start,
    )
    if not videos:
        raise HTTPException(422, msg("时间线上没有可识别的视频素材"))

    timeline_duration = max((c.start + c.duration for c in videos), default=0.0)
    if timeline_duration <= 0.05:
        raise HTTPException(422, msg("时间线视频时长过短，无法识别"))

    resolver = EditSources(novel_id, chapter_id)
    # Probe actual audio tracks and validate only main video sources.
    resolved = await resolver.validate(document.model_copy(update={"clips": videos}), freeze=True)
    sources = {item["key"]: item for item in resolved}

    root = Path(settings.CHAPTER_EXPORT_PATH).resolve()
    root.mkdir(parents=True, exist_ok=True)

    with TemporaryDirectory(dir=root, prefix=".asr-extract-") as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        segments: list[tuple[VideoClip | None, float]] = []
        cursor = 0.0

        for clip in videos:
            gap = clip.start - cursor
            if gap > 0.04:
                segments.append((None, gap))
            segments.append((clip, clip.duration))
            cursor = clip.start + clip.duration

        if timeline_duration - cursor > 0.04:
            segments.append((None, timeline_duration - cursor))

        segment_paths: list[Path] = []

        for index, (clip, dur) in enumerate(segments):
            seg_path = temp_dir / f"seg_{index}.wav"
            if clip is None:
                # 静音填充
                cmd = [
                    "ffmpeg", "-hide_banner", "-v", "error", "-y", "-nostdin",
                    "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
                    "-t", f"{dur:.6f}",
                    "-c:a", "pcm_s16le", "-ar", "16000", "-ac", "1",
                    str(seg_path),
                ]
                await _run_command(cmd, cwd=temp_dir)
            else:
                source_item = sources[source_key(clip.source)]
                has_audio = bool(source_item.get("has_audio", True))
                speed = clip.playback_rate
                source_dur = clip.source_end - clip.trim_in

                async with editor_storage.materialize(source_item["ref"]) as raw_path:
                    if not has_audio:
                        cmd = [
                            "ffmpeg", "-hide_banner", "-v", "error", "-y", "-nostdin",
                            "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
                            "-t", f"{dur:.6f}",
                            "-c:a", "pcm_s16le", "-ar", "16000", "-ac", "1",
                            str(seg_path),
                        ]
                    else:
                        filter_chain = (
                            f"atrim=duration={source_dur:.6f},asetpts=PTS-STARTPTS,"
                            f"{tempo(speed)},volume={clip.volume},aresample=16000,aformat=channel_layouts=mono,"
                            f"apad=whole_dur={dur:.6f},atrim=duration={dur:.6f}"
                        )
                        cmd = [
                            "ffmpeg", "-hide_banner", "-v", "error", "-y", "-nostdin",
                            "-ss", f"{clip.trim_in:.6f}",
                            "-i", str(raw_path),
                            "-vn",
                            "-filter_complex", f"[0:a]{filter_chain}[a]",
                            "-map", "[a]",
                            "-t", f"{dur:.6f}",
                            "-c:a", "pcm_s16le", "-ar", "16000", "-ac", "1",
                            str(seg_path),
                        ]
                    await _run_command(cmd, cwd=temp_dir)

            segment_paths.append(seg_path)

        # 合并所有切片并导出为 MP3
        concat_file = temp_dir / "concat.txt"
        concat_file.write_text("\n".join(f"file '{p.name}'" for p in segment_paths), encoding="utf-8")

        output_mp3 = temp_dir / "timeline.mp3"
        merge_cmd = [
            "ffmpeg", "-hide_banner", "-v", "error", "-y", "-nostdin",
            "-f", "concat", "-safe", "1", "-i", str(concat_file),
            "-c:a", "libmp3lame", "-b:a", "64k", "-ar", "16000", "-ac", "1",
            str(output_mp3),
        ]
        await _run_command(merge_cmd, cwd=temp_dir)

        audio_bytes = output_mp3.read_bytes()
        return audio_bytes, timeline_duration
