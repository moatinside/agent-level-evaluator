# Agent Level Evaluator Decision Log

## 文書の役割

この文書は、Agent Level評価方式に関する採用済み設計判断のSSOTである。概念定義は`../FRAMEWORK.md`、証明・ゲート仕様は`level-evidence-gate-design.md`、実行結果は`../execution-evidence/`および`../evaluation-reports/`を参照する。

## ADR-001 — Evidence-gated Level model

- **Status**: accepted
- **Accepted at**: 2026-09-06 JST
- **Scope**: Agent Level 1〜9の判定、運用証拠、昇格、回帰
- **Decision source**: ユーザー承認（Discord message `1545986793340539061`）

### Context

現行評価器は、自己申告スコア、Skill文書の静的lint、能力開発Phaseの進捗をLevel判定へ接続できる。これらは部品や計画の存在を示すが、制御された機能証明と実運用での反復証明を保証しない。特にLevel 5では、ユーザー指摘前の自己検出を証明するpre-send経路が存在せず、静的テスト合格だけで高い能力を示せる問題が確認された。

### Decisions

#### D1. Level階層

Level 1〜7は累積Operational Levelとする。Level 8 Social ArbitrationとLevel 9 Discoveryは、Level 7達成後に個別認証する独立Advanced Capabilityとし、相互を前提条件にしない。

#### D2. 最低観測量・期間

Level別の固定件数を根拠なく設定しない。最初に2〜4週間のshadow運用を行い、対象タスク頻度、経路カバレッジ、誤検知、見逃しを測定する。その結果から最低観測量・期間を事前登録する。確定前はOperational Levelを昇格しない。

#### D3. Promotion reviewer

- Gate D/F/X：決定的Evaluator
- Gate O：独立Agentによる意味レビュー
- Gate P：人間による正式承認
- 重大失敗：自動的に`under_review`へ移行可能
- 自動昇格：v1では禁止

#### D4. Level 5 Validatorの挿入順序

最初にagent-level-evaluator内へbuffered `validated_agent_runner`を実装し、未検証出力を外部送信せず、Validator、修正、再検証を行う。機能証明後、Hermes Agent coreのfinal response確定後かつGateway／CLI配信前の共通pre-delivery policyへ接続する。Strict validation対象ターンでは未検証streamを表示しない。

Gatewayの`on_before_finalize`はstream最終化用であり、既に表示されたdeltaを回収できないため、単独ではLevel 5の送信前ゲートに使わない。

#### D5. 証拠の保存と匿名化

運用証拠はmetadata-firstとする。通常はID、hash、判定、Tool trace、assertion ID、修正カテゴリ、redacted diffを保存し、会話全文、Tool出力全文、ファイル本文を複製しない。原文が必要な場合だけローカル隔離領域へ保存し、目的、アクセス範囲、保持期限を明示する。秘密情報・個人情報を検出した場合は保存を停止する。

#### D6. モデル・構成変更時の証拠再利用

重要構成変更ごとに新しい`agent_configuration_id`を発行する。

- 再利用可能：定義、Schema、決定的Validator、静的lintなどモデル非依存証拠
- 条件付き再利用：Tool routing、Skill発動、memory、検索経路など影響分析が必要な証拠
- 自動再利用不可：自己検証、アンサンブル統合、Agentic Search、自己改善、社会的調停、新規仮説生成などモデル依存の振る舞い証拠

モデル依存証拠は、新構成の回帰テスト合格後にのみ現在構成へ関連付ける。

#### D7. Level 8の責任範囲

Level 8は、利害関係者、権利、責任、制約、選択肢、残る不一致を扱う意思決定支援品質を評価する。実際の合意、決定、継続、成果は`downstream_impact`として別記録し、Agentが制御できない結果をPromotionの必須条件にしない。

#### D8. Level 9の新規性と独立再現

Level 9は次の三段階で評価する。

1. `prior_art_closure`：対象ソース、検索語、対象期間、基準日時を事前登録し、探索範囲に限定して新規性を表現する。
2. `falsifiable_result`：baseline、比較条件、成功・失敗条件を事前登録し、否定結果も保存する。
3. `independent_reproduction`：元Agentの非公開な内部思考へアクセスしない別主体が、凍結した仕様・データ・手順から再現する。

元Agentによる同一環境の再実行は独立再現に含めない。敵対的な反証試行をPromotion条件とし、第三者による実利用はGate Sの強い証拠として扱う。

### Consequences

- 旧「Level 6相当」は履歴として残るが、新基準では再評価前の暫定記録になる。
- 新基準によるOperational Levelは、証拠移行と再評価が終わるまで`unassessed`となる。
- 自己申告スコアとStatic Skill evalだけではLevel昇格できない。
- Phase完了とLevel昇格は別々に判定される。
- モデル変更後、モデル依存のLevel証拠は自動継承されない。
- Level 5の運用証明には、Hermes側の配信経路へ接続されたpre-delivery validationが必要になる。

### Supersession rule

この決定を変更する場合、本文を上書きして履歴を消さない。新しいADRを追加し、置き換えるDecision ID、変更理由、影響する証拠、再評価条件を明記する。

## ADR-002 — Evidence runtime contract

- **Status**: accepted
- **Accepted at**: 2026-09-09 JST
- **Scope**: 通常AgentのShadow接続前におけるEvidence metadata、実行モード、保存失敗の扱い
- **Decision source**: ユーザー承認（Discord message `1547076354535718962`）

### Decisions

1. `trigger_origin`は`harness`または`hermes`とする。実行状態は別フィールド`execution_mode`で表し、許可値は`shadow`、`strict`、`production`とする。
2. `configuration_id`は`sha256:<64桁の小文字hex>`形式のみを正式値とする。人間向け構成名を保持する場合は別metadataとし、秘密情報を含めない。
3. `decision: blocked`は、Productionなら停止すべきだったというポリシー判定を表す。Shadowでは外部送信を行わず、`side_effect_status: not_attempted`を記録する。実際の抑止は`side_effect_status: suppressed`で別表現する。
4. Evidence保存失敗時は、ShadowではAgent応答を返し、`evidence_persisted: false`と機械可読エラーを報告する。Strictでは保存を含む検証が成立しない場合、外部送信を停止する。

### Consequences

- `trigger_origin`、`execution_mode`、`decision`、`side_effect_status`、`evidence_persisted`を別々に監査できる。
- Shadow EvidenceはProduction EvidenceやProduction配信実績として集計できない。
- Strict接続は、保存失敗時のfail-closed経路を実装・検証するまで有効化しない。
- 通常Agent接続、Production接続、cron変更、自動昇格はこのADRによって有効化されない。

### Required follow-up

- fake adapterで正常、Schema違反、保存失敗、重複、conflict、blocked、秘密情報混入を検証する。
- 実AgentのShadow接続前に、外部送信が発生しないことを実ランタイム境界で確認する。

## Assessment-002 — Phase 2.3 evidence classification

- **Status**: assessed
- **Assessed at**: 2026-09-06 JST
- **Scope**: Phase 2.3 open-ended loopの既存実行証拠を新Evidence Gateへ照合
- **Source**: `/Users/yokapro/Developer/agent-level-evaluator` の実行コード・`execution-evidence/2.3/`・2026-09-06日次レポート

### Observed facts

- `state.json`は`status: passed`、`elapsed_days: 7`、`novel_results: 7`を保持する。
- 日次runは8件、`novel: true`が7件、`novel: false`が1件である。
- 7件の候補はすべて、`scripts/run_phase_2_3.py`の`CANDIDATES`へ事前定義されている。
- 8件すべてに`verifiable: true`が記録されるが、これは同スクリプトが固定値として付与している。
- 新規性判定は候補文のToken集合Jaccard類似度と閾値0.5に基づく。独立した意味評価や外部情報源による新規性確認ではない。
- 2026-09-06の候補は過去候補と類似度1.0で、`novel: false`として記録されている。この重複記録は、差分を隠さない処理の証拠になる。

### New-gate classification

- **Gate D**：部分的に確認。Phase定義、計画、完了条件は存在するが、Level 5〜7の能力契約ではない。
- **Gate F**：Phase Executorの決定的な正常実行は確認。ただし、Agentが未知課題を発見した機能証明ではない。
- **Gate X**：重複スキップと`novel: false`の記録は確認。依存失敗、壊れたstate、書き込み失敗、回復・ロールバックの証拠は未確認。
- **Gate O**：日次Executorの反復稼働という運用証拠は確認。主にLevel 2の定期ワークフロー実行の証拠であり、Level 5・6・7の運用証明ではない。
- **Gate P**：未通過。独立Reviewerによる判定と人間によるPromotion承認がない。
- **Gate S**：未通過。構成ID、変更影響、回帰判定、実運用上の効果測定がない。

### Decision

Phase 2.3は、旧定義に対するPhase状態としては`passed`である。しかし新Evidence Gateでは、次のLevelを証明しない。

- Level 5：自己検証・自己修正の証拠ではない。
- Level 6：検索計画、一次情報取得、出典付き統合の証拠ではない。
- Level 7：改善対象の自律発見、変更適用、baseline/candidate効果測定の証拠ではない。

したがって、Phase 2.3の`passed`をOperational Levelの昇格へ接続しない。既存の「Level 6相当」は履歴として保持し、新基準では再評価前の暫定記録として扱う。

### Required follow-up

- Phase 2.3の候補生成を、Level証明ではなくDevelopment Phaseの実行証拠として分類する。
- Level 5〜7を評価するには、それぞれの能力契約に対応したFunctional / Failure / Operational fixtureを別途作る。
- `verifiable: true`のような自己申告・固定値を、独立検証結果へ昇格させない。
- Phase 2.3を継続利用する場合も、候補の新規性、実験実行、効果測定、ユーザー価値を別フィールドで保持する。