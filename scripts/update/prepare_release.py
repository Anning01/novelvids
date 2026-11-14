"""Build versioned release artifacts without committing generated files to main."""
import argparse
import hashlib
import io
import json
import re
import subprocess
import tarfile
import tempfile
from pathlib import Path


def version_key(value):
    if not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", value):
        raise ValueError("Expected a stable three-part version")
    return tuple(map(int, value.split(".")))


def next_version(current, latest):
    major, minor, _ = max(version_key(current), version_key(latest or current))
    return f"{major}.{minor + 1}.0"


def prepare(root, output, latest):
    manifest = json.loads((root / "release.json").read_text())
    version = next_version(manifest["version"], latest)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    manifest.update(version=version, source_commit=commit,
                    summary=f"工作台 {version}，包含本次合并的功能与修复。",
                    summary_en=f"Studio {version}, including the merged features and fixes.")
    output.mkdir(parents=True, exist_ok=True)
    archive = subprocess.check_output(["git", "archive", "--format=tar", "HEAD"], cwd=root)
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory)
        with tarfile.open(fileobj=io.BytesIO(archive)) as package:
            package.extractall(source, filter="data")
        (source / "release.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        bundle = output / "novelvids-source.tar.gz"
        with tarfile.open(bundle, "w:gz") as package:
            for path in sorted(source.iterdir()):
                package.add(path, arcname=path.name)
    manifest["source_archive"] = {"name": bundle.name, "sha256": hashlib.sha256(bundle.read_bytes()).hexdigest()}
    (output / "release.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return version


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--latest-version", default="")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(prepare(Path.cwd(), args.output, args.latest_version))
