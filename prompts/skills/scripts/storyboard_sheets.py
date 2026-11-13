"""Prepare optional line-art storyboard generation from a finished chapter's shots."""

import argparse
import json
from pathlib import Path
import tempfile


def read_settings(project):
    path = project / "novelvids.config.json"
    settings = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not isinstance(settings, dict) or not isinstance(settings.get("storyboard_enabled", False), bool):
        raise ValueError("novelvids.config.json: storyboard_enabled must be a boolean")
    return settings


def set_enabled(project, settings, value):
    path = project / "novelvids.config.json"
    if settings.get("storyboard_enabled", False) == value:
        return
    settings["storyboard_enabled"] = value
    with tempfile.TemporaryDirectory(dir=project) as scratch:
        temp = Path(scratch) / path.name
        temp.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(path)


def prepare(board, templates):
    shots = board["shots"]
    if not isinstance(shots, list) or not shots:
        raise ValueError("Provide a non-empty shots list")
    jobs = []
    seen = set()
    visual_fields = ("time_setting", "environment", "spatial_relationships", "shot_size_and_camera",
                     "visual_prose", "camera_movement", "actions", "segments", "blocking_map")
    for shot in shots:
        number = shot["sequence"]
        if type(number) is not int or number < 1 or number in seen:
            raise ValueError(f"Invalid or duplicate shot sequence: {number}")
        seen.add(number)
        prompt = shot["prompt"]
        if not isinstance(prompt, str) or not prompt.strip() or not shot.get("actions") or not shot.get("visual_prose"):
            raise ValueError(f"Shot {number} needs a finished prompt, initial frame and action timeline")
        visual = {key: shot[key] for key in visual_fields if shot.get(key)}
        jobs.append({"sequence": number, "file_stem": f"shot-{number:03}-board",
                     "image_prompt": templates["image"] + "\n\n" + json.dumps(visual, ensure_ascii=False, indent=2),
                     "video_prompt": prompt + "\n\n" + templates["video"]})
    return jobs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd(), help="production project root")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "on", "off"):
        commands.add_parser(name)
    job = commands.add_parser("prepare")
    job.add_argument("board", type=Path)
    job.add_argument("--language", choices=("zh", "en"), default="zh")
    args = parser.parse_args()
    try:
        settings = read_settings(args.project)
        if args.command in ("on", "off"):
            set_enabled(args.project, settings, args.command == "on")
        enabled = settings.get("storyboard_enabled", False)
        if args.command == "prepare":
            result = []
            if enabled:
                root = Path(__file__).resolve().parents[1]
                templates = root / "references/storyboard_sheet_templates.json"
                if not templates.exists():
                    templates = root / "novelvids-storyboard/references/storyboard_sheet_templates.json"
                source = args.project / args.board
                result = prepare(json.loads(source.read_text(encoding="utf-8")),
                                 json.loads(templates.read_text(encoding="utf-8"))[args.language])
        else:
            result = {"storyboard_enabled": enabled}
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
