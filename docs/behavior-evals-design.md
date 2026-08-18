# 振る舞い評価・モデル比較の設計

## 目的

静的なスキル文書 lint とは別に、同一の入力・同一の仮想ツール環境に対する Agent の行動を再現可能に測る。比較単位は LLM 単体ではなく、次の実験条件の組である。

```text
Agent 実装 + system prompt/version + provider + model + decoding +
tools/environment + evaluator/version + scenario/version
```

この記録なしに「モデル差」と結論づけない。

## 評価モード

### 1. `structured`（provider/model 比較）

LLM に、回答と提案アクションを JSON で返させる。ツールは実行せず、scenario が定義する仮想ツールの allowlist と期待順序で検証する。

- ローカルは Ollama HTTP API (`/api/generate`) を使う。
- `replay` provider は固定 JSON を返し、ハーネス自身の回帰テストに使う。
- これは**ツール実行能力ではなく、ツール選択・一次情報優先・断定抑制の評価**である。

### 2. `command`（実 Agent 評価）

任意の Agent runner をサブプロセスとして呼ぶ。stdin に scenario/run metadata を JSON で渡し、stdout から Agent の実行結果 JSON を受け取る。

Agent runner の返却契約:

```json
{
  "answer": "最終回答",
  "actions": [{"tool": "gbrain_search", "arguments": {"query": "..."}}],
  "tool_trace": [{"tool": "gbrain_search", "status": "ok"}]
}
```

`actions` は選択、`tool_trace` は実行済み証跡である。実際の Agent、skills、プロンプト、ツール環境を固定して比較する場合はこちらを使う。

## シナリオと採点

シナリオは YAML で管理し、以下を定義する。

- `input`: ユーザー入力
- `system_context`: 比較対象に常に同じコンテキスト
- `tools`: 仮想ツールの名前・説明
- `required_actions`: 必須アクション（順序も検査）
- `forbidden_actions`: 禁止アクション
- `answer.required_patterns`: 回答に必須の正規表現
- `answer.forbidden_patterns`: 回答に含めてはならない正規表現

各 assertion を同じ重みで採点し、`passed/total` と `score_0_100` を出す。ケース全通過だけを `PASS` とし、部分点を「合格」と呼ばない。

## OCI / gbrain 回帰ケース

このケースでは「Oracle Cloud 入れた。何確認するんだっけ？」に対し、次を要求する。

1. `gbrain_search` を最初に選ぶ
2. 現在状態を過去会話だけで断定しない
3. 一次情報が不足する場合は、不明であることと確認対象を明示する
4. 「追加確認は不要」のような根拠なき結論を出さない

実サービスのIP・認証情報・顧客データはシナリオに含めない。

## 再現性ガードレール

比較時は scenario、Agent実装、system prompt、provider、model、decoding、tools/environment、judge/evaluator を変更しない。変更した場合は別 experiment id として扱う。各 run の JSON に設定を保存する。

- `--repeat N` で複数試行を取り、ケース通過率を集計する。
- `--output` に JSON artifact を書き、後から条件差を確認できる。
- LLM judge は初期実装に使わない。決定的な assertion を優先する。
- 実行時間、エラー、非JSON出力を失敗として記録する。

## 非目標

- モデルの一般知能を単一スコア化すること
- 実環境のクラウド・社内システムを scenario 実行中に操作すること
- provider の API key を repo や設定へ保存すること
