"""仅供 SSH 调用的媒体工作进程，不启动 HTTP 服务或访问业务数据库。"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

from schemas.remake_media import MediaWorkerRequest, MediaScene, MediaScenes, PreparedMedia


def execute(request: MediaWorkerRequest, root: Path) -> dict:
    work = root / "jobs" / request.job_id.hex
    if request.action == "create":
        work.mkdir(parents=True, mode=0o700, exist_ok=False)
        return {"ok": True}
    if request.action == "cleanup":
        for phase in ("prepare", "split"):
            subprocess.run(
                ["systemctl", "stop", f"novelvids-remake-{request.job_id.hex}-{phase}.service"],
                check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        if work.exists():
            shutil.rmtree(work)
        return {"ok": True}
    if request.action == "prepare":
        from services.remake.media_prepare import prepare_video_for_model_input

        prepared = prepare_video_for_model_input(
            work / f"source{request.extension}", work / "model-input", max_bytes=request.max_bytes,
        )
        destination = work / f"model{prepared.suffix}"
        destination.hardlink_to(prepared)
        result = PreparedMedia(filename=destination.name, size_bytes=destination.stat().st_size)
        (work / "prepared.json").write_text(result.model_dump_json())
        return result.model_dump()

    from services.remake.scene_detection import scene_detector
    from services.remake.media_prepare import probe_media_duration

    prepared = PreparedMedia.model_validate_json((work / "prepared.json").read_text())
    paths = scene_detector.split(work / prepared.filename, work / "scenes")
    return MediaScenes(scenes=[
        MediaScene(filename=path.name, duration_seconds=probe_media_duration(path)) for path in paths
    ]).model_dump()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("request", help="JSON MediaWorkerRequest")
    args = parser.parse_args()
    request = MediaWorkerRequest.model_validate_json(args.request)
    print(json.dumps(execute(request, args.root.resolve())), flush=True)


if __name__ == "__main__":
    main()
