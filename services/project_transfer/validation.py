"""Validate a portable graph before installing files or assigning local IDs."""
from pathlib import PureWindowsPath
import re

from services.project_transfer.archive import ArchiveError, DOCUMENT_SUFFIXES, VerifiedProject
from services.project_transfer.local_media import PROSE_FIELDS, document_refs

GROUPS = ("chapters", "assets", "variants", "scenes", "videos", "editor_assets", "edit_drafts",
          "exports", "publications", "remake_sources", "voices", "library")
MEDIA_FIELDS = {"cover", "main_image", "angle_image_1", "angle_image_2", "url", "audio_url", "avatar_url",
               "storage_ref", "poster_ref", "media_ref", "source_media_ref", "object_key", "first_frame_url",
               "last_frame_url", "image_url", "previous_image_url", "images", "reference_images", "image_gallery",
               "reference_videos", "reference_audios", "generation_reference_images", "selected_image_urls"}


def validate_portable_graph(verified: VerifiedProject):
    project = verified.project
    if not isinstance(project.get("novel"), dict) or not isinstance(project["novel"].get("name"), str):
        raise ArchiveError("作品清单缺少项目名称")
    if any(not isinstance(project.get(group), list) for group in GROUPS):
        raise ArchiveError("作品包缺少创作数据")
    for rows in ([project["novel"]], *(project[group] for group in GROUPS)):
        if any(not isinstance(row, dict) or type(row.get("id")) is not int or row["id"] <= 0 for row in rows):
            raise ArchiveError("作品记录编号无效")
        if len({row["id"] for row in rows}) != len(rows):
            raise ArchiveError("作品记录编号重复")

    def visit(value, field):
        if isinstance(value, list):
            for item in value:
                visit(item, field)
        elif isinstance(value, dict):
            for key, item in value.items():
                visit(item, key)
        elif isinstance(value, str) and value and field not in PROSE_FIELDS:
            if value.startswith("novelvids:media/"):
                if value not in verified.files:
                    raise ArchiveError("作品包缺少所引用的素材")
            elif field in MEDIA_FIELDS or field.endswith(("_image_url", "_thumbnail_url", "_media_url")):
                raise ArchiveError("作品媒体必须来自包内文件")
            elif value.startswith(("/", "\\", "../", "file:", "uploads/", "remake/sources/")) or PureWindowsPath(value).drive and not re.match(r"^[A-Za-z][A-Za-z0-9+.-]+://", value):
                raise ArchiveError("作品包包含外部文件路径")

    canvases = project.get("canvases", {})
    if not isinstance(canvases, dict) or not set(canvases) <= {str(row["id"]) for row in project["chapters"]}:
        raise ArchiveError("作品中的画布章节无效")
    from services.project_transfer.canvas import check_layout
    for layout in canvases.values():
        check_layout(layout)
    groups = project.get("sync_works", [])
    if not isinstance(groups,list) or any(not isinstance(g,dict) or not isinstance(g.get("work"),str)
       or not isinstance(g.get("objects"),list) or any(not isinstance(o,dict) or not isinstance(o.get("payload"),dict)
       for o in g["objects"]) for g in groups):
        raise ArchiveError("外部作品同步清单无效")
    docs = document_refs(project)
    if any(file.suffix[1:] in DOCUMENT_SUFFIXES and ref not in docs for ref,file in verified.files.items()):
        raise ArchiveError("原始文稿不在作品清单中")
    visit(project, "")
