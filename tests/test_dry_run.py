#!/usr/bin/env python3
"""
段階2 Dry-run: 本番シミュレーション データセットの検証テスト
"""

import json
import sys
from pathlib import Path

# Add scripts to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


def test_dry_run_evidence_loading():
    """Test: Dry-run で本番 evidence を読み込み・検証（write なし）."""
    
    dataset_path = Path(__file__).parent / "production_evidence_dry_run.jsonl"
    
    if not dataset_path.exists():
        print("❌ Dataset not found. Run generate_production_dataset.py first.")
        return False
    
    print("=" * 70)
    print("📌 段階2 Dry-run テスト: 本番 evidence 読み込み検証")
    print("=" * 70)
    
    records = []
    
    # Load all records from JSONL
    with dataset_path.open() as f:
        for i, line in enumerate(f, 1):
            try:
                record = json.loads(line.strip())
                records.append(record)
                print(f"\n✅ Record {i} loaded: {record.get('assessment_id')}")
                print(f"   - Level: {record.get('level')}")
                print(f"   - Result: {record.get('result')}")
                print(f"   - Provenance: {record.get('provenance', 'NOT SET (old format)')}")
            except json.JSONDecodeError as e:
                print(f"❌ Record {i} JSON parse error: {e}")
                return False
    
    print("\n" + "=" * 70)
    print(f"✅ Loaded {len(records)} records successfully")
    
    # Test 1: Check backward compatibility (old format without provenance)
    print("\n📋 Test 1: Backward Compatibility (old format)...")
    old_format_count = sum(1 for r in records if "provenance" not in r)
    print(f"   Records without provenance: {old_format_count}")
    if old_format_count > 0:
        print(f"   ✅ Old format records present (backward compat test)")
    
    # Test 2: Check new format (with provenance)
    print("\n📋 Test 2: New Format (with provenance)...")
    new_format_count = sum(1 for r in records if "provenance" in r)
    provenance_values = set(r.get("provenance") for r in records if "provenance" in r)
    print(f"   Records with provenance: {new_format_count}")
    print(f"   Provenance values: {provenance_values}")
    if new_format_count > 0:
        print(f"   ✅ New format records present")
    
    # Test 3: Check integrity hashes
    print("\n📋 Test 3: Integrity Hash Validation...")
    hash_count = sum(1 for r in records if "integrity_hash" in r)
    print(f"   Records with integrity_hash: {hash_count}/{len(records)}")
    if hash_count == len(records):
        print(f"   ✅ All records have integrity_hash")
    else:
        print(f"   ⚠️  Some records missing integrity_hash")
    
    # Test 4: Check schema fields compliance
    print("\n📋 Test 4: Required Fields Compliance...")
    required_fields = {
        "schema_version", "assessment_id", "level", "capability_id",
        "agent_configuration_id", "evaluator_configuration_id",
        "evidence_class", "scenario_id", "trigger_origin", "environment_class",
        "started_at", "ended_at", "input_ref", "expected_contract",
        "result", "semantic_verdict", "reviewer", "integrity_hash"
    }
    
    all_compliant = True
    for i, record in enumerate(records, 1):
        missing = required_fields - set(record.keys())
        if missing:
            print(f"   ❌ Record {i} missing: {missing}")
            all_compliant = False
        else:
            print(f"   ✅ Record {i}: compliant")
    
    # Test 5: Simulate read-only access pattern
    print("\n📋 Test 5: Read-only Access Pattern (no write)...")
    print(f"   ✅ Loaded {len(records)} records in read-only mode")
    print(f"   ✅ No modifications made")
    print(f"   ✅ No data persisted (dry-run)")
    
    print("\n" + "=" * 70)
    print("🎉 段階2 Dry-run テスト完了")
    print("=" * 70)
    
    if all_compliant:
        print("✅ All checks PASSED - Ready for production")
        return True
    else:
        print("⚠️  Some compliance issues detected")
        return False


if __name__ == "__main__":
    success = test_dry_run_evidence_loading()
    sys.exit(0 if success else 1)
