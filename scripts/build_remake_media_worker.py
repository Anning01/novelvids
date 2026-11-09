"""只打包重制媒体工作进程及其 uv.lock 固定依赖，不包含业务配置或凭据。"""

import argparse
import hashlib
import json
import tarfile
import tomllib
from pathlib import Path

WORKER_FILES = (
    "services/remake/__init__.py", "services/remake/media_worker.py",
    "services/remake/media_prepare.py", "services/remake/scene_detection.py",
    "schemas/__init__.py", "schemas/remake_media.py",
    "utils/messages.py", "utils/messages.json", "utils/prompt_language.py",
)


def build(output: Path) -> dict:
    repo = Path(__file__).resolve().parents[1]
    packages = {p["name"]: p for p in tomllib.loads((repo / "uv.lock").read_text())["package"]}
    needed = {"scenedetect", "opencv-python-headless", "pydantic"}
    pending = list(needed)
    while pending:
        for dependency in packages[pending.pop()].get("dependencies", []):
            name = dependency["name"]
            if name not in needed:
                needed.add(name)
                pending.append(name)
    digest = hashlib.sha256()
    for name in WORKER_FILES:
        digest.update(name.encode() + b"\0" + (repo / name).read_bytes())
    requirements = "".join(f"{name}=={packages[name]['version']}\n" for name in sorted(needed))
    digest.update(requirements.encode())
    release = digest.hexdigest()[:12]
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"worker-{release}.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for name in WORKER_FILES:
            tar.add(repo / name, arcname=name)
    (output / "requirements.txt").write_text(requirements)
    result = {"release": release, "archive": archive.name, "files": list(WORKER_FILES)}
    (output / "manifest.json").write_text(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    print(json.dumps(build(parser.parse_args().output)))
