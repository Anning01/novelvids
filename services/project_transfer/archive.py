"""Stream a portable project ZIP to disk and verify all media before handing it to import."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import BinaryIO, Literal
from zipfile import BadZipFile, ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

from pydantic import BaseModel, ConfigDict, Field, ValidationError


FORMAT = "novelvids.project"
MANIFEST = "project.json"
CHUNK_SIZE = 1024 * 1024
MEDIA_SUFFIXES = frozenset("png jpg jpeg webp bmp gif svg mp4 mov mkv webm avi m4v wav mp3 aac flac m4a ogg srt vtt".split())


class ArchiveError(ValueError):
    pass


class MediaEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    member: str = Field(pattern=r"^media/[1-9][0-9]*\.[a-z0-9]{1,5}$")
    byte_length: int = Field(ge=0)
    storage: Literal["media", "export", "remake"] = "media"
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    format: Literal["novelvids.project"]
    version: Literal[1]
    project: dict
    media: list[MediaEntry]


@dataclass(frozen=True)
class VerifiedProject:
    project: dict
    # Keys can be resolved only inside the read_project context.
    files: dict[str, Path]
    entries: dict[str, MediaEntry]


def media_ref(member: str) -> str:
    return "novelvids:" + member


class ProjectWriter:
    def __init__(self, archive: ZipFile):
        self.archive = archive
        self.media: list[MediaEntry] = []

    def add_media(self, stream: BinaryIO, suffix: str, *, storage: Literal["media", "export", "remake"] = "media") -> str:
        suffix = suffix.lower().removeprefix(".")
        if suffix not in MEDIA_SUFFIXES:
            raise ArchiveError("不支持的作品媒体格式")
        member = f"media/{len(self.media) + 1}.{suffix}"
        digest = hashlib.sha256()
        size = 0
        with self.archive.open(member, "w", force_zip64=True) as dest:
            while chunk := stream.read(CHUNK_SIZE):
                dest.write(chunk)
                digest.update(chunk)
                size += len(chunk)
        self.media.append(MediaEntry(member=member, byte_length=size, sha256=digest.hexdigest(), storage=storage))
        return media_ref(member)


@contextmanager
def write_project(path: Path, project: dict) -> Iterator[ProjectWriter]:
    """Publish only a complete archive. The caller may add references to project while writing."""
    with NamedTemporaryFile(dir=path.parent, suffix=".partial", delete=False) as file:
        partial = Path(file.name)
    try:
        with ZipFile(partial, "w", allowZip64=True) as archive:
            writer = ProjectWriter(archive)
            yield writer
            manifest = Manifest(format=FORMAT, version=1, project=project, media=writer.media)
            archive.writestr(MANIFEST, manifest.model_dump_json(), compress_type=ZIP_DEFLATED)
        partial.replace(path)
    finally:
        partial.unlink(missing_ok=True)


def read_manifest(archive: ZipFile, max_manifest_bytes: int) -> tuple[Manifest, dict[str, ZipInfo]]:
    entries = archive.infolist()
    indexed = {info.filename: info for info in entries}
    info = indexed.get(MANIFEST)
    if len(indexed) != len(entries) or not info or info.file_size > max_manifest_bytes:
        raise ArchiveError("作品包目录或清单无效")
    if info.compress_type not in {ZIP_STORED, ZIP_DEFLATED} or info.flag_bits & 1:
        raise ArchiveError("不支持的作品清单编码")
    try:
        manifest = Manifest.model_validate_json(archive.read(info))
    except ValidationError as exc:
        raise ArchiveError("无法读取此版本的作品包清单") from exc
    members = {item.member for item in manifest.media}
    if len(members) != len(manifest.media) or set(indexed) != {MANIFEST, *members}:
        raise ArchiveError("作品清单与包内文件不一致")
    for item in manifest.media:
        member = indexed[item.member]
        if (item.member.rsplit(".", 1)[1] not in MEDIA_SUFFIXES or member.compress_type != ZIP_STORED
                or member.file_size != member.compress_size or member.file_size != item.byte_length or member.flag_bits & 1):
            raise ArchiveError("作品媒体大小或格式无效")
    return manifest, indexed


@contextmanager
def read_project(file: BinaryIO, staging_parent: Path, *, max_manifest_bytes: int = 128 * 1024 * 1024) -> Iterator[VerifiedProject]:
    """Extract only verified regular files to private staging, never to archive-supplied paths."""
    with TemporaryDirectory(dir=staging_parent, prefix=".project-import-") as staging:
        files = {}
        try:
            with ZipFile(file, "r") as archive:
                manifest, indexed = read_manifest(archive, max_manifest_bytes)
                for entry in manifest.media:
                    digest = hashlib.sha256()
                    path = Path(staging) / Path(entry.member).name
                    with archive.open(indexed[entry.member]) as source, path.open("xb") as dest:
                        while chunk := source.read(CHUNK_SIZE):
                            digest.update(chunk)
                            dest.write(chunk)
                    if path.stat().st_size != entry.byte_length or digest.hexdigest() != entry.sha256:
                        raise ArchiveError("作品媒体校验失败")
                    files[media_ref(entry.member)] = path
        except (BadZipFile, EOFError) as exc:
            raise ArchiveError("作品包已损坏") from exc
        yield VerifiedProject(manifest.project, files, {media_ref(e.member): e for e in manifest.media})
