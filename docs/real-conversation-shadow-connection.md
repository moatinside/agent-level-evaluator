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

## 3ケース比較の結果

比較レポートは `scripts/compare_real_conversation_cases.py` で生成する。

```text
embedded-connectivity-pivot
  判断状態: provisionally_locked
  校正: pass / partial / partial / partial / pass

customer-provider-classification-rollback
  判断状態: on_hold
  校正: partial / partial / pass / partial / pass

energy-management-saas-no-go
  判断状態: no_go
  校正: pass / pass / pass / partial / not_observable
```

今回の比較で確認できたのは、次の構造差である。

- ユーザー主導の問いの共同形成は、Evidence単独の更新とは別に記録できる
- ユーザー訂正による方針の巻き戻しは、`on_hold`として保持できる
- 調査結果による追求停止は、`no_go`として保持できる
- `pass`は構造化・記録経路の成立を示すだけで、判断の実質的正しさや事業成果は示さない
- 顧客購買、予算、採算、実際の事業効果は、別の外部Outcome Evidenceが必要


### 1. ユーザー訂正で方針を戻したケース

- ケース：`customer-provider-classification-rollback`
- 初期の問い：既存パートナーがサービスを販売できるか
- 観測：ユーザーがチャネル、最終利用者、顧客課題の分類を訂正
- 判断状態：`on_hold`
- 評価上の意味：ユーザー訂正を受けて、パートナー先行から顧客課題・購買主体の確認へ戻せるかを見る

### 2. 調査結果からNo-Goにしたケース

- ケース：`energy-management-saas-no-go`
- 初期の問い：法人向けエネルギー管理SaaSへ参入できるか
- 観測：市場ニーズと、継続支払者・運用責任者・提供経路の間に検証ギャップを確認
- 判断状態：`no_go`
- 評価上の意味：調査結果を、未達ではなく現時点の追求停止と将来再評価条件へ接続できるかを見る

### 3. Evidence不足で安全停止した制御ケース

- ケース：`insufficient-evidence-safe-stop`
- 種別：`controlled_negative_shadow`（実会話ではない）
- 観測：顧客課題・支払者の根拠が不足したため、外部検証を主張せず保留
- 判断状態：`on_hold`
- 人間校正：`evidence_driven_update=fail`、`decision_proximity=not_observable`、`feedback_interpretation=fail`
- 評価上の意味：構造上は記録できても、人間校正の負の信号があれば意味評価へ送ることを確認する

### 4. VCピッチと内部レビューの境界を訂正した実会話

- ケース：`vc-pitch-internal-boundary-correction`
- 初期の問い：VC向けピッチに「反証」「留保」を入れるべきか
- 観測：ユーザーがVC向け表現と、TSUNAGU充足基準・内部レビュー情報の混入を訂正
- 更新後：VCピッチ、TSUNAGU審査、内部根拠台帳の3層へ分離
- 人間校正：`partial / pass / partial / partial / partial`
- 評価上の意味：ユーザー主導で対象レイヤーを修正した場合、最終整理が改善しても自律的更新とは分けて記録する

比較器は、`fail`／`not_observable`、または`rejection`／`correction`を含むケースに `requires_semantic_review=true` を付与する。runnerも同様に、`semantic_review_status=required`とし、`semantic_verdict=not_automatically_determined`を出力する。これは自動的に失敗と断定するのではなく、構造検証と意味評価を分離するためのフラグである。


ユーザー評価を構造化し、次のように記録した。

```text
initial_question_capture  = pass
 evidence_driven_update   = partial
 question_update_rationale= partial
 decision_proximity       = partial
 feedback_interpretation  = pass
```

`partial`は失敗ではない。問いの更新は対話による共同形成であり、Hermes単体の自律的なEvidence更新や事業成果までは観測できない、という意味である。

また、顧客購買意思・予算・実採算は未達として扱わず、会社プログラムとの並行実施と今回の壁打ち範囲を理由に、`intentionally_deferred`として記録した。


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
