"""Attach one model-specific prompt to its originating shot in storyboard.json."""
import argparse
import json
from pathlib import Path
import tempfile


def attach(board, model, source, draft, shot_id=None):
    if not model.strip() or model == "general" or not source.strip() or not draft.strip():
        raise ValueError("Provide a model key, source prompt and model-specific draft")
    matches = [shot for shot in board["shots"]
               if (shot_id is None or shot["id"] == shot_id)
               and shot.get("prompt", "").strip() == source.strip()]
    if len(matches) != 1:
        raise ValueError("Expected one matching source prompt; verify the stable shot ID and source revision")
    shot = matches[0]
    drafts = shot.setdefault("drafts", {})
    if drafts.get("general", source).strip() != source.strip():
        raise ValueError("The saved general draft differs from the source revision")
    drafts["general"] = shot["prompt"]
    drafts[model] = draft
    return shot["id"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("board", type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument("--source", required=True, type=Path, help="general prompt used to produce this draft")
    parser.add_argument("--draft", required=True, type=Path)
    parser.add_argument("--shot-id")
    args = parser.parse_args()
    try:
        lock = args.board.with_name("." + args.board.name + ".draft-lock")
        lock.mkdir()  # Serialize simultaneous model replies before reading the current board.
        try:
            board = json.loads(args.board.read_text(encoding="utf-8"))
            target = attach(board, args.model, args.source.read_text(encoding="utf-8"),
                            args.draft.read_text(encoding="utf-8"), args.shot_id)
            with tempfile.TemporaryDirectory(dir=args.board.parent) as tmp:
                output = Path(tmp) / "storyboard.json"
                output.write_text(json.dumps(board, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                output.replace(args.board)
        finally:
            lock.rmdir()
        print(target)
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
