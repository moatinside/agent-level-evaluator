# Agent Level Evaluator

> 「レストランの成長」をメタファーにしたAIエージェント進化レベル 1〜9 の定義と、自己評価フレームワーク。

どんなエージェントでも、このリポジトリをクローンして `AGENTS.md` を読ませるだけで、自分の現在のレベルを評価し、次のレベルに上がるためのロードマップを得られます。

## 対応エージェント

| エージェント | 自動ロードするファイル | ステータス |
|-------------|----------------------|-----------|
| Claude Code | `CLAUDE.md` | ✅ |
| Cursor | `.cursorrules` | ✅ |
| GitHub Copilot / Codex | `.github/copilot-instructions.md`, `AGENTS.md` | ✅ |
| Windsurf | `.windsurfrules` | 🔧 必要なら追加 |
| その他 | `AGENTS.md`（汎用） | ✅ |

どのエージェントでも、クローンして「自分のレベルを評価して」と指示するだけで使えます。`AGENTS.md` が評価手順の本体です。

## Quick Start

```bash
git clone https://github.com/moatinside/agent-level-evaluator.git
cd agent-level-evaluator

# エージェントに「自分のレベルを評価して」と指示する
# → AGENTS.md を自動ロードし、自己評価を開始する
```

または、カスタムインストラクションとして `AGENTS.md` の内容を直接エージェントに与えても動作します。

## レベル概要

| Level | イメージ | 能力 |
|-------|---------|------|
| **1** | 調理ロボット | 単一指示の忠実な実行 |
| **2** | 分業キッチン | 静的ワークフローの順次実行 |
| **3** | 司令塔＋検品 | 動的ルーティングと品質管理 |
| **4** | 試食会 | アンサンブル推論（複数視点の統合） |
| **5** | 自律的な店主 | 動的プランニングと自己修正 |
| **6** | 目利き | Agentic Search／Agentic RAG |
| **7** | 求道者 | 自己進化と環境改善 |
| **8** | 哲人シェフ | 社会的／倫理的な調停 |
| **9** | 未知の扉 | 知の創出／パラダイムシフト |

詳細: [FRAMEWORK.md](FRAMEWORK.md)

## 評価結果の読み方

評価は、次の3層を分けて解釈します。静的評価のPASSやスコアは、実運用Levelの直接的な証明ではありません。

- **静的構成評価**: Skill、ツール、設定、評価器の存在と構造健全性
- **振る舞い評価**: 固定シナリオで回答・仮想アクション・tool traceが契約を満たすか
- **実運用Level評価**: 継続的な実行、改善前後の効果、失敗回復、反復性の証拠

Level 7は、改善余地の自律的な発見から改善実行、効果測定、失敗回復、反復までが実運用で確認できた場合に限り候補とします。Skillやcronの存在、Phaseの完了だけではLevel 7確定とはしません。

詳細: [docs/evaluation-model.md](docs/evaluation-model.md)

## 振る舞い評価（provider / model / Agent 実装の比較）

既存の `evals/run_evals.py` は SKILL.md の**静的構造 lint**です。LLMを呼ばないため、provider/model差は測りません。

`evals/run_behavior_evals.py` は別レイヤーとして、同じシナリオ・同じ仮想ツール・同じプロンプト条件で、回答とツール選択を検証します。比較結果は「LLM単体の点数」ではなく、`Agent実装 + prompt + provider + model + decoding + tools/environment + evaluator` の実験結果として記録します。

```bash
# ハーネス自身の決定的な回帰テスト（外部LLM・ネットワーク不要）
python3 evals/run_behavior_evals.py \
  --config evals/behavior/replay-pass.yaml --repeat 3 \
  --output evaluation-reports/behavior-replay.json

# ローカルLLM（Ollama）。exampleをコピーして model 名だけ指定する
cp evals/behavior/ollama.example.yaml /tmp/ollama-eval.yaml
# /tmp/ollama-eval.yaml の REPLACE_WITH_LOCAL_MODEL をローカルの生成モデル名へ置換
python3 evals/run_behavior_evals.py --config /tmp/ollama-eval.yaml \
  --repeat 5 --output evaluation-reports/ollama-model-a.json

# 実Agent runner。stdinでscenario JSONを受け、stdoutにanswer/actions/tool_trace JSONだけを返す
python3 evals/run_behavior_evals.py \
  --config evals/behavior/command.example.yaml \
  --output evaluation-reports/agent-baseline.json
```

- シナリオ: `evals/behavior/scenarios.yaml`
- 設計と比較時の固定条件: `docs/behavior-evals-design.md`
- `structured` なOllama評価は、**実ツールを実行せず**選択だけを採点する。
- 実際のAgentのツール実行まで測る比較は `command` adapter を使い、`tool_trace` を返すrunnerを接続する。
- APIキー・トークンを設定ファイルや評価artifactに保存しない。

## 構成

```
agent-level-evaluator/
├── AGENTS.md           ← エージェントが自動ロードするメインの評価手順
├── FRAMEWORK.md        ← Level 1-9 の定義と各レベルの解説
├── CHECKPOINTS.md      ← Phase 0-3 のチェックポイントテンプレート
├── docs/
│   ├── autonomous-progression-protocol.md ← 評価から実行へ遷移する必須プロトコル
│   ├── level-evidence-gate-design.md ← Level 1〜9の証明・昇格設計
│   └── decision-log.md ← 設計判断とPhase 2.3評価の記録
├── contracts/
│   └── level-contracts.yaml ← Level契約とGateの機械可読定義
├── schemas/
│   └── evidence-record.schema.json ← 証拠レコードSchema
├── tests/
│   ├── test_stage1_contracts.py ← Stage 1回帰テスト
│   └── fixtures/ ← 正常／異常証拠fixture
├── execution-plans/     ← 実行可能なチェックポイント計画
├── execution-evidence/  ← 実行成果物・テスト・ログ
├── scripts/
│   ├── evaluate.py     ← Python3 自己評価スクリプト（標準ライブラリのみ）
│   └── progression_gate.py ← 未完了項目・実行証拠の停滞ゲート
│   ├── progression_runner.py ← チェックポイント実行オーケストレータ
│   └── validate_stage1.py ← Level契約・証拠Schemaの決定的検証
│   ├── response_validation.py ← Level 5 buffered Validator
│   ├── validated_agent_runner.py ← 外部送信しないValidator runner
│   ├── validated_command_runner.py ← 生成Agent／修正Agent接続runner
│   ├── collect_operational_evidence.py ← metadata-first運用証拠Collector
│   ├── run_shadow_batch.py ← 複数ケースのshadow実行・集計
│   ├── reclassify_phase23.py ← Phase 2.3履歴の再分類
│   └── promotion_gate.py ← 証拠ゲートによる昇格ブロック
│   └── run_phase_2_1.py ← 2.1進化的コード探索Executor
│   └── run_phase_2_2.py / run_phase_2_3.py ← 2.2/2.3 Executor
├── evals/              ← スキル単位の品質保証（Schmid: Don't Ship Skills Without Evals）
│   ├── README.md       ← テスト定義の書き方・使い方
│   ├── run_evals.py    ← 評価ハーネス（YAMLテスト読込・regex判定・アブレーション）
│   └── tests/          ← <skill>.yaml 形式のテスト定義（例: gbrain.yaml, self-validate.yaml）
└── README.md
```

## 評価スクリプト

```bash
python3 scripts/evaluate.py             # インタラクティブ評価（evals 同時実行）
python3 scripts/evaluate.py --quick     # クイック（全軸50と仮定・evals 同時実行）
python3 scripts/evaluate.py --no-evals  # スキル評価をスキップ
```

各レベル（3〜7）を6軸でスコアリングし、どの能力が不足しているかを可視化します。
**自己申告と同時に `evals/run_evals.py` が自動実行され、客観指標（スキル単位の
機械検証結果）がレポートに埋め込まれます** — 主観申告を客観数値で裏付ける構成です。

## スキル評価 (Skill Evals)

レベル評価（エージェント全体）に加えて、`evals/` で**スキル単位の品質保証**を行います。
スキルを追加・変更したら eval を実行し、改善を確認できない限りマージしない運用です。

```bash
python3 evals/run_evals.py            # 全スキルの構造健全性チェック
python3 evals/run_evals.py --ablate   # アブレーション（スキル有無で結果比較）
```

## 使い方

1. **自己評価**: エージェントに「このリポジトリで自分のレベルを評価して」と指示
2. **次の実行対象を特定**: `python3 scripts/progression_gate.py`
3. **検証工程を進める**: `python3 scripts/progression_runner.py --checkpoint auto` で、実行器が登録された最初の未完了項目を起動する
4. **定期評価**: evaluate.py をcron等で定期実行し、進捗をトラッキング

評価結果を報告するだけでは、レベルアップとはみなしません。実行可能な成果物、合格テスト、実行ログが揃って初めてチェックポイントを完了扱いにします。
詳細な状態遷移と承認境界は [autonomous-progression-protocol.md](docs/autonomous-progression-protocol.md) を参照してください。

Phase 2.3は日次実行で継続実行の状態を蓄積します。実時間7日・新規結果3件以上はPhaseの完了条件であり、Level 7の確定や次Levelへの移行条件とは別です。

## License

MIT
