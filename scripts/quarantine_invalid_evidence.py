#!/usr/bin/env python3
"""Quarantine fully invalid persisted Evidence without rewriting its bytes.

The active evaluator scans ``operational-evidence`` and ``evaluation-reports``.
This tool moves only files whose Evidence records are all invalid under the
current Promotion Gate. Mixed files remain active for manual review.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
QUARANTINE_DIRNAME = "evidence-quarantine"
MANIFEST_NAME = "manifest.json"
MANIFEST_SCHEMA_VERSION = 1


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def reason_category(error: str) -> str:
    if "agent_configuration_id must" in error:
        return "invalid_agent_configuration_id_format"
    if "agent_configuration_id mismatch" in error:
        return "stale_agent_configuration"
    if "evaluator_configuration_id must" in error:
        return "invalid_evaluator_configuration_id_format"
    if "evaluator_configuration_id mismatch" in error:
        return "stale_evaluator_configuration"
    if "invalid trigger_origin" in error:
        return "invalid_trigger_origin"
    if "integrity_hash" in error:
        return "integrity_hash_mismatch"
    if "invalid JSON" in error:
        return "invalid_json"
    return "evidence_contract_error"


def _read_candidates(path: Path) -> list[tuple[int, Any, list[str]]]:
    if path.suffix == ".jsonl":
        candidates: list[tuple[int, Any, list[str]]] = []
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                candidates.append((line_number, json.loads(line), []))
            except json.JSONDecodeError as exc:
                candidates.append((line_number, None, [f"invalid JSON: {exc.msg}"]))
        return candidates

    try:
        return [(1, json.loads(path.read_text(encoding="utf-8")), [])]
    except json.JSONDecodeError as exc:
        return [(1, None, [f"invalid JSON: {exc.msg}"])]


def inspect_file(root: Path, path: Path, promotion: Any, validator: Any, expected_id: str | None) -> dict[str, Any] | None:
    candidates = _read_candidates(path)
    if not candidates:
        return None

    evidence_items: list[tuple[int, list[str]]] = []
    ignored_count = 0
    for line_number, value, parse_errors in candidates:
        if parse_errors:
            evidence_items.append((line_number, parse_errors))
            continue
        if not isinstance(value, dict):
            evidence_items.append((line_number, ["evidence record must be an object"]))
            continue
        if "evidence_class" not in value:
            ignored_count += 1
            continue
        evidence_items.append(
            (
                line_number,
                promotion.validate_persisted_record(value, validator, expected_id),
            )
        )

    if not evidence_items or ignored_count or any(not errors for _, errors in evidence_items):
        return None

    reason_counts: Counter[str] = Counter()
    for _, errors in evidence_items:
        for error in errors:
            reason_counts[reason_category(error)] += 1

    relative = path.relative_to(root)
    quarantine_path = Path(QUARANTINE_DIRNAME) / relative
    return {
        "source_path": str(relative),
        "quarantine_path": str(quarantine_path),
        "source_sha256": sha256_file(path),
        "record_count": len(evidence_items),
        "line_numbers": [line_number for line_number, _ in evidence_items],
        "reason_counts": dict(sorted(reason_counts.items())),
    }


def build_plan(root: Path) -> list[dict[str, Any]]:
    root = root.resolve()
    promotion = load_module("_promotion_gate_for_quarantine", ROOT / "scripts" / "promotion_gate.py")
    validator = promotion.load_module("_stage1_validator_for_quarantine", promotion.VALIDATOR)
    expected_id, configuration_error = promotion.expected_evaluator_configuration_id(root)
    if configuration_error:
        raise RuntimeError(configuration_error)

    plan: list[dict[str, Any]] = []
    for directory_name in ("operational-evidence", "evaluation-reports"):
        directory = root / directory_name
        if not directory.exists():
            continue
        for path in sorted(directory.rglob("*")):
            if path.suffix not in {".json", ".jsonl"} or not path.is_file():
                continue
            entry = inspect_file(root, path, promotion, validator, expected_id)
            if entry is not None:
                plan.append(entry)
    return plan


def _manifest_path(root: Path) -> Path:
    return root / QUARANTINE_DIRNAME / MANIFEST_NAME


def _load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "entries": [],
        }
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ValueError("unsupported quarantine manifest")
    if not isinstance(value.get("entries"), list):
        raise ValueError("quarantine manifest entries must be an array")
    return value


def apply_plan(root: Path, plan: list[dict[str, Any]]) -> dict[str, Any]:
    root = root.resolve()
    quarantine_root = root / QUARANTINE_DIRNAME
    manifest_path = quarantine_root / MANIFEST_NAME
    manifest = _load_manifest(manifest_path)
    existing = {entry.get("source_path"): entry for entry in manifest["entries"]}

    for entry in plan:
        source = root / entry["source_path"]
        destination = root / entry["quarantine_path"]
        if not source.exists():
            if destination.exists() and sha256_file(destination) == entry["source_sha256"]:
                existing.setdefault(entry["source_path"], entry)
                continue
            raise FileNotFoundError(f"source disappeared before quarantine: {source}")
        if destination.exists():
            raise FileExistsError(f"quarantine destination already exists: {destination}")
        if entry["source_path"] in existing:
            raise ValueError(f"source already recorded in manifest: {entry['source_path']}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        if sha256_file(destination) != entry["source_sha256"]:
            raise IOError(f"quarantine hash mismatch after move: {destination}")
        existing[entry["source_path"]] = entry

    manifest["entries"] = [existing[key] for key in sorted(existing)]
    manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
    manifest["summary"] = {
        "file_count": len(manifest["entries"]),
        "record_count": sum(int(entry["record_count"]) for entry in manifest["entries"]),
    }
    quarantine_root.mkdir(parents=True, exist_ok=True)
    temporary = manifest_path.with_suffix(".tmp")
    temporary.write_text(canonical_json(manifest), encoding="utf-8")
    temporary.replace(manifest_path)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Quarantine fully invalid persisted Evidence")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--apply", action="store_true", help="move planned files and write the manifest")
    args = parser.parse_args()

    root = args.root.resolve()
    plan = build_plan(root)
    print(json.dumps({
        "mode": "apply" if args.apply else "dry_run",
        "planned_file_count": len(plan),
        "planned_record_count": sum(int(entry["record_count"]) for entry in plan),
        "planned_files": plan,
    }, ensure_ascii=False, indent=2))
    if not args.apply:
        return 0

    manifest = apply_plan(root, plan)
    print(json.dumps({
        "status": "PASS",
        "manifest": str(_manifest_path(root)),
        "quarantined_file_count": manifest["summary"]["file_count"],
        "quarantined_record_count": manifest["summary"]["record_count"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
