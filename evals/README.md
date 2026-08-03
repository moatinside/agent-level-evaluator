# スキル評価ハーネス (Skill Evals)

> 動機: Schmid「Don't Ship Skills Without Evals」— Skill Bench 5万スキル中ほぼ全てに
> eval がなく、AI生成スキルは性能を悪化させるケースがある。スキル平均 +15% 性能向上を
> 評価で担保する。
>
> 運用ルール: **スキル追加/変更時は eval を実行し、改善しなければマージしない**
> (DeepMind の運用方式を採用)。eval はスキルの構造的健全性 + 品質問題の検出を担う。

## 使い方

```bash
# 全スキルのテスト実行
python3 evals/run_evals.py

# 特定スキルのみ
python3 evals/run_evals.py --skill gbrain

# アブレーション (スキル無効化で結果比較 → no-op テスト検出)
python3 evals/run_evals.py --ablate

# JSON 出力 (CI / レポート用)
python3 evals/run_evals.py --json
```

## テスト定義の書き方

`evals/tests/<skill>.yaml` にスキル単位で定義する:

```yaml
skill: <スキル名>
description: 何をするスキルか
target_file: SKILL.md
max_score: 10

happy_path:          # 満たすべき要件 (スキルが機能するために必要)
  - id: <skill>-h1
    name: 表示名
    check: contains        # SKILL.md にパターンが含まれるべき
    pattern: "^name:"
    reason: なぜ必要なのか

negative_path:       # 陥ってはいけない品質問題
  - id: <skill>-n1
    name: 表示名
    check: not_contains    # SKILL.md にパターンが含まれてはならない
    pattern: "(?i)\\bTODO\\b"
    reason: なぜ禁止なのか
```

### 種別の意味

| 種別 | 意味 | 判定 |
|------|------|------|
| `happy_path` / `contains` | スキルが正しく機能するための必須要素 | パターン一致で PASS |
| `negative_path` / `not_contains` | 品質を毀損する禁止要素 | パターン不一致で PASS |

## アブレーション (`--ablate`)

スキルディレクトリを一時的に無効化して再評価し、テストが「スキルが本当に効いているか」
を検証していることを確認する。

- **有効テスト** = スキルありで PASS / スキルなしで FAIL になるテスト
- **no-op テスト** = スキル有無で結果が変わらないテスト (警告。トークンと信頼の無駄)

スキルが未インストールの場合は SKIPPED として安全にスキップされる。

## 既存テスト

| テスト | 対象スキル | 内容 |
|--------|-----------|------|
| `gbrain.yaml` | gbrain | 知識基盤スキルの構造健全性 (frontmatter / 手順 / 検証 / 落とし穴) |
| `self-validate.yaml` | self-validate | 自己検証スキルの要件充足 (発動条件 / 完了基準 / 3層防御 / 禁止原則) |

## 評価対象スキルの場所

デフォルトで `~/.hermes/skills/<skill>/SKILL.md` を対象にする。
`--skills-dir` で差し替え可能 (リポジトリ外の Hermes 環境を評価する想定)。

## 既知の制約

- regex 判定のため意味的な正しさ (手順が実行可能か等) は検証しない。構造的健全性の
  ゲートとして位置づける。
- プラグイン配下 (`~/.hermes/plugins/`) のスキルは探索対象外 (必要なら `--skills-dir`
  を向ける)。
- アブレーションはファイルリネームで実装しており、実行中にスキルを使う処理が走ると
  競合する可能性がある (バッチ実行時は避ける)。
