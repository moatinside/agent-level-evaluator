# Evidence Runtime Contract

更新日: 2026-09-09
状態: 契約確定・Shadow実装前

## Purpose

この文書は、通常Agent実行をEvidence Pipelineへ接続する前に、Evidenceの意味と失敗時の扱いを固定するための設計書です。

この文書だけでは、通常Agent接続、Strict enforcement、Production配信、cron変更、自動昇格を有効にしません。

## Scope boundary

```text
通常Agent
  -> 判定結果
  -> Evidence生成
  -> JSONL保存
  -> Schema / integrity / environment / duplicate検証
  -> Promotion Gate
  -> 人間監査

今回の対象外:
  -> 外部送信
  -> Production Evidenceへの昇格
  -> 自動Promotion
  -> cron追加・変更
```

## Current invariants

次の事項は現行実装の前提として維持します。

- Evidenceの正規保存形式はJSONL
- 同一`assessment_id`かつ同一hashはidempotent
- 同一`assessment_id`かつ異なるhashはconflictとしてfail-closed
- `fixture`、`sandbox`、`shadow`はPromotion Gateの既定対象外
- Agentの判定結果とEvidence保存結果は別フィールドで返す
- Evidence保存失敗で、成功したAgent判定を`inconclusive`へ上書きしない
- 自動昇格は無効で、人間の承認を必要とする
- Evidenceに秘密情報や回答本文を不要に保存しない

## Accepted runtime contract

### C1. `trigger_origin` and `execution_mode`

**目的:** Evidenceを生成した実行経路を識別する。

契約値:

- `harness`: 決定的なテスト・ハーネス実行
- `hermes`: Hermesの通常実行経路

実行モードは別フィールド`execution_mode`で表現します。

- `shadow`: 観測のみ。外部送信を行わない
- `strict`: 証跡と判定が成立しない場合、外部送信を停止
- `production`: 承認済みの運用経路。別途有効化が必要

受入条件:

- 許可値以外を保存前に拒否する
- `trigger_origin`と`execution_mode`を混同しない
- Reportで実行元・実行モードを別々に絞り込める

### C2. `configuration_id`

**目的:** Evidenceを生成した構成を再現可能に識別する。

契約値:

- `sha256:<64 lowercase hex>`だけを`configuration_id`として許可する
- 人間向け構成名は、秘密情報を含まない別metadataとして任意に保持する

実装時の前提:

- 構成内容のcanonical serialization
- hash計算対象に秘密情報が含まれないことの保証方法

受入条件:

- 同一構成が実行ごとに異なるIDにならない
- 秘密情報をhash入力・ログ・Evidenceに含めない
- IDから実行条件を監査できる

### C3. Shadowの`blocked`

**目的:** Shadow実行での送信抑止結果を、Productionの配信拒否と混同しない。

契約値:

- `decision: blocked`: Productionなら止めるべきだったというポリシー判定
- Shadowでは外部送信を行わず、`side_effect_status: not_attempted`を記録する
- 実際のStrict/Production抑止は、`side_effect_status: suppressed`で表す
- 判定不能は`decision: inconclusive`で表す

境界:

- `blocked`は実際の外部送信抑止を意味しない
- `decision`と`side_effect_status`を別々に監査する
- Shadow EvidenceだけでProduction配信を証明しない

受入条件:

- Shadow recordだけでProduction配信を証明しない
- `decision`と`side_effect_status`をReportで表示する
- Shadowの外部送信未実施を独立metadataとして監査できる

### C4. Evidence保存失敗

**目的:** 保存障害がAgent判定やユーザー応答へ与える影響を明示する。

契約値:

- Shadowでは判定と保存結果を分離する
- StrictではEvidence保存を含む検証が成立しなければ外部送信を停止する
- Productionは別途運用承認されるまで未接続とする
- 絶対パス・秘密情報をエラー出力へ含めない

受入条件:

- 成功判定が保存失敗だけで別の判定へ変化しない
- 保存失敗は終了コードと機械可読エラーコードで識別できる
- 再試行時に重複・conflictを安全に処理できる

## Shadow acceptance matrix

通常Agent接続を検討する前に、fake adapterまたは外部副作用のないisolated adapterで以下を確認する。

1. 正常判定: 判定結果、Evidence、JSONL、Reportが一致する
2. Schema違反: 保存前またはGate入口で拒否される
3. 保存失敗: 判定結果と保存結果が分離される
4. 同一Evidence再実行: 重複として安全に扱われる
5. 同一ID・異なるhash: conflictとしてfail-closedになる
6. Shadow blocked: `decision=blocked`かつ`side_effect_status=not_attempted`として記録され、Production配信実績として集計されない
7. 不正な`trigger_origin`: 保存・集計対象から拒否される
8. 不正な`configuration_id`: 保存・集計対象から拒否される
9. 秘密情報の混入: Evidence、ログ、Reportに保存されない

## Decision authority

- 契約値の採用: 人間の明示判断
- EvidenceのSchema検証: Validator / Promotion Gate
- Evidenceの採用可否: Gateの決定的判定
- Level昇格: 人間の承認
- Strict / Production / cron切替: 別途運用承認

Evidenceの生成結果だけで契約を自動変更しません。

## Exit criteria for the next phase

次の「通常AgentのShadow接続」へ進める条件は以下です。

- C1〜C4の採用値がdecision logへ記録されている
- 上記Shadow acceptance matrixの全ケースにfixtureがある
- Producer→Collector→JSONL→Gate→Reportの一連の経路を実行できる
- 成功・異常・重複・保存失敗の終了コードと成果物を読み戻せる
- Production送信が発生しないことを確認できる
- 未確定の項目が残る場合、Shadow接続の対象外として明記されている
