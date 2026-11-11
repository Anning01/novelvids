"""Resolve the final prompt-authoring skill for the selected video model."""

import argparse
import json
from pathlib import Path


def select(project, model, registry):
    if model is None:
        settings = project / "novelvids.config.json"
        model = json.loads(settings.read_text(encoding="utf-8")).get("video_model_type") if settings.exists() else None
    if model is not None and not isinstance(model, str):
        raise ValueError("video_model_type must be a string")
    key = (model or "").strip().casefold()
    for model_type, profile in registry.items():
        if key not in {value.casefold() for value in [model_type, *profile["aliases"]]}:
            continue
        name = profile["skill"]
        entry = project / ".agents" / "skills" / name / "SKILL.md"
        if entry.is_file():
            return {"mode": "optimize", "model_type": model_type, "skill": name, "entry": str(entry.resolve())}
        return {"mode": "missing", "model_type": model_type, "skill": name, "source": profile["source"]}
    return {"mode": "generic", "model_type": model}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd(), help="production project root")
    parser.add_argument("--model", help="selected video model type; overrides the project setting")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    registry = root / "references/video_prompt_models.json"
    if not registry.exists():
        registry = root / "novelvids-video/references/video_prompt_models.json"
    try:
        result = select(args.project, args.model, json.loads(registry.read_text(encoding="utf-8")))
    except (ValueError, OSError, AttributeError) as error:
        parser.exit(1, f"{error}\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
