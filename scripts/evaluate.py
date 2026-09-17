#!/usr/bin/env python3
"""
Agent Level Self-Evaluation Script

依存ゼロ（Python標準ライブラリのみ）。
実行自律性の診断と協働・拡張学習の段階を入力し、2軸の評価レポートを生成する。

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

COLLABORATION_STAGES = [
    "人間の意図受領",
    "判断基準の外化",
    "複数視点の共同統合",
    "批評による修正",
    "問い・対象の拡張",
    "新しい実践の定着・一般化",
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


def determine_execution_level(scores: dict) -> int:
    """実行自律性の連続して確認できたLevelを返す。"""
    if scores.get("workflow", 0) < 60:
        return 1
    if scores.get("routing", 0) < 60:
        return 2
    if scores.get("ensemble", 0) < 60:
        return 3
    if scores.get("self_validate", 0) < 60:
        return 4
    if scores.get("agentic_search", 0) < 60:
        return 5
    if scores.get("self_evolution", 0) < 60:
        return 6
    return 7


def determine_level(scores: dict) -> int:
    """後方互換用。新規レポートでは単一Levelを使用しない。"""
    return determine_execution_level(scores)


def ask_collaboration_stage() -> int:
    """協働・拡張学習の観測段階を質問する。"""
    print("\\n協働・拡張学習の観測段階を選択してください。")
    for i, stage in enumerate(COLLABORATION_STAGES, 1):
        print(f"  {i}: {stage}")
    print("  0: 未観測")
    while True:
        try:
            value = int(input("\\n段階 (0-6) → "))
            if 0 <= value <= len(COLLABORATION_STAGES):
                return value
            print(f"0〜{len(COLLABORATION_STAGES)}の範囲で入力してください")
        except ValueError:
            print("数値を入力してください")
        except (EOFError, KeyboardInterrupt):
            print()
            return -1


def generate_report(scores: dict, level: int, output_path: str = "", eval_results: list | None = None, collaboration_stage: int = 0):
    """2軸評価レポートを生成する。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    collaboration = (
        COLLABORATION_STAGES[collaboration_stage - 1]
        if 0 < collaboration_stage <= len(COLLABORATION_STAGES)
        else "未観測"
    )

    report = f"""# Agent Level Evaluation Report

**評価日時:** {now}
**方法:** 実行自律性の診断 + 協働・拡張学習の段階評価 + スキル機械検証 (evals)

## 評価トラック

- **実行自律性:** Level {level}相当（連続Gateの診断値。実運用Levelの確定ではない）
- **協働・拡張学習:** {collaboration}
- **因果順序:** 未評価（`Evidence → Agent update → user judgment` または `user judgment → Agent structuring` を記録する）
- **51点ゲート:** 未評価（人間との共同形成とEvidenceの校正が必要）
- **単一総合Level:** 断定しない

## 診断スコア（補助指標）

| 診断項目 | スコア | 補助表示 |
|----------|--------|----------|
"""
    for axis in AXES:
        sid = axis["id"]
        score = scores.get(sid, 0)
        bar = "█" * (score // 10) + "░" * (10 - score // 10)
        report += f"| {axis['name']} | {score:>3d}/100 | {bar} |\n"

    report += "\n"
    report += format_evals_section(eval_results)

    report += "\n## 次のステップ\n\n"
    report += "1. Evidence Gate（Functional / Failure-Recovery / Operational）の不足を確認する\n"
    report += "2. 協働・拡張学習の因果順序と人間校正を記録する\n"
    report += "3. 51点ゲートは外部成果を含めて別途評価する\n"

    if output_path:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w") as f:
            f.write(report)
        print(f"\nレポート保存: {output_path}")

    return report


def quick_mode(run_evals: bool = True):
    """クイックモード：全診断項目50、協働段階は未観測"""
    scores = {a["id"]: 50 for a in AXES}
    level = determine_execution_level(scores)
    eval_results = run_skill_evals() if run_evals else None
    print(generate_report(scores, level, eval_results=eval_results, collaboration_stage=0))
    return scores, level


def interactive_mode(run_evals: bool = True):
    """対話モード：診断項目と協働段階を質問"""
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
    
    collaboration_stage = ask_collaboration_stage()
    if collaboration_stage < 0:
        print("中断")
        return {}, 0
    level = determine_execution_level(scores)
    eval_results = run_skill_evals() if run_evals else None
    print()
    print("=" * 60)
    print(generate_report(scores, level, eval_results=eval_results, collaboration_stage=collaboration_stage))
    return scores, level


def main():
    run_evals = "--no-evals" not in sys.argv
    if "--quick" in sys.argv:
        quick_mode(run_evals=run_evals)
    elif "--help" in sys.argv or "-h" in sys.argv:
        print("Usage: python3 evaluate.py [--quick] [--no-evals]")
        print("  (no flag)    インタラクティブモード（evals 同時実行）")
        print("  --quick      クイックモード（診断項目50・協働段階未観測・evals 同時実行）")
        print("  --no-evals   スキル評価 (evals) をスキップ")
    else:
        interactive_mode(run_evals=run_evals)


if __name__ == "__main__":
    main()
