#!/usr/bin/env python3
"""Run the first executable checkpoint and persist evidence."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def next_checkpoint() -> str | None:
    """Return the first incomplete checkpoint from the repository state."""
    gate_path = ROOT / "scripts" / "progression_gate.py"
    namespace: dict = {}
    exec(compile(gate_path.read_text(encoding="utf-8"), str(gate_path), "exec"), namespace)
    text = (ROOT / "CHECKPOINTS.md").read_text(encoding="utf-8")
    item = namespace["first_incomplete"](text)
    return item[0] if item else None


def run_phase_2_1(output: Path, seed: int, generations: int, population: int) -> int:
    command = [
        sys.executable, str(ROOT / "scripts" / "run_phase_2_1.py"),
        "--seed", str(seed), "--generations", str(generations),
        "--population", str(population), "--output", str(output),
    ]
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    if completed.returncode != 0 and not output.exists():
        output.write_text(json.dumps({
            "checkpoint": "2.1", "status": "failed",
            "command": command, "stderr": completed.stderr,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return completed.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Execute the next level checkpoint")
    parser.add_argument("--checkpoint", default="auto")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--generations", type=int, default=12)
    parser.add_argument("--population", type=int, default=24)
    args = parser.parse_args()
    checkpoint = next_checkpoint() if args.checkpoint == "auto" else args.checkpoint
    if checkpoint is None:
        print(json.dumps({"status": "complete", "message": "no incomplete checkpoint"}))
        return 0
    if checkpoint != "2.1":
        print(f"BLOCKED: no executor registered for checkpoint {checkpoint}")
        return 2

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    evidence = ROOT / "execution-evidence" / "2.1" / f"{stamp}.json"
    rc = run_phase_2_1(evidence, args.seed, args.generations, args.population)
    result = json.loads(evidence.read_text(encoding="utf-8"))
    result["executed_by"] = "scripts/progression_runner.py"
    result["evidence_path"] = str(evidence.relative_to(ROOT))
    evidence.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "checkpoint": checkpoint, "status": result.get("status"),
        "evidence": str(evidence.relative_to(ROOT)), "executor_exit": rc,
    }, ensure_ascii=False, indent=2))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
