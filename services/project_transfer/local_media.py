"""Translate application media references when packing or opening a local project."""
from pathlib import Path
import re
from urllib.parse import quote, unquote

from services.project_transfer.archive import ArchiveError, MEDIA_SUFFIXES, write_project

MENTION = re.compile(r"(@\{参考(?:图片|视频):)([^}]+)(\})")


def translate(value, resolve):
    if isinstance(value, dict):
        return {k: translate(v, resolve) for k, v in value.items()}
    if isinstance(value, list):
        return [translate(item, resolve) for item in value]
    if not isinstance(value, str):
        return value
    translated = resolve(value)
    if translated != value:
        return translated

    def mention(match):
        source = unquote(match[2])
        target = resolve(source)
        if target == source:
            return match[0]
        # encodeURIComponent, as used by the canvas and the storyboard editor.
        return match[1] + quote(target, safe="-_.!~*'()") + match[3]

    return MENTION.sub(mention, value)


def pack_local_snapshot(snapshot: dict, destination: Path, *, media_root: Path, exports_root: Path):
    """Package on the machine that owns the media. No server-side URL fetching."""
    contents = {}
    with write_project(destination, contents) as writer:
        cached = {}

        def resolve(source):
            if source in cached:
                return cached[source]
            storage = "media"
            if source.startswith("/media/exports/"):
                storage = "export"
                root, relative = exports_root, source[len("/media/exports/"):]
            elif source.startswith("/media/"):
                root, relative = media_root, source[len("/media/"):]
            elif source.startswith("remake/sources/"):
                storage = "remake"
                root, relative = media_root, source
            elif source.startswith(("https://", "http://", "uploads/")) and "\n" not in source:
                # The client must fetch these directly from their origin before finalizing the archive.
                raise ArchiveError("作品包含远程素材，需从素材来源下载原文件")
            else:
                return source
            root = root.resolve()
            path = (root / relative).resolve()
            if not path.is_relative_to(root) or not path.is_file() or path.suffix.lower().lstrip(".") not in MEDIA_SUFFIXES:
                raise ArchiveError("作品引用的本地素材缺失或路径无效")
            with path.open("rb") as file:
                ref = writer.add_media(file, path.suffix, storage=storage)
            cached[source] = ref
            return ref

        contents.update(translate(snapshot, resolve))
