from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def load_module(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


recorder = load_module("record_conversation_review", "scripts/record_conversation_review.py")
comparator = load_module("compare_conversation_review", "scripts/compare_conversation_review.py")
exporter = load_module("export_correction_case", "scripts/export_correction_case.py")
evaluator = load_module("evaluate_session_with_claude", "scripts/evaluate_session_with_claude.py")


def make_evaluation(ref="abcdef123456", input_hash="sha256:" + "a" * 64):
    axes = []
    for axis in evaluator.AXES:
        axes.append({
            "axis": axis,
            "status": "partial",
            "reason": "モデルの短い理由",
            "evidence_positions": [2],
            "evidence_spans": [{"position": 2, "start": 0, "end": 10, "role": "assistant", "excerpt": "以前の回答抜粋"}],
        })
    return {
        "schema_version": 2,
        "evaluation_ref": ref,
        "input_hash": input_hash,
        "axes": axes,
        "trajectory": {
            "question_initial": {"summary": "開始時", "evidence_spans": [{"position": 1, "start": 0, "end": 10, "role": "user", "excerpt": "最初の問い"}], "unobservable_reason": None},
            "question_current": {"summary": "現在", "evidence_spans": [{"position": 4, "start": 0, "end": 10, "role": "assistant", "excerpt": "現在の問い"}], "unobservable_reason": None},
            "question_changes": [{
                "change_id": "update-001", "before": "以前", "after": "以後",
                "observed_order": "user_judgment_agent_structuring",
                "event_positions": {"evidence": [], "agent_update": [4], "user_judgment": [3]},
                "evidence_spans": [
                    {"position": 3, "start": 0, "end": 10, "role": "user", "excerpt": "訂正の短い抜粋"},
                    {"position": 4, "start": 0, "end": 10, "role": "assistant", "excerpt": "修正の短い抜粋"},
                ],
                "cause_hypothesis": {"summary": "ユーザー方向づけの可能性", "evidence_spans": []},
                "causal_review": {"review_status": "pending", "verdict": None, "reason": None},
                "decision_impact": None, "next_validation": None, "outcome": "unknown",
            }],
        },
    }


class ConversationReviewTests(unittest.TestCase):
    def _write_evaluation(self, directory: Path):
        directory.mkdir(parents=True)
        evaluation = make_evaluation(ref=directory.name)
        (directory / "evaluation.json").write_text(json.dumps(evaluation), encoding="utf-8")
        return evaluation

    def test_review_starts_pending_and_records_one_axis_without_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "abcdef123456"
            evaluation = self._write_evaluation(directory)
            result = recorder.record_axis(directory, "evidence_driven_update", "fail", "訂正後まで方針を直さなかった")
            self.assertEqual(result["status"], "RECORDED")
            review = json.loads((directory / "review.json").read_text(encoding="utf-8"))
            self.assertEqual(review["input_hash"], evaluation["input_hash"])
            self.assertEqual(sum(x["review_status"] == "pending" for x in review["axes"]), 5)
            review_schema = json.loads((ROOT / "schemas" / "conversation-review-human-v2.schema.json").read_text(encoding="utf-8"))
            self.assertEqual(set(review), set(review_schema["properties"]))
            self.assertEqual(set(review["axes"][0]), set(review_schema["$defs"]["axis"]["properties"]))
            self.assertEqual(review["causal_reviews"][0]["review_status"], "pending")
            with self.assertRaisesRegex(ValueError, "already reviewed"):
                recorder.record_axis(directory, "evidence_driven_update", "partial", "更新")

    def test_causal_review_is_separate_from_axis_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "abcdef123456"
            self._write_evaluation(directory)
            recorder.record_causal(directory, "update-001", "rejected", "順序は合うが原因は断定できない")
            review = json.loads((directory / "review.json").read_text(encoding="utf-8"))
            self.assertEqual(review["causal_reviews"][0]["verdict"], "rejected")
            self.assertTrue(all(item["review_status"] == "pending" for item in review["axes"]))

    def test_comparison_excludes_pending_and_nulls_denominator_when_none_reviewed(self):
        evaluation = make_evaluation()
        review = recorder._new_review(evaluation)
        result = comparator.compare_records(evaluation, review)
        self.assertEqual(result["axis_count"], 0)
        self.assertEqual(result["pending_axis_count"], 6)
        self.assertIsNone(result["agreement_rate"])
        self.assertEqual(result["interpretation_boundary"]["promotion_decision"], "not_authorized")
        comparison_schema = json.loads((ROOT / "schemas" / "conversation-review-comparison-v2.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(set(result), set(comparison_schema["properties"]))
        self.assertEqual(set(result["interpretation_boundary"]), set(comparison_schema["properties"]["interpretation_boundary"]["properties"]))

    def test_comparison_classifies_only_answered_axis_and_checks_hash(self):
        evaluation = make_evaluation()
        review = recorder._new_review(evaluation)
        review["axes"][1].update({"review_status": "recorded", "status": "fail", "reason": "未反映"})
        result = comparator.compare_records(evaluation, review)
        self.assertEqual(result["axis_count"], 1)
        self.assertEqual(result["pending_axis_count"], 5)
        self.assertEqual(result["axes"][1]["comparison"], "overcall")
        review["input_hash"] = "sha256:" + "b" * 64
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            comparator.compare_records(evaluation, review)

    def test_case_requires_recorded_human_failure_and_keeps_run_unapproved(self):
        evaluation = make_evaluation()
        review = recorder._new_review(evaluation)
        review["axes"][1].update({"review_status": "recorded", "status": "fail", "reason": "ユーザー訂正後にのみ更新した"})
        case = exporter.build_case(
            evaluation, review, axis="evidence_driven_update", target_position=2,
            correction_summary="ユーザーの訂正を受けて方向を戻した",
            expected_behavior="ユーザーの明示した判断目的へ更新する",
        )
        self.assertEqual(case["case_status"], "candidate_pending_context_review")
        self.assertEqual(case["execution_status"], "not_run")
        self.assertEqual(case["approval_status"], "pending")
        self.assertEqual(case["regression_input"]["messages_before_target"][0]["position"], 1)
        self.assertNotIn("訂正の短い抜粋", json.dumps(case["regression_input"], ensure_ascii=False))
        self.assertFalse(case["regression_input"]["after_correction_answer_or_label_included"])
        schema = json.loads((ROOT / "schemas" / "correction-case-v1.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(set(case), set(schema["properties"]))
        self.assertEqual(set(case["source"]), set(schema["properties"]["source"]["properties"]))

    def test_case_rejects_pending_or_non_assistant_target_and_sensitive_text(self):
        evaluation = make_evaluation()
        review = recorder._new_review(evaluation)
        with self.assertRaisesRegex(ValueError, "human-recorded fail"):
            exporter.build_case(evaluation, review, axis="evidence_driven_update", target_position=2, correction_summary="訂正", expected_behavior="修正")
        review["axes"][1].update({"review_status": "recorded", "status": "fail", "reason": "失敗"})
        with self.assertRaisesRegex(ValueError, "assistant evidence"):
            exporter.build_case(evaluation, review, axis="evidence_driven_update", target_position=3, correction_summary="訂正", expected_behavior="修正")
        with self.assertRaisesRegex(ValueError, "excluded"):
            exporter.build_case(evaluation, review, axis="evidence_driven_update", target_position=2, correction_summary="api_key=abcdef123456789", expected_behavior="修正")

    def test_schema_documents_are_valid_json_with_closed_top_level_objects(self):
        for name in ("conversation-review-v2.schema.json", "conversation-review-human-v2.schema.json", "conversation-review-comparison-v2.schema.json", "correction-case-v1.schema.json"):
            schema = json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))
            self.assertEqual(schema["type"], "object")
            self.assertFalse(schema["additionalProperties"])
            self.assertTrue(schema["required"])


if __name__ == "__main__":
    unittest.main()
