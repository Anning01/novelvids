"""Preserve stable MCP identifiers without importing online users, requests or billing receipts."""
from uuid import uuid4
from models.asset import Asset
from models.asset_variant import AssetVariant
from models.chapter import Chapter
from models.novel import Novel
from models.scene import Scene
from models.work_sync import WorkSyncObject
from services.local_mcp.package import digest
from services.project_transfer.archive import ArchiveError

KINDS = {"work":Novel,"episode":Chapter,"asset":Asset,"variant":AssetVariant,"shot":Scene}


async def mappings_for(novel_id, db):
    works = await WorkSyncObject.filter(kind="work",local_id=novel_id).using_db(db)
    result = []
    for work in works:
        objects = await WorkSyncObject.filter(work_id=work.work_id).using_db(db).order_by("id").values(
            "stable_id","episode_id","kind","local_id","payload")
        result.append({"work":work.stable_id, "objects":objects})
    return result


async def restore_mappings(groups, ids, novel_id, team_id, db):
    for group in groups:
        work = group["work"]
        def scoped(name):
            return f"t{team_id}:{digest(name)}" if team_id is not None else name
        # Importing a copy must never redirect the existing project's external editing clients.
        while await WorkSyncObject.filter(work_id=scoped(work)).using_db(db).exists():
            work = f"{group['work'][:85]}-{uuid4().hex}"
        anchors = [item for item in group["objects"] if item["kind"]=="work"]
        if len(anchors)!=1 or ids.get(Novel,anchors[0]["local_id"])!=novel_id:
            raise ArchiveError("外部作品编号与项目不匹配")
        for item in group["objects"]:
            kind = item["kind"]
            if kind not in KINDS:
                raise ArchiveError("作品同步对象类型无效")
            local_id = ids.tables.get(KINDS[kind],{}).get(item["local_id"])
            if local_id is None: continue  # Deleted objects are outside the active project snapshot.
            payload = item["payload"]
            if kind=="work":
                payload={**payload,"id":work}
            elif kind=="episode":
                payload={**payload, "manifest":{**payload["manifest"],"work":{**payload["manifest"]["work"],"id":work}}}
            elif kind in {"asset","variant"}:
                from services.creation_objects import CreationObjects
                target = await KINDS[kind].get(id=local_id).using_db(db)
                payload={**payload, "version":await CreationObjects.recovery_version(target)}
            await WorkSyncObject.create(using_db=db,work_id=scoped(work),episode_id=item["episode_id"],kind=kind,
                stable_id=work if kind=="work" else item["stable_id"],local_id=local_id,payload=payload)
