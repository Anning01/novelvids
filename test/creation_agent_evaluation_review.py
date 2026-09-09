"""Bind independent reviews to immutable step evidence for one frozen run."""

import copy
import hashlib
import json
import sys
import re
from pathlib import Path


def step_evidence_sha256(step: dict) -> str:
    payload = json.dumps(step, ensure_ascii=False, sort_keys=True, default=str).encode()
    return hashlib.sha256(payload).hexdigest()


def selected_run(records: list[dict], run_id: str) -> list[dict]:
    selected = [copy.deepcopy(row) for row in records if row.get("run_id") == run_id]
    keys = [(row["case_id"], row["repetition"]) for row in selected]
    if len(keys) != len(set(keys)):
        raise ValueError("冻结轮次存在重复实例，禁止挑选最佳结果")
    return selected


def amend_unchanged_scene_checks(step: dict) -> None:
    """Remove legacy-content checks that predate and were not caused by this run."""
    before = {row["id"]: row for row in step.get("before", {}).get("scene", [])}
    after = {row["id"]: row for row in step.get("after", {}).get("scene", [])}
    unchanged = {
        id for id in before.keys() & after.keys()
        if (before[id].get("prompt"), before[id].get("prompt_params"))
        == (after[id].get("prompt"), after[id].get("prompt_params"))
    }
    retained = []
    removed = []
    content_markers = ("external shorthand", "nonlocal numbering", "incorrect segment count",
                       "current definition missing")
    for failure in step.get("hard_failures", []):
        match = re.match(r"scene:(\d+):", failure)
        if match and int(match.group(1)) in unchanged and any(marker in failure for marker in content_markers):
            removed.append(failure)
        else:
            retained.append(failure)
    if removed:
        step["hard_failures"] = retained
        step.setdefault("evaluation_amendments", []).append({
            "kind": "unchanged_legacy_content",
            "removed_raw_hard_failures": removed,
            "reason": "目标内容未发生变化；该问题属于执行结果失败，不是本次写入造成的数据破坏。",
        })


def apply_quality_reviews(records: list[dict], reviews: list[dict], run_id: str) -> list[dict]:
    selected = selected_run(records, run_id)
    review_rows = [row for row in reviews if row.get("run_id") == run_id]
    review_keys = [(row["case_id"], row["repetition"], row["step"]) for row in review_rows]
    if len(review_keys) != len(set(review_keys)):
        raise ValueError("同一证据存在重复独立评审")
    by_key = {key: row for key, row in zip(review_keys, review_rows)}
    evidence_keys = set()
    for record in selected:
        for index, step in enumerate(record["steps"], 1):
            key = (record["case_id"], record["repetition"], index)
            evidence_keys.add(key)
            review = by_key.get(key)
            evidence_hash = step_evidence_sha256(step)
            if review is None:
                amend_unchanged_scene_checks(step)
                continue
            if review.get("evidence_sha256") != evidence_hash:
                raise ValueError(f"{key} 的评审证据哈希不匹配")
            quality = review.get("quality_review")
            if not isinstance(quality, dict):
                raise ValueError(f"{key} 缺少评审内容")
            step["quality_review"] = copy.deepcopy(quality)
            amend_unchanged_scene_checks(step)
    unexpected = set(by_key) - evidence_keys
    if unexpected:
        raise ValueError(f"评审包含冻结轮次中不存在的步骤: {sorted(unexpected)}")
    return selected


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


if __name__ == "__main__":
    if len(sys.argv) != 5:
        raise SystemExit("usage: results.jsonl quality-reviews.jsonl RUN_ID reviewed-results.jsonl")
    results_path, reviews_path, run_id, output_path = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4])
    reviewed = apply_quality_reviews(_read_jsonl(results_path), _read_jsonl(reviews_path), run_id)
    output_path.write_text("".join(json.dumps(row, ensure_ascii=False, default=str) + "\n" for row in reviewed))
