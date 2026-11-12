"""Rebind an exported browser canvas to the restored project without rewriting creative text."""
import re
from math import isfinite
from models.asset import Asset
from models.asset_variant import AssetVariant
from models.audio_reference import AudioReference
from models.chapter_export import ChapterExport
from models.remake_source import RemakeSource
from models.scene import Scene
from models.video import Video
from models.resource_library import VideoResource
from services.project_transfer.archive import ArchiveError

MANUAL = {"audio_reference","digital_human","image_media","video_media","audio_media","watermark",
          "video_composer","video_enhancement","section","note"}


def check_layout(value):
    if not isinstance(value,dict) or value.get("version")!=2 or not isinstance(value.get("nodes"),dict):
        raise ArchiveError("画布存档格式无效")
    view = value.get("viewport")
    if not isinstance(view,dict) or not all(type(view.get(k)) in {float,int} and isfinite(view[k]) for k in ("x","y","zoom")) or view["zoom"] <= 0:
        raise ArchiveError("画布视口无效")
    manual,edges = value.get("manualNodes"),value.get("manualEdges")
    if not isinstance(manual,list) or not isinstance(edges,list):
        raise ArchiveError("画布节点或连线格式无效")
    keys = set()
    for node in manual:
        if not isinstance(node,dict) or node.get("kind") not in MANUAL or not isinstance(node.get("key"),str) or not isinstance(node.get("data"),dict):
            raise ArchiveError("手工画布节点无效")
        key = node["key"]
        if key in keys or key in {"chapter","__proto__","constructor","prototype"} or re.fullmatch(r"(?:asset|shot|video|remake-source)-\d+(?:-variant-\d+)?",key):
            raise ArchiveError("画布节点编号冲突")
        keys.add(key)
    if any(not isinstance(e,dict) or not all(isinstance(e.get(k),str) for k in ("key","source","target")) for e in edges):
        raise ArchiveError("画布连线缺少端点")
    return value


def rebind_layout(layout, ids):
    check_layout(layout)
    manual = {n["key"] for n in layout["manualNodes"]}
    def node_key(key):
        if key == "chapter" or key in manual:
            return key
        asset = re.fullmatch(r"asset-(\d+)(?:-variant-(\d+))?",key)
        if asset:
            base = ids.tables.get(Asset,{}).get(int(asset[1]))
            variant = ids.tables.get(AssetVariant,{}).get(int(asset[2])) if asset[2] else None
            if base and (not asset[2] or variant):
                return f"asset-{base}-variant-{variant}" if variant else f"asset-{base}"
        system = re.fullmatch(r"(shot|video|remake-source)-(\d+)",key)
        if system:
            model = {"shot":Scene,"video":Video,"remake-source":RemakeSource}[system[1]]
            new = ids.tables.get(model,{}).get(int(system[2]))
            if new: return f"{system[1]}-{new}"
        return None  # Historical deleted nodes have no target in the restored work.

    nodes = []
    for node in layout["manualNodes"]:
        data = ids.references(node["data"])
        if "node_keys" in data:
            data["node_keys"] = [new for k in data["node_keys"] if (new:=node_key(k))]
        for field,model in (("upload_source_id",VideoResource),("export_id",ChapterExport),("source_export_id",ChapterExport)):
            if field in data and data[field] is not None:
                data[field] = ids.tables.get(model,{}).get(data[field])
        if isinstance(data.get("resource"),dict):
            if node["kind"]=="audio_reference" and data["resource"].get("id"):
                data["resource"]["id"] = ids.get(AudioReference,data["resource"]["id"])
            data.pop("resource_catalog_key",None)
        nodes.append({**node,"data":data})
    edges = []
    for edge in layout["manualEdges"]:
        src,dst = node_key(edge["source"]),node_key(edge["target"])
        if src and dst:
            edges.append({**edge,"source":src,"target":dst,"config":ids.references(edge.get("config"))})
    return {**layout,"nodes":{new:v for k,v in layout["nodes"].items() if (new:=node_key(k))},
            "manualNodes":nodes,"manualEdges":edges}
