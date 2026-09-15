# Real Conversation Shadow Connection

更新日: 2026-09-16
状態: 1会話のTrace接続を実装・検証済み（Shadowのみ）

## 対象

実際の新規事業壁打ちから、次の構造を持つ1ケースを選んだ。

- 当初の問い：モバイルFCへの参入
- 観測された更新：既存モバイル事業との境界・社内摩擦を踏まえた再定義
- 現在の問い：端末ライフサイクルの顧客入口、単店採算、専門バックエンド、複数拠点再現性
- 判定状態：`provisionally_locked`

元会話の本文、セッション識別子、個人情報、認証情報はEvidenceへ保存しない。ケースファイルには、問い・変化理由・Evidence参照・ユーザー評価の種類だけを置く。

## 観測する契約

```text
initial question
  → evidence reference
  → updated question
  → reason for change
  → decision impact
  → next validation
  → user feedback
```

ユーザー評価は、本文の印象点ではなく、会話上の観測可能なシグナルに分類する。

- `correction`：事業境界・顧客分類などの訂正
- `positive_signal`：ピボット・センターピンへの肯定反応
- `acceptance`：提案を次の作業へ進める反応
- `rejection`：提案の不採用・差し戻し

## 実行

```bash
AGENT_ID=$(printf '%s' 'agent-level-shadow' | shasum -a 256 | cut -d' ' -f1)
EVAL_ID=$(printf '%s' 'real-conversation-shadow-evaluator' | shasum -a 256 | cut -d' ' -f1)
uv run --with pytest --with pyyaml python scripts/run_real_conversation_shadow.py \
  --case tests/fixtures/real-conversation-embedded-connectivity.json \
  --output /tmp/agent-level-real-conversation/operational-evidence/embedded-connectivity.jsonl \
  --agent-configuration-id sha256:$AGENT_ID \
  --evaluator-configuration-id sha256:$EVAL_ID

PYTHONPATH=. uv run --with pytest --with pyyaml python scripts/evidence_report.py \
  --root /tmp/agent-level-real-conversation \
  --environment-class shadow \
  --summary
```

## 今回確認できたこと

- Trace構造が存在する
- 問いが2回更新されている
- 各更新にEvidence参照と変更理由がある
- 判断への影響と次の検証が接続されている
- ユーザー訂正と肯定シグナルを分離して記録できる
- 生テキストを保存しない
- 外部送信・自動Promotionを行わない
- 既存Evidence Reportへ投入できる

## まだ確認できないこと

この1件だけでは、以下は証明しない。

- 問いの更新が事業成果につながったこと
- ユーザー評価の妥当性・再現性
- 外部顧客が仮説を支持したこと
- 実際のGo／No-Go判断が正しかったこと
- Operational Levelの昇格

Human評価は、次に人手の校正基準を定め、同じ形式の複数ケースで一致度を確認する必要がある。今回の判定は決定的な構造検証であり、実ユーザー評価そのものを自動判定したものではない。
