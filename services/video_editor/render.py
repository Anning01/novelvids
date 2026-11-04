"""Bounded local rendering from validated edit objects, never caller filter strings."""
import asyncio
import os
import subprocess
import unicodedata
from pathlib import Path
from tempfile import TemporaryDirectory
from config import settings
from schemas.video_edit import EditDocument
from services.video_editor.sources import source_key
from services.video_enhancement.media import inspect_media
from utils.messages import localized_message as msg


def wrap_subtitle(text: str, width: int, font_size: float) -> str:
    limit = width * .88 / font_size
    lines, line, used = [], '', 0.0
    for char in text.replace('\r', ''):
        weight = 1 if unicodedata.east_asian_width(char) in {'W', 'F'} else .55
        if char == '\n' or used + weight > limit:
            lines.append(line)
            line, used = '', 0
            if char == '\n':
                continue
        if ord(char) >= 32 or char == '\t':
            line += char
            used += weight
    lines.append(line)
    return '\n'.join(lines)


def subtitle_font() -> Path:
    result = subprocess.run(['fc-match', '-f', '%{file}', 'sans-serif:lang=zh-cn'],
                            capture_output=True, check=True, timeout=10)
    path = Path(result.stdout.decode().strip())
    if not path.is_file():
        raise ValueError(msg('服务器缺少可用的字幕字体'))
    return path


def filter_path(path: Path) -> str:
    return str(path).replace('\\', '\\\\').replace(':', '\\:').replace("'", "'\\''")


def tempo(speed):
    parts = []
    while speed < .5:
        parts.append('atempo=0.5'); speed /= .5
    while speed > 2:
        parts.append('atempo=2'); speed /= 2
    return ','.join([*parts, f'atempo={speed:.8f}'])


class EditRenderer:
    def __init__(self, *, cancelled, progress):
        self.cancelled, self.progress = cancelled, progress
        self.process = None

    async def command(self, args, *, cwd):
        if await self.cancelled():
            raise asyncio.CancelledError
        process = await asyncio.create_subprocess_exec('ffmpeg', '-hide_banner', '-v', 'error',
            '-nostdin', '-y', '-xerror', '-filter_complex_threads', '1', '-filter_threads', '1', *args,
            cwd=cwd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        self.process = process
        communication = asyncio.create_task(process.communicate())
        try:
            while not communication.done():
                if await self.cancelled():
                    raise asyncio.CancelledError
                await asyncio.wait({communication}, timeout=.5)
            _, stderr = await communication
            if process.returncode:
                # Do not send paths, subtitles or source-specific FFmpeg output into public errors/logs.
                raise ValueError(msg('成片渲染失败，请检查素材是否可解码及服务器字体'))
        finally:
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), 5)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
            await asyncio.gather(communication, return_exceptions=True)
            self.process = None

    @staticmethod
    def encoding(document, audio_codec='aac'):
        return ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p',
                '-threads', '2', '-r', str(document.fps), '-c:a', audio_codec, '-ar', '48000', '-ac', '2',
                '-movflags', '+faststart']

    async def segment(self, clip, document, source, target, directory):
        width, height, fps = document.width, document.height, document.fps
        if clip is None:
            duration = source
            await self.command(['-f', 'lavfi', '-i', f'color=c=black:s={width}x{height}:r={fps}',
                '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo', '-t', str(duration),
                *self.encoding(document, 'pcm_s16le'), str(target)], cwd=directory)
            return
        path, info = source
        duration = clip.duration
        sw, sh = max(2, round(width * clip.scale / 2) * 2), max(2, round(height * clip.scale / 2) * 2)
        mode = 'decrease' if clip.fit == 'contain' else 'increase'
        # Normalize each clip before concatenating: only one video decoder/encoder is active.
        video = (f'trim=duration={duration * clip.speed:.8f},setpts=(PTS-STARTPTS)/{clip.speed},'
                 f'scale={width}:{height}:force_original_aspect_ratio={mode}:force_divisible_by=2,'
                 f"crop=w='min(iw,{width})':h='min(ih,{height})',"
                 f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black')
        if clip.scale != 1:
            # Preview transforms the fitted viewport, including its padding, before cropping.
            video += (f",scale={sw}:{sh},crop=w='min(iw,{width})':h='min(ih,{height})',"
                      f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black')
        video += f',setsar=1,fps={fps}'
        args = ['-ss', str(clip.trim_in), '-threads', '1', '-i', str(path)]
        audio_index = 0
        if not info.get('has_audio'):
            args += ['-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo']
            audio_index = 1
        audio = (f'atrim=duration={duration * clip.speed:.8f},asetpts=PTS-STARTPTS,'
                 f'{tempo(clip.speed)},volume={clip.volume},aresample=48000')
        args += ['-filter_complex', f'[0:v]{video}[v];[{audio_index}:a]{audio}[a]',
                 '-map', '[v]', '-map', '[a]', '-t', f'{duration:.8f}',
                 *self.encoding(document, 'pcm_s16le'), str(target)]
        await self.command(args, cwd=directory)

    async def render(self, document: EditDocument, sources: dict, directory: Path) -> Path:
        duration = max((c.start + c.duration for c in document.clips), default=0)
        if not duration:
            raise ValueError(msg('时间线没有可导出的片段'))
        videos = sorted((c for c in document.clips if c.type == 'video'), key=lambda c: c.start)
        segments, cursor = [], 0.0
        for clip in videos:
            if clip.start - cursor > .5 / document.fps:
                segments.append((None, clip.start - cursor))
            segments.append((clip, sources[source_key(clip.source)]))
            cursor = clip.start + clip.duration
        if duration - cursor > .5 / document.fps:
            segments.append((None, duration - cursor))
        paths = []
        for i, (clip, source) in enumerate(segments):
            path = directory / f'segment-{i}.mov'
            await self.segment(clip, document, source, path, directory)
            paths.append(path)
            await self.progress(10 + int(50 * (i + 1) / len(segments)), 'editor_video')
        concat = directory / 'concat.txt'
        concat.write_text('\n'.join(f"file '{path.name}'" for path in paths))
        base = directory / 'base.mp4'
        # PCM segments have no per-clip AAC priming delay; encode the continuous audio once.
        await self.command(['-f', 'concat', '-safe', '1', '-i', str(concat), '-map', '0:v', '-map', '0:a',
                            '-c:v', 'copy', '-c:a', 'aac', '-af', 'asetpts=N/SR/TB', '-ar', '48000', '-ac', '2',
                            '-t', str(duration), str(base)], cwd=directory)
        for path in paths:
            path.unlink()
        overlay_clips = [c for c in document.clips if c.type in {'subtitle', 'sticker'}]
        font = await asyncio.to_thread(subtitle_font) if any(c.type == 'subtitle' for c in overlay_clips) else None
        # A bounded number of still-image decoders prevents large sticker sets exhausting memory.
        for offset in range(0, len(overlay_clips), 4):
            batch = overlay_clips[offset:offset + 4]
            args, filters, current, input_index = ['-threads', '1', '-i', str(base)], [], '0:v', 1
            for i, clip in enumerate(batch):
                out = f'o{i}'
                enabled = f'gte(t,{clip.start:.8f})*lt(t,{clip.start + clip.duration:.8f})'
                if clip.type == 'subtitle':
                    textfile = directory / f'subtitle-{offset+i}.txt'
                    size = clip.font_size * document.height / 1080
                    textfile.write_text(wrap_subtitle(clip.text, document.width, size), encoding='utf-8')
                    filters.append(f"[{current}]drawtext=fontfile='{filter_path(font)}':textfile='{textfile.name}':"
                        f"expansion=none:fontsize={size:.8f}:fontcolor={clip.color}:borderw={max(1,size/18):.6f}:"
                        f"bordercolor=black:x=(w-text_w)/2:y=h*(1-{clip.bottom/100:.8f})-text_h:"
                        f"line_spacing={size*.2:.4f}:enable='{enabled}'[{out}]")
                else:
                    path, _ = sources[source_key(clip.source)]
                    args += ['-loop', '1', '-framerate', str(document.fps), '-threads', '1', '-i', str(path)]
                    sw = max(2, round(document.width * .25 * clip.scale / 2) * 2)
                    filters.append(f'[{input_index}:v]scale={sw}:-2,format=rgba,colorchannelmixer=aa={clip.opacity}[s{i}]')
                    filters.append(f"[{current}][s{i}]overlay=x=W*{clip.x/100:.8f}-w/2:y=H*{clip.y/100:.8f}-h/2:"
                                   f"eof_action=repeat:enable='{enabled}'[{out}]")
                    input_index += 1
                current = out
            rendered = directory / f'overlay-{offset}.mp4'
            await self.command([*args, '-filter_complex', ';'.join(filters), '-map', f'[{current}]', '-map', '0:a',
                '-t', str(duration), *self.encoding(document), str(rendered)], cwd=directory)
            base.unlink(); base = rendered
            await self.progress(65 + int(15 * min(offset + 4, len(overlay_clips)) / len(overlay_clips)), 'editor_overlays')
        audio_clips = [c for c in document.clips if c.type == 'audio']
        if audio_clips:
            args, filters, labels = ['-i', str(base)], [], ['[0:a]']
            for index, clip in enumerate(audio_clips, 1):
                path, info = sources[source_key(clip.source)]
                trimmed = directory / f'music-{index}.wav'
                await self.command(['-ss', str(clip.trim_in), '-i', str(path), '-vn', '-t',
                    str(min(clip.duration, info['duration'] - clip.trim_in)), '-c:a', 'pcm_s16le',
                    '-ar', '48000', '-ac', '2', str(trimmed)], cwd=directory)
                args += [*(['-stream_loop', '-1'] if clip.loop else []), '-i', str(trimmed)]
                fade = f'afade=t=in:st=0:d={clip.fade_in},' if clip.fade_in else ''
                if clip.fade_out:
                    fade += f'afade=t=out:st={clip.duration-clip.fade_out:.8f}:d={clip.fade_out},'
                filters.append(f'[{index}:a]atrim=duration={clip.duration:.8f},asetpts=PTS-STARTPTS,'
                    f'volume={clip.volume},{fade}adelay={round(clip.start*1000)}:all=1[a{index}]')
                labels.append(f'[a{index}]')
            filters.append(''.join(labels) + f'amix=inputs={len(labels)}:duration=longest:normalize=0,alimiter=limit=0.95[a]')
            result = directory / 'mixed.mp4'
            await self.command([*args, '-filter_complex', ';'.join(filters), '-map', '0:v', '-map', '[a]',
                '-c:v', 'copy', '-c:a', 'aac', '-ar', '48000', '-ac', '2', '-t', str(duration),
                '-movflags', '+faststart', str(result)], cwd=directory)
            base.unlink(); base = result
        await self.progress(95, 'editor_saving')
        actual = await asyncio.to_thread(inspect_media, base)
        if (actual.width != document.width or actual.height != document.height
                or abs(float(actual.duration) - duration) > 2/document.fps + .05
                or abs(float(actual.fps) - document.fps) > .01 or not actual.audio_streams):
            raise ValueError(msg('导出结果的画面或时长与剪辑草稿不一致'))
        return base
