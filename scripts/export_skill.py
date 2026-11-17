"""Export one NovelVids skill as a portable directory, including its referenced rules."""

import argparse
import posixpath
from pathlib import Path
import re
import shutil
import tempfile
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "prompts" / "skills"
LINK = re.compile(r"(\[[^\]\n]+\]\()([^()\n]+)(\))")


def entrypoints() -> dict[str, Path]:
    return {path.parent.name: path for path in sorted(SKILLS.glob("novelvids-*/SKILL.md"))}


def export_skill(name: str, destination: Path) -> Path:
    entries = entrypoints()
    if name not in entries:
        raise ValueError(f"Unknown skill: {name}")

    entry = entries[name]
    resources: dict[str, Path] = {"agents/openai.yaml": entry.parent / "agents/openai.yaml"}
    contents: dict[str, bytes] = {}
    pending = [('SKILL.md', entry)]

    while pending:
        filename, document = pending.pop(0)

        def package_link(match: re.Match) -> str:
            url = urlsplit(match[2])
            if url.scheme or url.netloc or not url.path:
                return match[0]
            source = (document.parent / url.path).resolve(strict=True)
            if source in {SKILLS / "scripts/draw_blocking.py", SKILLS / "scripts/storyboard_sheets.py", SKILLS / "scripts/select_video_optimizer.py", SKILLS / "scripts/attach_shot_draft.py"}:
                relative = f"scripts/{source.name}"
            elif (source.is_relative_to(SKILLS) and source.parent.name == "references"
                  and source.suffix in {".md", ".json"} and source.is_file()):
                relative = f"references/{source.name}"
            else:
                raise ValueError(f"Unsupported skill reference: {match[2]}")
            if relative in resources:
                if resources[relative] != source:
                    raise ValueError(f"Conflicting skill references: {relative}")
            else:
                resources[relative] = source
                if source.suffix == '.md':
                    pending.append((relative, source))
            target = posixpath.relpath(relative, posixpath.dirname(filename) or '.')
            if url.fragment:
                target += '#' + url.fragment
            return f"{match[1]}{target}{match[3]}"

        contents[filename] = LINK.sub(package_link, document.read_text(encoding='utf-8')).encode('utf-8')
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / name
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"Skill already exists: {target}")
    with tempfile.TemporaryDirectory(dir=destination) as scratch:
        package = Path(scratch) / name
        (package / "references").mkdir(parents=True)
        (package / "SKILL.md").write_bytes(contents['SKILL.md'])
        shutil.copyfile(ROOT / "LICENSE", package / "LICENSE")
        for filename, source in resources.items():
            target_file = package / filename
            target_file.parent.mkdir(exist_ok=True)
            if filename in contents:
                target_file.write_bytes(contents[filename])
            else:
                shutil.copyfile(source, target_file)
        package.rename(target)
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    names = list(entrypoints())
    parser.add_argument("name", nargs="?", choices=names)
    parser.add_argument("--dest", type=Path, help="parent directory for the standalone package")
    parser.add_argument("--list", action="store_true", help="list publishable skills")
    args = parser.parse_args()
    if args.list:
        print("\n".join(names))
        return
    if args.name is None or args.dest is None:
        parser.error("provide a skill name and --dest, or use --list")
    try:
        print(export_skill(args.name, args.dest))
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
