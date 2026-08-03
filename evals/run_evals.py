#!/usr/bin/env python3
"""
run_evals.py — Hermes スキル評価ハーネス (最小導入)

Schmid「Don't Ship Skills Without Evals」準拠の軽量 eval ハーネス。
evals/tests/<skill>.yaml に定義されたテストを、対象スキルの SKILL.md に
対して正規表現で判定する (regex 判定 = 安価・依存ゼロ)。

使い方:
    python3 run_evals.py                     # 全スキルのテスト実行
    python3 run_evals.py --skill gbrain      # 特定スキルのみ
    python3 run_evals.py --ablate            # アブレーション (スキル無効化で結果比較)
    python3 run_evals.py --json              # JSON 出力 (CI/レポート用)

設計原則:
- テスト定義は YAML (evals/tests/<skill>.yaml)。happy path = 満たすべき要件、
  negative path = 陥ってはいけない品質問題。
- スキル変更時は eval 実行 → 改善しなければマージしない (DeepMind 運用)。
- --ablate はスキルファイルを一時リネームして happy path が落ちることを確認し、
  テストが「スキルが本当に効いているか」を検証していることを保証する。
- テストが no-op (スキル有無で結果が変わらない) なら警告する。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("PyYAML が必要です: pip install pyyaml\n")
    sys.exit(2)

HERE = Path(__file__).resolve().parent
DEFAULT_TESTS_DIR = HERE / "tests"
DEFAULT_SKILLS_DIR = Path.home() / ".hermes" / "skills"

# テスト定義のチェック種別 (将来拡張用に辞書で管理)
CHECK_TYPES = {"contains", "not_contains"}


def load_tests(tests_dir: Path, skill_filter: str | None) -> list[dict]:
    """evals/tests/*.yaml を読み込む。--skill 指定時はそのスキルのみ。"""
    tests = []
    for yaml_file in sorted(tests_dir.glob("*.yaml")):
        with open(yaml_file, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict) or "skill" not in data:
            print(f"⚠ スキップ (skill キーなし): {yaml_file.name}")
            continue
        if skill_filter and data["skill"] != skill_filter:
            continue
        data["_file"] = yaml_file.name
        tests.append(data)
    return tests


def find_skill_dir(skill_name: str, skills_dir: Path) -> Path | None:
    """~/.hermes/skills/ 直下およびカテゴリ配下からスキルディレクトリを探す。"""
    candidates = [skills_dir / skill_name]
    # カテゴリ分けされている場合 (skills/<category>/<skill>/)
    for category_dir in skills_dir.iterdir():
        if category_dir.is_dir():
            candidates.append(category_dir / skill_name)
    for c in candidates:
        if c.is_dir():
            return c
    return None


def run_single_test(test: dict, content: str) -> tuple[bool, str]:
    """1テスト実行。戻り値: (pass?, 判定根拠文字列)。"""
    check = test.get("check", "contains")
    pattern = test.get("pattern", "")
    if check not in CHECK_TYPES:
        return False, f"不明なcheck種別: {check}"
    try:
        matched = re.search(pattern, content, re.MULTILINE | re.IGNORECASE) is not None
    except re.error as e:
        return False, f"regexエラー: {e}"
    if check == "contains":
        ok = matched
        detail = "パターン一致" if ok else f"パターンなし: {pattern[:60]}"
    else:  # not_contains
        ok = not matched
        detail = "パターンなし (OK)" if ok else f"禁止パターン出現: {pattern[:60]}"
    return ok, detail


def run_eval(test_def: dict, skills_dir: Path, skill_dir: Path | None) -> dict:
    """1スキルの全テスト実行。結果 dict を返す。"""
    skill = test_def["skill"]
    target_file = test_def.get("target_file", "SKILL.md")
    result = {
        "skill": skill,
        "file": test_def.get("_file"),
        "description": test_def.get("description", ""),
        "skill_found": skill_dir is not None,
        "happy": [],
        "negative": [],
    }

    if skill_dir is None:
        # スキル未インストール → happy path は全部 FAIL (スキルがない = 機能しない)
        for t in test_def.get("happy_path", []):
            result["happy"].append({
                "id": t.get("id"), "name": t.get("name", ""),
                "pass": False, "detail": "スキル未インストール",
            })
        for t in test_def.get("negative_path", []):
            result["negative"].append({
                "id": t.get("id"), "name": t.get("name", ""),
                "pass": True, "detail": "スキル未インストール (検証対象なし)",
            })
        return result

    content_path = skill_dir / target_file
    content = ""
    if content_path.exists():
        content = content_path.read_text(encoding="utf-8", errors="replace")
    else:
        # SKILL.md がない場合は配下の md を連結して判定 (構造は YAML で担保)
        md_files = sorted(skill_dir.glob("*.md"))
        content = "\n".join(
            f.read_text(encoding="utf-8", errors="replace") for f in md_files
        )

    for t in test_def.get("happy_path", []):
        ok, detail = run_single_test(t, content)
        result["happy"].append({
            "id": t.get("id"), "name": t.get("name", ""),
            "pass": ok, "detail": detail,
        })
    for t in test_def.get("negative_path", []):
        ok, detail = run_single_test(t, content)
        result["negative"].append({
            "id": t.get("id"), "name": t.get("name", ""),
            "pass": ok, "detail": detail,
        })
    return result


def format_results(results: list[dict]) -> str:
    """人間向けテーブル出力。"""
    lines = []
    for r in results:
        status = "✅" if r["skill_found"] else "❌"
        lines.append(f"\n=== {status} {r['skill']} ({r['file']}) ===")
        if r["description"]:
            lines.append(f"    {r['description']}")
        all_tests = [
            (t, "H") for t in r["happy"]
        ] + [(t, "N") for t in r["negative"]]
        for t, kind in all_tests:
            mark = "PASS" if t["pass"] else "FAIL"
            icon = "✅" if t["pass"] else "❌"
            lines.append(f"  [{kind}] {icon} {mark}  {t['id']} {t['name']}")
            if not t["pass"]:
                lines.append(f"          ↳ {t['detail']}")
        passed = sum(1 for t, _ in all_tests if t["pass"])
        total = len(all_tests)
        lines.append(f"  スコア: {passed}/{total}")
    return "\n".join(lines)


def ablate(test_def: dict, skills_dir: Path) -> dict:
    """
    アブレーション: スキルディレクトリを一時リネームして eval を再実行する。
    スキルが「本当に効いている」なら happy path が全部 FAIL になるはず。
    no-op テスト (スキル有無で結果が変わらない) を検出する。
    """
    skill = test_def["skill"]
    skill_dir = find_skill_dir(skill, skills_dir)
    if skill_dir is None:
        return {"skill": skill, "ablation": "SKIPPED", "reason": "スキル未インストール"}
    backup = skill_dir.with_name(f".{skill}.ablate-backup")
    try:
        shutil.move(str(skill_dir), str(backup))
        no_skill_result = run_eval(test_def, skills_dir, None)
    finally:
        shutil.move(str(backup), str(skill_dir))

    # スキルあり eval と比較
    with_skill = run_eval(test_def, skills_dir, skill_dir)
    no_skill_happy = [t for t in no_skill_result["happy"] if t["pass"]]
    happy_ids_with = {t["id"] for t in with_skill["happy"] if t["pass"]}
    happy_ids_without = {t["id"] for t in no_skill_result["happy"] if t["pass"]}
    noop_ids = happy_ids_with & happy_ids_without
    effective = len(happy_ids_with - happy_ids_without)
    return {
        "skill": skill,
        "ablation": "OK",
        "effective_happy": effective,
        "noop_ids": sorted(noop_ids),
        "with_skill": f"{len(happy_ids_with)}/{len(with_skill['happy'])}",
        "without_skill": f"{len(happy_ids_without)}/{len(no_skill_result['happy'])}",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Hermes スキル評価ハーネス")
    parser.add_argument("--skill", help="特定スキルのみ実行")
    parser.add_argument("--tests-dir", default=str(DEFAULT_TESTS_DIR), help="テスト定義ディレクトリ")
    parser.add_argument("--skills-dir", default=str(DEFAULT_SKILLS_DIR), help="スキルディレクトリ")
    parser.add_argument("--ablate", action="store_true", help="アブレーション実行")
    parser.add_argument("--json", action="store_true", help="JSON 出力")
    args = parser.parse_args()

    tests_dir = Path(args.tests_dir)
    skills_dir = Path(args.skills_dir)

    if not tests_dir.exists():
        print(f"❌ テスト定義ディレクトリなし: {tests_dir}")
        return 2

    test_defs = load_tests(tests_dir, args.skill)
    if not test_defs:
        print(f"テスト定義が見つかりません: {tests_dir} (skill={args.skill})")
        return 2

    if args.ablate:
        ablation_results = []
        for td in test_defs:
            ablation_results.append(ablate(td, skills_dir))
        if args.json:
            print(json.dumps(ablation_results, ensure_ascii=False, indent=2))
        else:
            for a in ablation_results:
                if a["ablation"] == "OK":
                    print(
                        f"🔬 {a['skill']}: 有効テスト {a['effective_happy']} 件 "
                        f"(あり {a['with_skill']} / なし {a['without_skill']})"
                    )
                    if a["noop_ids"]:
                        print(f"   ⚠ no-op テスト (有無で結果不変): {', '.join(a['noop_ids'])}")
                else:
                    print(f"🔬 {a['skill']}: SKIPPED ({a['reason']})")
        return 0

    results = []
    for td in test_defs:
        skill_dir = find_skill_dir(td["skill"], skills_dir)
        results.append(run_eval(td, skills_dir, skill_dir))

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(format_results(results))

    # 全体サマリ + exit code
    all_tests = [
        (t, r["skill"]) for r in results for t in r["happy"] + r["negative"]
    ]
    total = len(all_tests)
    passed = sum(1 for t, _ in all_tests if t["pass"])
    failed = total - passed
    if args.json:
        # JSON の時は stdout が汚れないよう stderr にサマリ
        print(f"\nSUMMARY: {passed}/{total} passed ({failed} failed)", file=sys.stderr)
    else:
        print(f"\n📊 総合: {passed}/{total} PASS ({failed} FAIL)")
        if failed:
            print("→ eval 不合格。スキルを改善してから再実行してください (改善しなければマージしない)。")
        else:
            print("→ 全テスト合格。スキルは出荷可能な品質です。")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
