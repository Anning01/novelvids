import json

import pytest

from test.creation_agent_evaluation_review import apply_quality_reviews, selected_run, step_evidence_sha256


def result(run_id="fixed", case_id="I01", repetition=1):
    return {"run_id": run_id, "case_id": case_id, "repetition": repetition,
            "steps": [{"reply": "已保存", "quality_review": {"reviewer": None}}]}


def review_for(record):
    step = record["steps"][0]
    return {"run_id": record["run_id"], "case_id": record["case_id"],
            "repetition": record["repetition"], "step": 1,
            "evidence_sha256": step_evidence_sha256(step),
            "quality_review": {"reviewer": "独立评审", "intent_fulfilled": True,
                               "intent": 5, "continuity": 5, "independent_use": 5,
                               "reason": "请求与保存结果一致。"}}


def test_review_is_bound_to_selected_run_without_mutating_raw_results():
    target, old = result(), result("old")
    merged = apply_quality_reviews([old, target], [review_for(target)], "fixed")
    assert len(merged) == 1 and merged[0]["run_id"] == "fixed"
    assert merged[0]["steps"][0]["quality_review"]["reviewer"] == "独立评审"
    assert target["steps"][0]["quality_review"]["reviewer"] is None


def test_review_rejects_changed_evidence_and_duplicate_attempts():
    target = result()
    review = review_for(target)
    review["evidence_sha256"] = "wrong"
    with pytest.raises(ValueError, match="哈希"):
        apply_quality_reviews([target], [review], "fixed")
    with pytest.raises(ValueError, match="重复实例"):
        selected_run([target, json.loads(json.dumps(target))], "fixed")


def test_review_rejects_duplicate_or_unexpected_review_rows():
    target = result()
    review = review_for(target)
    with pytest.raises(ValueError, match="重复独立评审"):
        apply_quality_reviews([target], [review, dict(review)], "fixed")
    unexpected = {**review, "case_id": "missing"}
    with pytest.raises(ValueError, match="不存在"):
        apply_quality_reviews([target], [unexpected], "fixed")


def test_reviewed_derivative_amends_only_content_checks_on_unchanged_scenes():
    target = result()
    target["steps"][0].update({
        "before": {"scene": [{"id": 4, "prompt": "旧文本", "prompt_params": {}}]},
        "after": {"scene": [{"id": 4, "prompt": "旧文本", "prompt_params": {}}]},
        "hard_failures": ["scene:4: current definition missing for 林岚", "scene:4: protected fields changed"],
    })
    merged = apply_quality_reviews([target], [review_for(target)], "fixed")
    step = merged[0]["steps"][0]
    assert step["hard_failures"] == ["scene:4: protected fields changed"]
    assert step["evaluation_amendments"][0]["removed_raw_hard_failures"] == [
        "scene:4: current definition missing for 林岚"
    ]
