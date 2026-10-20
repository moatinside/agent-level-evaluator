#!/usr/bin/env python3
"""
段階2: Dry-run Test Suite
Production-like evidence dataset を生成して、新コードの検証を実施
"""

import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path


def generate_production_like_evidence():
    """本番環境をシミュレートした evidence サンプル（複数パターン）を生成."""
    
    samples = []
    
    # パターン1: 通常の passed evidence（provenance なし = old format）
    old_format_passed = {
        "schema_version": 1,
        "assessment_id": "assess:prod-001",
        "level": 5,
        "capability_id": "semantic_understanding",
        "capability_contract_version": "1.0",
        "agent_configuration_id": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "evaluator_configuration_id": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "evidence_class": "F",
        "scenario_id": "scenario:prod-comprehension",
        "trigger_origin": "harness",
        "environment_class": "production",
        "execution_mode": "production",
        "started_at": "2026-10-20T08:00:00Z",
        "ended_at": "2026-10-20T08:05:00Z",
        "input_ref": "evidence:input-001",
        "expected_contract": ["semantic_correctness", "response_completeness"],
        "action_trace_ref": "trace:001",
        "result": "passed",
        "semantic_verdict": "not_automatically_determined",
        "acceptance_results": {"semantic_correctness": True, "response_completeness": True},
        "reviewer": "deterministic",
        "reviewed_at": "2026-10-20T08:05:30Z",
        "integrity_hash": "sha256:" + hashlib.sha256(b"evidence-001").hexdigest(),
        # NOTE: provenance field が無い = old format (backward compat test)
    }
    samples.append(old_format_passed)
    
    # パターン2: failed evidence with provenance (new format)
    new_format_failed = {
        "schema_version": 1,
        "assessment_id": "assess:prod-002",
        "level": 3,
        "capability_id": "task_execution",
        "capability_contract_version": "1.0",
        "agent_configuration_id": "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
        "evaluator_configuration_id": "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
        "evidence_class": "O",
        "provenance": "production_runtime",  # New field
        "scenario_id": "scenario:prod-execution",
        "trigger_origin": "hermes",
        "environment_class": "production",
        "execution_mode": "strict",
        "started_at": "2026-10-20T08:10:00Z",
        "ended_at": "2026-10-20T08:12:00Z",
        "input_ref": "evidence:input-002",
        "expected_contract": ["tool_availability", "parameter_validation"],
        "action_trace_ref": "trace:002",
        "result": "failed",
        "semantic_verdict": "not_automatically_determined",
        "acceptance_results": {"tool_availability": False},
        "negative_evidence": [{"reason": "Tool not available"}],
        "reviewer": "deterministic",
        "reviewed_at": "2026-10-20T08:12:30Z",
        "integrity_hash": "sha256:" + hashlib.sha256(b"evidence-002").hexdigest(),
    }
    samples.append(new_format_failed)
    
    # パターン3: inconclusive evidence (fixture_probe provenance)
    fixture_probe_inconclusive = {
        "schema_version": 1,
        "assessment_id": "assess:prod-003",
        "level": 7,
        "capability_id": "reasoning_chain",
        "capability_contract_version": "1.0",
        "agent_configuration_id": "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
        "evaluator_configuration_id": "sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
        "evidence_class": "R",
        "provenance": "fixture_probe",  # Test data
        "scenario_id": "scenario:prod-reasoning",
        "trigger_origin": "harness",
        "environment_class": "sandbox",
        "execution_mode": "shadow",
        "started_at": "2026-10-20T08:20:00Z",
        "ended_at": "2026-10-20T08:25:00Z",
        "input_ref": "evidence:input-003",
        "expected_contract": ["logical_consistency", "premise_accuracy"],
        "result": "inconclusive",
        "semantic_verdict": "not_automatically_determined",
        "reviewer": "independent-agent",
        "reviewed_at": "2026-10-20T08:26:00Z",
        "integrity_hash": "sha256:" + hashlib.sha256(b"evidence-003").hexdigest(),
    }
    samples.append(fixture_probe_inconclusive)
    
    return samples


def save_production_dataset(output_path: Path):
    """Generate and save production-like dataset."""
    
    samples = generate_production_like_evidence()
    
    # Save as JSONL
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as f:
        for sample in samples:
            f.write(json.dumps(sample) + "\n")
    
    print(f"✅ Created production-like dataset: {output_path}")
    print(f"   - Records: {len(samples)}")
    print(f"   - Patterns tested:")
    print(f"     • Old format (no provenance)")
    print(f"     • New format (provenance='production_runtime')")
    print(f"     • Fixture format (provenance='fixture_probe')")
    
    return samples


if __name__ == "__main__":
    dataset_path = Path(__file__).parent / "production_evidence_dry_run.jsonl"
    samples = save_production_dataset(dataset_path)
    
    print(f"\n📊 Dataset Summary:")
    for i, sample in enumerate(samples, 1):
        print(f"   Record {i}: {sample['assessment_id']} - {sample['result']}")
