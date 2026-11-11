"""Install verified project files under fresh collection names before committing the local graph."""
import asyncio
from contextlib import ExitStack
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from uuid import uuid4

from services.project_transfer.archive import ArchiveError, read_project
from services.project_transfer.local_media import translate
from services.project_transfer.restore import restore_graph
from services.storyboard.blocking_reference import standalone_svg


async def install_project(file, *, media_root: Path, exports_root: Path, team_id, user_id):
    collection = uuid4().hex
    # Each import owns its directory, including on filesystem or database rollback.
    with ExitStack() as rollback, TemporaryDirectory() as staging:
        opened = read_project(file, Path(staging))
        verified = await asyncio.to_thread(opened.__enter__)
        try:
            roots = {
                "media": (media_root / "project-imports" / collection, f"/media/project-imports/{collection}/"),
                "export": (exports_root / "imports" / collection, f"/media/exports/imports/{collection}/"),
                "remake": (media_root / "remake" / "sources" / collection, f"remake/sources/{collection}/"),
            }
            refs = {}
            def copy_media():
                for ref, source in verified.files.items():
                    entry = verified.entries[ref]
                    folder, prefix = roots[entry.storage]
                    if not folder.exists():
                        folder.mkdir(parents=True)
                        rollback.callback(shutil.rmtree, folder, ignore_errors=True)
                    name = entry.sha256 + source.suffix
                    target = folder / name
                    if not target.exists():
                        if source.suffix == ".svg":
                            target.write_bytes(standalone_svg(source.read_bytes()))
                        else:
                            shutil.copyfile(source, target)
                    refs[ref] = prefix + name
            await asyncio.to_thread(copy_media)

            def local_reference(value):
                if value.startswith("novelvids:media/"):
                    if value not in refs:
                        raise ArchiveError("作品包缺少所引用的素材")
                    return refs[value]
                if value.startswith(("/media/", "uploads/", "remake/sources/")):
                    raise ArchiveError("作品包包含未打包的媒体引用")
                return value

            graph = translate(verified.project, local_reference)
            novel = await restore_graph(graph, team_id=team_id, user_id=user_id)
        finally:
            opened.__exit__(None, None, None)
        rollback.pop_all()
        return novel
