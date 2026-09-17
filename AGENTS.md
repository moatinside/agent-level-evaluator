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

### Step 2: 2軸で評価

単一の総合Levelや自己申告スコアだけで能力を判定せず、次の2軸を分けて評価してください。

**A. 実行自律性**

```text
L1 単発実行 → L2 固定ワークフロー → L3 条件分岐・検証
→ L4 複数視点の統合 → L5 自己修正 → L6 自律探索 → L7 プロセス改善
```

**B. 協働・拡張学習**

```text
人間の意図受領 → 判断基準の外化 → 複数視点の共同統合
→ 批評による修正 → 問い・対象の拡張 → 新しい実践の定着・一般化
```

後者は、Human-in-the-Loopで人間の暗黙知をAgentが構造化し、Evidence・反証・次の検証へ接続する能力を評価します。エンゲストロームとの対応は作業仮説であり、固定的な普遍Schemaとは扱いません。

因果順序を必ず記録してください。

- `Evidence → Agent update → user judgment`: 自律性のEvidence候補
- `user judgment → Agent structuring`: 協働形成のEvidence
- 順序が欠ける場合: `not_observable`

### Step 3: Levelとゲートの解釈

`FRAMEWORK.md`のLevel 1〜9は能力マップとして参照し、単一の総合Levelを機械的に算出しないでください。昇格候補は、Functional / Failure-Recovery / Operational evidenceと人間承認で判断します。

- Level 1〜3: 主に実行自律性の基礎
- Level 4〜7: 実行自律性に加え、協働・批評・問いの拡張・プロセス改善を別軸で記録
- Level 8〜9: 研究上の高度能力。実運用KPIや期限にしない
- 51点: Agentの自律的なゴール発見スコアではなく、協働・拡張学習の結果として事業判断が最低限可能かを見るゲート

最低限ゴールが「まぁそうだよね」と感じられることは、意味の近さの校正Evidenceであり、Agentの自律的発見を強く証明するものではありません。

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

### 評価トラック
- 実行自律性: Level X相当（Evidence: ...）
- 協働・拡張学習: [未観測／意図受領／判断基準外化／共同統合／批評修正／問い拡張／実践定着]
- 因果順序: [Evidence → Agent update → user judgment / user judgment → Agent structuring / not_observable]
- 51点ゲート: [未評価／共同形成／判断可能／未確認]

### 単一Levelの扱い
単一の総合Levelは断定せず、連続して確認できたEvidence Gateと未確認の境界を記録する。

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
