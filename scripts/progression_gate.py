#!/usr/bin/env python3
"""Report the next required checkpoint and whether execution evidence exists.

This is intentionally conservative: documentation or a self-reported score is
not evidence of execution. The command exits non-zero while work is pending.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

CHECKPOINT_RE = re.compile(r"^###\s+([0-9]+\.[0-9]+)\s+(.+)$", re.MULTILINE)
DONE_RE = re.compile(
    r"^(?:###\s+|\s*[├└]─\s*)([0-9]+\.[0-9]+).*?(?:✅|\[x\])",
    re.MULTILINE,
)


def first_incomplete(text: str) -> tuple[str, str] | None:
    done_ids = {m.group(1) for m in DONE_RE.finditer(text)}
    for match in CHECKPOINT_RE.finditer(text):
        checkpoint_id = match.group(1)
        if checkpoint_id not in done_ids:
            return checkpoint_id, match.group(2).strip()
    return None


def has_evidence(root: Path, checkpoint_id: str) -> bool:
    """Evidence must be in a dedicated directory and mention the checkpoint."""
    for directory in (root / "execution-evidence", root / "evaluation-reports"):
        if not directory.is_dir():
            continue
        for path in directory.rglob("*"):
            if path.is_file() and checkpoint_id in path.read_text(
                encoding="utf-8", errors="replace"
            ):
                return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Show the next level checkpoint")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    args = parser.parse_args()
    root = Path(args.root).resolve()
    checkpoints = root / "CHECKPOINTS.md"
    if not checkpoints.is_file():
        print(f"ERROR: CHECKPOINTS.md not found: {checkpoints}")
        return 2

    next_item = first_incomplete(checkpoints.read_text(encoding="utf-8"))
    if next_item is None:
        print("STATUS: complete — no incomplete checkpoint found")
        return 0

    checkpoint_id, title = next_item
    evidence = has_evidence(root, checkpoint_id)
    print(f"STATUS: pending — checkpoint {checkpoint_id}: {title}")
    print(f"EXECUTION_PLAN: required for {checkpoint_id}")
    print(f"EXECUTION_EVIDENCE: {'found' if evidence else 'missing'}")
    print("NEXT_ACTION: create or execute the smallest plan for this checkpoint")
    print("COMPLETION_RULE: do not mark complete without artifact, test, and log")
    return 1


if __name__ == "__main__":
    sys.exit(main())
