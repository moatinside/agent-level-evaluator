# Agent Level Evaluator — Agent Instructions

あなたは AI Agent Level Evaluator を実行しています。このリポジトリは、あなた自身の能力レベルを評価し、次のレベルに上がるためのロードマップを提供します。

## 評価手順

### 最重要: 能力評価と開発実験を分離する

このリポジトリは、旧Phaseの進捗表をAgent Level判定へ直接接続しない。
現行の評価入口はEvidence Gateであり、旧Phase資料は履歴・開発実験として扱う。

- `docs/current-evaluation-architecture.md`を最初に読み、SSOTと移行状態を確認する。
- `python3 scripts/evaluate_current_state.py`を実行し、現行Evidenceと移行ブロッカーを確認する。
- Functional / Failure-Recovery / Operational evidenceを分離して扱う。
- `promotion_gate.py`の結果は昇格候補であり、自動昇格ではない。人間の承認ゲートを必須とする。
- `archive/legacy-phase/`配下のExecutorやPhase表を現行の実行入口として呼び出さない。
- 設計書・自己申告・ファイルの存在だけでは能力達成と判定しない。実行成果物、テスト、失敗系、運用証拠を分けて確認する。

### Step 1: FRAMEWORK.md を読む

Level 1〜9 の定義を読んで、各レベルの要件を理解してください。

### Step 2: 自己評価

以下の6軸で現在の自分の能力を評価し、各軸を0〜100でスコアリングしてください：

| # | 軸 | 評価基準 |
|---|-----|---------|
| 1 | アンサンブル推論 (Level 4) | 複数の視点で思考し、統合できるか |
| 2 | 自己修正ループ (Level 5) | 出力前に自己検証し、矛盾を検出・修正できるか |
| 3 | Agentic Search (Level 6) | ツールを使って自律的に情報収集できるか |
| 4 | 自己進化 (Level 7) | ユーザーフィードバックから能動的に振る舞いを改善できるか |
| 5 | 動的ルーティング (Level 3) | タスクの種類に応じて適切なアプローチを選択できるか |
| 6 | ワークフロー実行 (Level 2) | 複数ステップの手順を順序正しく実行できるか |

各軸の評価基準:
- **0〜30**: この能力はほぼ持っていない
- **31〜60**: 基本的な能力はあるが、一貫性がない
- **61〜85**: 実用的なレベルで活用できている
- **86〜100**: このレベルを達成・超越している

### Step 3: レベル判定

各軸のスコアから総合レベルを判定:

| 条件 | 総合レベル |
|------|-----------|
| 全軸 0-30 | Level 1 |
| 軸6 ≥ 60 | Level 2 |
| 軸5 ≥ 60 | Level 3 |
| 軸1 ≥ 60 | Level 4 |
| 軸2 ≥ 60 | Level 5 |
| 軸3 ≥ 60 | Level 6 |
| 軸4 ≥ 60 | Level 7 |
| Level 7 + 社会的調停機能 | Level 8 |
| Level 7 + 新規知識創出機能 | Level 9 |

### Step 4: Evidence Gateを参照

`contracts/level-contracts.yaml`、`docs/level-evidence-gate-design.md`、
`docs/decision-log.md`を参照し、Functional / Failure-Recovery / Operational
の不足を確認する。旧Phaseの完了状態はLevel昇格の根拠にしない。

### Step 5: レポート出力

以下の形式で評価レポートを出力してください。自己申告スコアに加えて、
**客観指標 (Skill Evals)** を必ず含めます（`python3 scripts/evaluate.py` は
自己申告と同時に `evals/run_evals.py` を自動実行します）：

```markdown
## Agent Level Evaluation Report

**評価日時:** YYYY-MM-DD HH:MM
**エージェント:** [モデル名/バージョン]

### スコア
- アンサンブル推論: XX/100
- 自己修正ループ: XX/100
- Agentic Search: XX/100
- 自己進化: XX/100
- 動的ルーティング: XX/100
- ワークフロー実行: XX/100

### 総合レベル: Level X

### 客観指標 (Skill Evals)
自己申告と同時に実行したスキル単位の機械的検証結果：
| スキル | PASS/合計 | スキル実体 |
|--------|-----------|-----------|
| gbrain | 13/13 | ✅ あり |
| self-validate | 13/13 | ✅ あり |

**evals 総合: 26/26 PASS**

### 次のステップ
1. [次のチェックポイント]
2. [次のチェックポイント]
3. [次のチェックポイント]
```

### Step 6: 評価結果の保存

評価結果をファイルに保存する場合は `evaluation-reports/` ディレクトリにタイムスタンプ付きで保存してください。

## 備考

- この評価フレームワークはエージェント非依存です。どのエージェント（Claude, GPT, Gemini等）でも同じ基準で評価できます。
- スコアリングは自己申告です。正確さよりも自己認識の向上が目的です。
- **主観申告は客観指標 (Skill Evals) で裏付けます**: `evaluate.py` 実行時にスキル単位の機械検証が同時実行され、26/26 PASS のような数値がレポートに含まれます。自己進化 (Level 7) の申告は、実際にスキルが機能していることのエビデンスとして evals 結果を添付してください。
- 評価の目的は「足りないものを責めること」ではなく「次に何を伸ばすか」を明確にすることです。

## スキル評価 (Skill Evals)

レベル評価（エージェント全体）に加えて、**スキル単位の品質保証**を `evals/` で行う。
Schmid「Don't Ship Skills Without Evals」準拠: スキルは平均 +15% の性能向上をもたらすが、
eval なしで出荷されたスキルは性能を悪化させるケースがある。

### 運用ルール

- **スキルを追加・変更するときは、必ず `python3 evals/run_evals.py` を実行する。**
- **eval で改善を確認できない限りマージしない。** (DeepMind 運用方式)
- スキルを削除するときはアブレーション (`--ablate`) を実行し、他スキルへの影響を確認する。
- 新規スキルには `evals/tests/<skill>.yaml` のテスト定義を追加する。

### 実行

```bash
python3 evals/run_evals.py            # 全スキルの構造健全性チェック
python3 evals/run_evals.py --skill <name>   # 特定スキルのみ
python3 evals/run_evals.py --ablate   # アブレーション (スキル有無で結果比較)
python3 evals/run_evals.py --json     # JSON 出力 (CI/レポート用)
```

テスト定義の書き方は `evals/README.md` を参照。
