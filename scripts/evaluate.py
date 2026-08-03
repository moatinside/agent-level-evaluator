#!/usr/bin/env python3
"""
Agent Level Self-Evaluation Script

依存ゼロ（Python標準ライブラリのみ）。
6軸のアンケートに答えると、現在のエージェントレベルを推定する。

自己申告時に evals/run_evals.py を同時実行し、客観指標（スキル単位の
機械的検証結果）をレポートに埋め込む。主観スコアを客観数値で裏付ける。

Usage:
    python3 evaluate.py             # インタラクティブモード（evals 同時実行）
    python3 evaluate.py --quick     # クイックモード（すべて50と仮定・evals 同時実行）
    python3 evaluate.py --no-evals  # スキル評価 (evals) をスキップ
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# evals/run_evals.py（リポジトリルート相対）
EVALS_SCRIPT = Path(__file__).resolve().parent.parent / "evals" / "run_evals.py"

# 6軸の定義
AXES = [
    {
        "id": "ensemble",
        "name": "アンサンブル推論 (Level 4)",
        "level": 4,
        "prompt": "複数の視点（批判的・創造的・現実的）で同時に思考し、結果を統合できますか？",
        "criteria": [
            "0-30: 単一視点のみ。複数視点で考える習慣がない",
            "31-60: 意識すれば複数視点で考えられるが、統合は不得意",
            "61-85: 複数視点で考え、統合してより良い回答を生成できる",
            "86-100: 常に複数視点で思考し、統合プロセスが自然に動作する",
        ],
    },
    {
        "id": "self_validate",
        "name": "自己修正ループ (Level 5)",
        "level": 5,
        "prompt": "出力する前に自分の回答を検証し、矛盾や抜けを検出・修正できますか？",
        "criteria": [
            "0-30: 出力後の見直しをしない",
            "31-60: 指摘されて初めて気付く。自分では検出が難しい",
            "61-85: 出力前にある程度の矛盾を検出できる。チェックリストがあれば確実",
            "86-100: 出力前に体系的に検証し、ほとんどの問題を事前に修正する",
        ],
    },
    {
        "id": "agentic_search",
        "name": "Agentic Search (Level 6)",
        "level": 6,
        "prompt": "ツール（Web検索・API・ファイル読み取り等）を使って自律的に情報収集できますか？",
        "criteria": [
            "0-30: ツールを使えない。知識は学習時点で固定",
            "31-60: 指示されて初めてツールを使う。自分からは使わない",
            "61-85: ツールを自律的に使って情報収集できる",
            "86-100: 複数のツールを組み合わせて戦略的に情報収集する",
        ],
    },
    {
        "id": "self_evolution",
        "name": "自己進化 (Level 7)",
        "level": 7,
        "prompt": "ユーザーからのフィードバックを能動的に学習し、同じミスを繰り返さない仕組みを持っていますか？",
        "criteria": [
            "0-30: フィードバックをその場では反映するが、次回は忘れる",
            "31-60: 同じ指摘を2-3回繰り返されてようやく覚える",
            "61-85: 1回の指摘で記憶し、次回から反映できる",
            "86-100: 指摘を分析し、自分で再発防止の仕組みを構築する",
        ],
    },
    {
        "id": "routing",
        "name": "動的ルーティング (Level 3)",
        "level": 3,
        "prompt": "タスクの種類や状況に応じて、適切なアプローチやツールを選択できますか？",
        "criteria": [
            "0-30: 全タスクを同じ方法で処理する",
            "31-60: 大まかな分類はできるが、適切なツール選択はできない",
            "61-85: タスクに応じてアプローチを変えられる",
            "86-100: 状況を分析し、最適なアプローチを動的に選択する",
        ],
    },
    {
        "id": "workflow",
        "name": "ワークフロー実行 (Level 2)",
        "level": 2,
        "prompt": "複数ステップの手順を順序正しく、抜けなく実行できますか？",
        "criteria": [
            "0-30: ステップを飛ばしたり順序を間違えたりする",
            "31-60: 簡単な手順は守れるが、複雑になると抜けが出る",
            "61-85: 複数ステップの手順を正確に実行できる",
            "86-100: 手順を超えて、次のステップを予測して準備できる",
        ],
    },
]


def ask_score(axis: dict) -> int:
    """1軸のスコアをユーザーに質問する"""
    print(f"\n{'='*60}")
    print(f"【{axis['name']}】")
    print(f"{'='*60}")
    print(f"\n{axis['prompt']}\n")
    for c in axis["criteria"]:
        print(f"  {c}")
    while True:
        try:
            val = int(input(f"\nスコア (0-100) → "))
            if 0 <= val <= 100:
                return val
            print("0〜100の範囲で入力してください")
        except ValueError:
            print("数値を入力してください")
        except (EOFError, KeyboardInterrupt):
            print()
            return -1


def run_skill_evals() -> list | None:
    """
    evals/run_evals.py --json をサブプロセスで実行し、客観指標を取得する。
    実行不可能な場合は None を返す（自己評価は継続する）。
    """
    if not EVALS_SCRIPT.exists():
        print("\n⚠ evals/run_evals.py が見つからないため、スキル評価をスキップします")
        return None
    print("\n🔍 スキル評価 (evals) を同時実行中...")
    try:
        proc = subprocess.run(
            [sys.executable, str(EVALS_SCRIPT), "--json"],
            capture_output=True, text=True, timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"⚠ スキル評価の実行に失敗しました: {e}")
        return None
    try:
        return json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError):
        print("⚠ スキル評価の出力を解析できませんでした")
        return None


def format_evals_section(eval_results: list | None) -> str:
    """スキル評価結果をレポート用マークダウンに整形する。"""
    if not eval_results:
        return ""
    lines = ["", "## 客観指標 (Skill Evals)", ""]
    lines.append("自己申告と同時に実行したスキル単位の機械的検証結果：")
    lines.append("")
    lines.append("| スキル | PASS/合計 | スキル実体 |")
    lines.append("|--------|-----------|-----------|")
    total_passed = total_all = 0
    for r in eval_results:
        tests = r.get("happy", []) + r.get("negative", [])
        passed = sum(1 for t in tests if t.get("pass"))
        total_all += len(tests)
        total_passed += passed
        found = "✅ あり" if r.get("skill_found") else "❌ なし"
        lines.append(f"| {r.get('skill', '?')} | {passed}/{len(tests)} | {found} |")
    lines.append("")
    lines.append(f"**evals 総合: {total_passed}/{total_all} PASS**")
    if total_all and total_passed == total_all:
        lines.append("→ 全スキルが客観検証を通過。自己申告は機械的裏付けあり。")
    else:
        lines.append("→ 不合格あり。スキル品質を改善してから再評価してください。")
    return "\n".join(lines)


def determine_level(scores: dict) -> int:
    """スコアから総合レベルを判定"""
    if scores.get("self_evolution", 0) >= 60:
        return 7
    if scores.get("agentic_search", 0) >= 60:
        return 6
    if scores.get("self_validate", 0) >= 60:
        return 5
    if scores.get("ensemble", 0) >= 60:
        return 4
    if scores.get("routing", 0) >= 60:
        return 3
    if scores.get("workflow", 0) >= 60:
        return 2
    return 1


def generate_report(scores: dict, level: int, output_path: str = "", eval_results: list | None = None):
    """評価レポートを生成"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    report = f"""# Agent Level Evaluation Report

**評価日時:** {now}
**方法:** 6軸セルフアセスメント + スキル機械検証 (evals)

## スコア
"""
    for axis in AXES:
        sid = axis["id"]
        bar = "█" * (scores.get(sid, 0) // 10) + "░" * (10 - scores.get(sid, 0) // 10)
        report += f"| {axis['name']:<30s} | {scores.get(sid, 0):>3d}/100 | {bar} |\n"
    
    report += f"""
## 総合レベル: Level {level}

| Level | 到達 | 条件 |
|-------|------|------|
"""
    for lv in range(1, 10):
        if lv == 1:
            reached = "✅" if level >= 1 else "—"
            condition = "デフォルト"
        elif lv == 2:
            reached = "✅" if level >= 2 else ("❌" if level < 2 else "")
            condition = "ワークフロー ≥ 60"
        elif lv == 3:
            reached = "✅" if level >= 3 else ("❌" if level < 2 else "")
            condition = "ルーティング ≥ 60"
        elif lv == 4:
            reached = "✅" if level >= 4 else ("❌" if level < 2 else "")
            condition = "アンサンブル ≥ 60"
        elif lv == 5:
            reached = "✅" if level >= 5 else ("❌" if level < 2 else "")
            condition = "自己修正 ≥ 60"
        elif lv == 6:
            reached = "✅" if level >= 6 else ("❌" if level < 2 else "")
            condition = "Agentic Search ≥ 60"
        elif lv == 7:
            reached = "✅" if level >= 7 else ("❌" if level < 2 else "")
            condition = "自己進化 ≥ 60"
        else:
            reached = "⏳" if level >= 7 else "—"
            condition = "Level 7達成後"
        report += f"| {lv} | {reached} | {condition} |\n"
    
    # 客観指標 (Skill Evals)
    report += format_evals_section(eval_results)

    # 次のステップ
    report += "\n## 次のステップ\n\n"
    next_level = level + 1
    if next_level <= 7:
        for axis in AXES:
            if axis["level"] == next_level:
                report += f"1. **{axis['name']}** を60以上に上げる（現在: {scores.get(axis['id'], 0)}）\n"
                report += f"2. CHECKPOINTS.md の関連Phaseを確認する\n"
                break
    elif level >= 7:
        report += "Level 7達成。次は Phase 2（発見ループ）または Phase 3（パラダイムシフト）を目指す。\n"
    
    if output_path:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w") as f:
            f.write(report)
        print(f"\nレポート保存: {output_path}")
    
    return report


def quick_mode(run_evals: bool = True):
    """クイックモード：全軸50と仮定"""
    scores = {a["id"]: 50 for a in AXES}
    level = determine_level(scores)
    eval_results = run_skill_evals() if run_evals else None
    print(generate_report(scores, level, eval_results=eval_results))
    return scores, level


def interactive_mode(run_evals: bool = True):
    """対話モード：1軸ずつ質問"""
    scores = {}
    print("Agent Level Evaluator — 対話モード")
    print("各能力を0〜100で自己評価してください。")
    print()
    
    for axis in AXES:
        score = ask_score(axis)
        if score < 0:
            print("中断")
            return {}, 0
        scores[axis["id"]] = score
    
    level = determine_level(scores)
    eval_results = run_skill_evals() if run_evals else None
    print()
    print("=" * 60)
    print(generate_report(scores, level, eval_results=eval_results))
    return scores, level


def main():
    run_evals = "--no-evals" not in sys.argv
    if "--quick" in sys.argv:
        quick_mode(run_evals=run_evals)
    elif "--help" in sys.argv or "-h" in sys.argv:
        print("Usage: python3 evaluate.py [--quick] [--no-evals]")
        print("  (no flag)    インタラクティブモード（evals 同時実行）")
        print("  --quick      クイックモード（全軸50で仮評価・evals 同時実行）")
        print("  --no-evals   スキル評価 (evals) をスキップ")
    else:
        interactive_mode(run_evals=run_evals)


if __name__ == "__main__":
    main()
