#!/usr/bin/env python3
"""
Agent Level Self-Evaluation Script

依存ゼロ（Python標準ライブラリのみ）。
6軸のアンケートに答えると、現在のエージェントレベルを推定する。

Usage:
    python3 evaluate.py           # インタラクティブモード
    python3 evaluate.py --quick   # クイックモード（すべて3と仮定）
"""

import json
import os
import sys
from datetime import datetime

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


def generate_report(scores: dict, level: int, output_path: str = ""):
    """評価レポートを生成"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    report = f"""# Agent Level Evaluation Report

**評価日時:** {now}
**方法:** 6軸セルフアセスメント

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


def quick_mode():
    """クイックモード：全軸3と仮定"""
    scores = {a["id"]: 50 for a in AXES}
    level = determine_level(scores)
    print(generate_report(scores, level))
    return scores, level


def interactive_mode():
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
    print()
    print("=" * 60)
    print(generate_report(scores, level))
    return scores, level


def main():
    if "--quick" in sys.argv:
        quick_mode()
    elif "--help" in sys.argv or "-h" in sys.argv:
        print("Usage: python3 evaluate.py [--quick]")
        print("  (no flag)  インタラクティブモード")
        print("  --quick    クイックモード（全軸50で仮評価）")
    else:
        interactive_mode()


if __name__ == "__main__":
    main()
