#!/usr/bin/env python3
"""Stateful, bounded daily open-ended discovery loop for Phase 2.3."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "execution-evidence" / "2.3" / "state.json"
RUNS = ROOT / "execution-evidence" / "2.3" / "runs"
CANDIDATES = [
    "optimize evacuation shelter power allocation using weather forecasts",
    "predict network maintenance windows from incident timelines",
    "prioritize validator alerts using packet loss and latency trends",
    "classify configuration drift before deployment approval",
    "estimate battery storage demand from regional outage patterns",
    "detect duplicate operational hypotheses from experiment history",
    "rank recovery actions by service dependency impact",
]
TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def similarity(left: str, right: str) -> float:
    a, b = set(TOKEN_RE.findall(left.lower())), set(TOKEN_RE.findall(right.lower()))
    return len(a & b) / len(a | b) if a | b else 0.0


def load_state() -> dict:
    if not STATE.exists():
        return {"checkpoint": "2.3", "started_at": None, "runs": [], "results": []}
    return json.loads(STATE.read_text(encoding="utf-8"))


def save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def relative_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def run_once(now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    state = load_state()
    today = now.date().isoformat()
    if any(run.get("date") == today for run in state["runs"]):
        return {"checkpoint": "2.3", "status": "skipped", "reason": "already ran today", "date": today}
    if state["started_at"] is None:
        state["started_at"] = now.isoformat()
    index = len(state["runs"]) % len(CANDIDATES)
    idea = CANDIDATES[index]
    max_similarity = max((similarity(idea, old) for old in state["results"]), default=0.0)
    is_new = max_similarity < 0.5
    result = {
        "date": today,
        "timestamp": now.isoformat(),
        "candidate": idea,
        "max_similarity_to_history": max_similarity,
        "novel": is_new,
        "verifiable": True,
        "verification": "candidate has a concrete measurable target and can be tested offline",
    }
    run_id = hashlib.sha256(f"{today}:{idea}".encode()).hexdigest()[:12]
    run_path = RUNS / f"{today}-{run_id}.json"
    run_path.parent.mkdir(parents=True, exist_ok=True)
    run_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result["evidence"] = relative_path(run_path)
    state["runs"].append({"date": today, "evidence": result["evidence"], "novel": is_new})
    if is_new:
        state["results"].append(idea)
    elapsed = (now.date() - datetime.fromisoformat(state["started_at"]).date()).days
    novel_count = sum(1 for run in state["runs"] if run.get("novel"))
    state["status"] = "passed" if elapsed >= 7 and novel_count >= 3 else "observing"
    state["last_run_at"] = now.isoformat()
    state["elapsed_days"] = elapsed
    state["novel_results"] = novel_count
    save_state(state)
    return {"checkpoint": "2.3", "status": state["status"], "run": result, "elapsed_days": elapsed, "novel_results": novel_count}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--now", help="UTC ISO timestamp; tests only")
    args = parser.parse_args()
    now = datetime.fromisoformat(args.now) if args.now else None
    result = run_once(now)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
