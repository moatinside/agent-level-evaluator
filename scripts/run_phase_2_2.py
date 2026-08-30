#!/usr/bin/env python3
"""Deterministic Phase 2.2 novelty scoring baseline."""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[一-龯々ぁ-んァ-ヶー]+")

CASES = [
    {
        "id": "similar-1",
        "idea": "automatically validate deployment configuration and detect configuration errors",
        "label": "existing",
    },
    {
        "id": "similar-2",
        "idea": "detect deployment configuration mistakes using automated validation",
        "label": "existing",
    },
    {
        "id": "novel-1",
        "idea": "optimize evacuation shelter power allocation using weather forecasts",
        "label": "novel",
    },
    {
        "id": "novel-2",
        "idea": "discover new battery chemistry through molecular simulation",
        "label": "novel",
    },
    {
        "id": "similar-3",
        "idea": "automated checks for deployment settings and configuration failures",
        "label": "existing",
    },
]

EXISTING = [
    "automated deployment configuration validation detects configuration errors",
    "monitor deployment settings and report configuration failures",
]


def tokens(text: str) -> set[str]:
    return {token.lower() for token in TOKEN_RE.findall(text)}


def jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def novelty(idea: str) -> tuple[float, float, str]:
    idea_tokens = tokens(idea)
    similarities = [jaccard(idea_tokens, tokens(item)) for item in EXISTING]
    maximum = max(similarities, default=0.0)
    score = 1.0 - maximum
    label = "existing" if maximum >= 0.25 else "novel"
    return maximum, score, label


def run() -> dict:
    results = []
    for case in CASES:
        similarity, score, predicted = novelty(case["idea"])
        results.append({
            **case,
            "max_similarity": similarity,
            "novelty_score": score,
            "predicted": predicted,
            "correct": predicted == case["label"],
        })
    correct = sum(1 for result in results if result["correct"])
    accuracy = correct / len(results) if results else 0.0
    return {
        "checkpoint": "2.2",
        "experiment": "deterministic-novelty-baseline",
        "status": "passed" if accuracy >= 0.8 else "failed",
        "method": "token-set-jaccard",
        "threshold": 0.25,
        "cases": results,
        "accuracy": accuracy,
        "acceptance": {
            "separates_similar_and_novel": all(
                r["predicted"] == r["label"] for r in results
            ),
            "accuracy_at_least_80_percent": accuracy >= 0.8,
            "deterministic": True,
        },
        "executed_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run()
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
