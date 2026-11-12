"""Describe what the browser should download. Model media never passes through a migration proxy."""
from pathlib import PurePosixPath
import mimetypes
from urllib.parse import unquote, urlsplit
from ipaddress import ip_address

from services.oss import normalize_media_url, resolve_media_url
from services.project_transfer.archive import ArchiveError, MEDIA_SUFFIXES, media_ref
from services.project_transfer.local_media import archived_document, document_refs, translate


def export_plan(snapshot: dict, team_id: int | None) -> dict:
    approved = document_refs(snapshot)
    private = {}
    for row in snapshot["exports"]:
        for field, query in (("media_ref", ""), ("source_media_ref", "?source=true")):
            ref = row.get(field)
            if ref:
                private[ref] = f"/api/video/exports/{row['id']}/download{query}"

    shared_media = {normalize_media_url(row.get(field)) for row in snapshot.get("library", [])
                    for field in ("storage_ref", "poster_ref") if row.get(field)}
    export_urls = {url:ref for ref,url in private.items()}
    files = []
    refs = {}

    def resolve(value):
        if value.startswith("blob:"):
            raise ArchiveError("浏览器中的素材应由导出端直接打包")
        if value.startswith("data:"):
            if value in refs:
                return refs[value]
            mime, separator, _ = value[5:].partition(";base64,")
            suffix = (mimetypes.guess_extension(mime) or "").lstrip(".")
            if not separator or suffix not in MEDIA_SUFFIXES:
                raise ArchiveError("作品内嵌素材格式无效")
            member = f"media/{len(files)+1}.{suffix}"
            files.append({"member":member,"url":value,"storage":"media","authenticated":False})
            refs[value] = media_ref(member)
            return refs[value]
        if value in export_urls:
            return resolve(export_urls[value])
        if not value.startswith(("/media/", "uploads/", "remake/sources/", "https://", "http://")) or "\n" in value:
            return value
        if value in refs:
            return refs[value]
        key = normalize_media_url(value) or value
        parsed = urlsplit(key)
        path = unquote(parsed.path)
        parts = PurePosixPath(path).parts
        if ".." in parts or "\\" in path or any(ord(c) < 32 for c in path):
            raise ArchiveError("素材地址无效")
        suffix = PurePosixPath(path).suffix.lower().removeprefix(".")
        if suffix not in MEDIA_SUFFIXES and not archived_document(key, approved):
            raise ArchiveError("作品包含无法识别格式的素材")
        authenticated = False
        storage = "media"
        if key.startswith("/media/exports/"):
            if value not in private:
                raise ArchiveError("作品引用的成片不属于当前项目")
            url, authenticated, storage = private[value], True, "export"
        elif key.startswith("uploads/"):
            if not key.startswith(f"uploads/{team_id or 0}/") and key not in shared_media:
                raise ArchiveError("素材不属于作品团队")
            url = resolve_media_url(key)
            if not url or url == key:
                raise ArchiveError("对象存储素材暂时不可访问")
            if value in private:
                storage = "export"
        elif key.startswith("remake/sources/"):
            # The source belongs to the current project, regardless of the installation's default provider.
            source = next((row for row in snapshot["remake_sources"] if row["object_key"] == key), None)
            if not source:
                raise ArchiveError("作品引用的来源视频不属于当前项目")
            storage = "remake"
            url = resolve_media_url(key) if source["storage_provider"] == "oss" else "/media/" + key
            if url == key:
                raise ArchiveError("对象存储素材暂时不可访问")
        elif key.startswith("/media/"):
            url = key
        else:
            host = parsed.hostname
            if parsed.scheme != "https" or not host or parsed.username or parsed.password or "." not in host or host.endswith((".localhost", ".local", ".internal")):
                raise ArchiveError("远程素材需要可访问的 HTTPS 地址")
            try:
                address = ip_address(host)
            except ValueError:
                pass
            else:
                if not address.is_global:
                    raise ArchiveError("远程素材地址无效")
            url = key
        member = f"media/{len(files) + 1}.{suffix}"
        files.append({"member":member, "url":url, "storage":storage, "authenticated":authenticated})
        refs[value] = media_ref(member)
        return refs[value]

    project = translate(snapshot, resolve)
    return {"project":project, "files":files}
