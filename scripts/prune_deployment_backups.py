"""Keep one verified NovelVids rollback bundle; preview unless --apply is given."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import shutil
import subprocess
import tarfile


def validate_backup(root: Path, name: str) -> Path:
    if not re.fullmatch(r"release-[a-f0-9]{7,40}-[0-9]{14}", name):
        raise ValueError("Expected a release-<commit>-<timestamp> directory name")
    backup_root = root / "novelvids-deploy-backups"
    keep = backup_root / name
    if root.is_symlink() or backup_root.is_symlink() or keep.is_symlink():
        raise ValueError("Backup paths must not be symbolic links")
    for relative in ("previous-commit", "database.dump", "code.tar.gz", "dist/index.html"):
        path = keep / relative
        if not path.is_file() or path.stat().st_size == 0 or not path.resolve().is_relative_to(keep.resolve()):
            raise ValueError(f"Missing or invalid rollback file: {relative}")
    if not re.fullmatch(r"[a-f0-9]{40}", (keep / "previous-commit").read_text().strip()):
        raise ValueError("Invalid previous commit")
    subprocess.run(["pg_restore", "--list", str(keep / "database.dump")], check=True, stdout=subprocess.DEVNULL)
    with tarfile.open(keep / "code.tar.gz") as archive:
        if "main.py" not in archive.getnames():
            raise ValueError("Code archive is incomplete")
    return keep


def cleanup_targets(root: Path, keep: Path) -> list[Path]:
    targets = [path for path in keep.parent.iterdir() if path != keep]
    # Legacy deployment locations only; never match live application/data paths.
    for pattern in (
        "novelvids-dependency-backup.*", "novelvids-deploy-backup-dist-*",
        "novelvids-dist-rollback-*", "novelvids-web-*",
    ):
        targets.extend(root.glob(pattern))
    for path in (root / "novelvids-releases", root / "novelvids-deploy-artifacts", root / "deploy-backups/novelvids"):
        if path.exists() or path.is_symlink():
            targets.append(path)
    backups = root / "backups"
    if backups.exists():
        if backups.is_symlink():
            raise ValueError("Legacy backup parent must not be a symbolic link")
        targets.extend(backups.glob("novelvids-*"))
        targets.extend(backups.glob(".novelvids-*"))
    for path in targets:
        if path == keep or path in keep.parents or keep in path.parents:
            raise ValueError("Refusing to delete the retained backup")
    return sorted(set(targets))


def remove_targets(targets: list[Path]) -> None:
    for path in targets:
        if path.is_symlink() or path.is_file():
            path.unlink()
        else:
            shutil.rmtree(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", required=True, help="Verified release directory name to retain")
    parser.add_argument("--root", type=Path, default=Path("/root"), help="Deployment parent (default: /root)")
    parser.add_argument("--apply", action="store_true", help="Delete listed historical backups")
    args = parser.parse_args()
    root = args.root.absolute()
    keep = validate_backup(root, args.keep)
    targets = cleanup_targets(root, keep)
    print(f"Retain: {keep}")
    for path in targets:
        print(f"Remove: {path}")
    if args.apply:
        remove_targets(targets)
        print("Historical backups removed; one rollback bundle retained.")
    else:
        print("Preview only; use --apply after deployment health checks pass.")


if __name__ == "__main__":
    main()
