# Agent Level Evaluator

> 「レストランの成長」をメタファーにしたAIエージェント進化レベル 1〜9 の定義と、Evidence Gate・協働学習評価フレームワーク。

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

## Current Status

- 現行の評価経路: Evidence Gate
- 旧PhaseのExecutor: `archive/legacy-phase/` にアーカイブ済み
- Phase 2.3: 開発実験の履歴として保持し、Level昇格には使用しない
- 自動昇格: 無効（人間の承認が必要）
- Production接続・cron切替: 未実施（別途承認が必要）
- 通常Agent接続前の契約整理: [docs/evidence-runtime-contract.md](docs/evidence-runtime-contract.md)
- Capability追加前の測定可能性設計: [docs/measurement-first-capability-design.md](docs/measurement-first-capability-design.md)
- 事業開発会話の協働・拡張学習評価: [docs/business-development-trajectory-reconstruction.md](docs/business-development-trajectory-reconstruction.md)
- 現行状態の確認: `python3 scripts/evaluate_current_state.py`

## Start Here

1. `AGENTS.md` を読む
2. `python3 scripts/evaluate_current_state.py` で現行Evidence状態を確認
3. `python3 scripts/audit_legacy_pipeline.py --root .` で旧経路の混入がないことを確認
4. `python3 scripts/evidence_report.py --summary` でEvidenceを監査
5. Skill単位の品質確認には `python3 evals/run_evals.py` を使う

## Quick Start

```bash
git clone https://github.com/moatinside/agent-level-evaluator.git
cd agent-level-evaluator

# エージェントに「自分のレベルを評価して」と指示する
# → AGENTS.md を自動ロードし、自己評価を開始する
```

または、カスタムインストラクションとして `AGENTS.md` の内容を直接エージェントに与えても動作します。

## レベル評価の2軸

Level 1〜3の実行自律性と、Level 4以降で重要になる人間との協働・拡張学習を、同じ一つのスコアへ混ぜずに評価します。

- **実行自律性**: 単発実行 → 固定ワークフロー → 条件分岐・検証 → アンサンブル → 自己修正 → 自律探索 → プロセス改善
- **協働・拡張学習**: 動機付け → 方向付け → 内化 → 外化 → 批評 → 統制

後者は、人間の暗黙の判断基準をAgentが外化し、Evidence・反証・次の検証へ接続できるかを扱います。51点の事業判断基準はLevelそのものではなく、協働・拡張学習の結果として最低限の判断可能性に到達したかを見るゲートです。詳細な実会話の校正は [docs/business-development-trajectory-reconstruction.md](docs/business-development-trajectory-reconstruction.md) にあります。

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
- APIキー・トークンを設定ファイルへ直接記載しない。評価artifactはメタデータ限定で、回答本文・ツールtrace/引数・Provider設定・scenario入力・ローカルパスを保存しない。

## 本番環境デプロイ（Blue-Green Strategy）

**macOS と Windows の両プラットフォームで Blue-Green デプロイをサポートしています。**

### macOS (launchd)

```bash
# セットアップ
bash scripts/setup_blue_green.sh

# 監視
python3 scripts/blue_green_monitor.py

# 詳細ガイド
cat docs/BLUE_GREEN_DEPLOYMENT_GUIDE.md
```

詳細: [Blue-Green Deployment Guide](docs/BLUE_GREEN_DEPLOYMENT_GUIDE.md)

### Windows (Task Scheduler)

1. **Release ページから executable をダウンロード**
   ```
   https://github.com/moatinside/agent-level-evaluator/releases
   → agent-level-evaluator.exe
   ```

2. **PowerShell で自動セットアップ**
   ```powershell
   # 管理者として実行
   .\setup_windows_service.ps1 -ExePath ".\agent-level-evaluator.exe"
   ```

3. **自動実行開始**
   - Blue service: 毎時間実行
   - Green service: 待機（24h後に昇格可能）

詳細: [Windows Setup Guide](docs/README_WINDOWS.md)

---

## リポジトリ構成

```text
agent-level-evaluator/
├── .cursorrules              # Cursor向け指示
├── .github/                  # Copilot指示とGitHub Actions
├── .gitignore
├── archive/legacy-phase/     # 旧Phaseの計画・実行スクリプト・チェックポイント
├── contracts/                # Level契約の機械可読定義
├── docs/                     # 評価方式、Evidence Gate、本番デプロイガイド
│   ├── BLUE_GREEN_DEPLOYMENT_GUIDE.md  # 共通 Blue-Green ガイド
│   ├── README_WINDOWS.md                # Windows セットアップ
│   └── ...                              # その他ドキュメント
├── evals/                    # スキル評価と振る舞い評価
│   ├── behavior/             # シナリオ、設定例、固定fixture
│   └── tests/                # スキル評価定義と振る舞い評価の回帰テスト
├── evaluation-reports/       # 評価レポート・履歴スナップショット
├── execution-evidence/       # 過去の実行証拠
├── migration/                # 移行検証の承認記録
├── schemas/                  # Evidence等のJSON Schema
├── scripts/                  # 評価・検証CLI + 本番デプロイスクリプト
│   ├── setup_blue_green.sh           # macOS Blue-Green セットアップ
│   ├── blue_green_monitor.py         # 監視ダッシュボード
│   └── ...                           # その他CLI
├── tests/                    # 現行コードのユニットテストとfixture
├── build_windows_exe.py      # Windows exe ビルドスクリプト（PyInstaller）
├── setup_windows_service.ps1 # Windows Task Scheduler 自動セットアップ
├── AGENTS.md                 # エージェント共通の評価手順
├── CLAUDE.md                 # Claude Code向け入口
├── FRAMEWORK.md              # Level 1〜9の定義
└── README.md                 # 利用者向け案内
```

旧Phaseの実行計画とスクリプトは`archive/legacy-phase/`内に置いています。現行CLIは`scripts/`、テストは`tests/`、Skill・Agentの評価定義とハーネスは`evals/`に分けています。

`operational-evidence/`と`evidence-quarantine/`は設計上の運用保存先です。現在のリポジトリにはディレクトリや記録ファイルは含まれていません。

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
2. **現行状態を確認**: `python3 scripts/evaluate_current_state.py`
3. **移行状態を監査**: `python3 scripts/audit_legacy_pipeline.py --root .`
4. **Evidenceを監査**: `python3 scripts/evidence_report.py --summary`（既定では `production-like` / `production` のみ。Shadowは `--environment-class shadow` で明示）

Outbox/ledgerのtransport状況も同じレポートに添付する場合は、`--runtime-outbox-db`、`--runtime-ledger-db`、`--runtime-sink-id`、`--runtime-max-records`をすべて明示してください。出力の`runtime_transport`はEvidence記録・Promotion統計と分離されます。`outcome_counts`はaccepted・reason別rejected・境界別conflictを件数のみで表示し、durableな観測値がないduplicateは`null`です。`emitted`、`measurement_complete`、`evaluation_eligible`も未実装の間`null`です。既定のDB pathやruntime rootの自動読取りはありません。

5. **定期評価**: Evidence Gateの結果だけをcron等で観測し、Levelを自動昇格しない

評価結果を報告するだけでは、レベルアップとはみなしません。実行可能な成果物、合格テスト、実行ログが揃って初めてチェックポイントを完了扱いにします。
詳細な状態遷移と承認境界は [autonomous-progression-protocol.md](docs/autonomous-progression-protocol.md) を参照してください。

旧Phase 2.3は開発実験の履歴として保持します。実時間7日・新規結果数は、Agent Levelの昇格条件ではありません。現行の能力判定はEvidence GateのFunctional / Failure-Recovery / Operational evidenceで行います。

## License

MIT
