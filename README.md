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

## 構成

```
agent-level-evaluator/
├── AGENTS.md           ← エージェントが自動ロードするメインの評価手順
├── FRAMEWORK.md        ← Level 1-9 の定義と各レベルの解説
├── CHECKPOINTS.md      ← Phase 0-3 のチェックポイントテンプレート
├── scripts/
│   └── evaluate.py     ← Python3 自己評価スクリプト（標準ライブラリのみ）
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
2. **レベルアップ**: CHECKPOINTS.md の各Phaseを消化して次のレベルを目指す
3. **定期評価**: evaluate.py をcron等で定期実行し、進捗をトラッキング

## License

MIT
