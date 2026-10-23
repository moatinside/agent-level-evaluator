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

## ADR-003 — Measurement-first capability evaluation

- **Status**: accepted
- **Accepted at**: 2026-09-15 JST
- **Scope**: Capability追加、評価項目追加、Evidence設計、実務シナリオ評価
- **Decision source**: ユーザー承認（Discord message `1549315276565381153`）

### Context

理想的なAgent能力を先に細分化すると、実際には観測・検知・評価できない項目が増え、形式的なチェックや根拠のないスコアへ流れるリスクがある。特に「問いの浅さ」や「CXOらしさ」のような意味概念は、テキストだけで直接判定できない場合がある。

### Decisions

1. Capabilityや評価項目は、理想能力からトップダウンで増やさず、観測可能性、検知方法、評価方法を確認した後に定義する。
2. 評価設計を次の順序で実施する。
   ```text
   観測可能性の棚卸し
     → 検知可能なイベント
     → 評価可能性
     → Capability定義
     → 実務シナリオ適用
   ```
3. 評価可能性を、(A)決定的に機械評価、(B)Trace＋人間Calibration、(C)実案件Outcome、(D)現時点では評価不能の4層に分類する。
4. Dは正式なOperational Level契約に追加せず、研究仮説として保留する。未観測は成功・失敗のいずれにも変換せず、`inconclusive`として扱う。
5. 「問いの浅さ」などの潜在概念を直接採点せず、問いの変化、変更理由、根拠Evidence、判断への影響をTrajectoryとして観測する。
6. 新しい項目には、観測データ、取得元、検知方法、評価方法、未観測時の扱い、誤検知・見逃しの確認方法を定義する採用ゲートを適用する。
7. Level 1〜9の既存定義とEvidence Gate、Human Promotion Gate、Production／cron承認境界は維持する。本ADRはLevelの再定義や自動昇格を意味しない。

### Consequences

- Capability一覧は少数から始まり、観測経路の実証後にのみ拡張する。
- Tool、Trajectory、Outcome、保存・検知状態を分離して評価する。
- テキスト上の更新確認と、事業上の有効性確認を別Evidenceとして扱う。
- 直接測れない概念を、説明文の増加だけでPassにすることを防ぐ。
- 評価器の不足とAgent能力の不足を別々に切り分けられる。

### Required follow-up

- `docs/measurement-first-capability-design.md`に従い、現行TraceとCollectorの観測可能性インベントリを作成する。
- 新しいCapabilityを`contracts/level-contracts.yaml`へ追加する前に、採用ゲートを通過させる。
- Shadow環境で、正常、失敗、未観測、捕捉失敗、評価不整合を分離して確認する。

## ADR-002 — Evidence quarantine for historical contract failures

- **Status**: accepted
- **Accepted at**: 2026-09-25 JST
- **Scope**: Persisted Evidence with historical schema, configuration identity, integrity, or origin failures
- **Decision source**: User approval in Discord

### Decision

Historical invalid Evidence is not deleted, rewritten, or relabeled as valid. Files whose Evidence records are all invalid under the current Promotion Gate are moved byte-for-byte to `evidence-quarantine/`, outside the active scan roots. The migration is recorded in `evidence-quarantine/manifest.json` with source and destination paths, record counts, reason categories, and file hashes.

Mixed files containing both valid and invalid Evidence are not moved automatically. A current configuration rerun produces new Active Evidence and is referenced as regenerated coverage, not as an in-place repair of the historical record.

### Operational reporting

The current evaluator reports these states separately:

- `records_considered`: Active Evidence accepted by the current gate
- `active_invalid_record_count`: invalid records still in active scan roots
- `quarantined_historical_record_count`: records retained outside the active scan roots
- `quarantine_audit_status`: manifest and file-integrity result

A quarantine audit failure is not silently ignored. It is reported as a failed audit and blocks any claim that historical preservation is verified.

### Consequences

- The active evaluation report can show zero active invalid records without destroying negative evidence.
- Historical records remain available for forensic review and reason analysis.
- Quarantine placement must remain outside `operational-evidence/` because the active Promotion Gate scans that directory recursively.
- Future collection should validate in staging and publish only validated records to Active Evidence; failed output should enter quarantine.

## Decision note — WP5 source architecture

- **Status**: selected design direction; producer contract and runtime integration remain unimplemented; source access conditions remain unspecified
- **Decision source**: user chose option A in response to the assistant's recommended choices in Discord message `1562490297089523805`; treat as acceptance of the presented design direction, not an independently formulated architecture requirement
- **Decision**: choose option A's producer-owned event-row architecture: a producer stage upstream of WP5 emits ordered, closed-code event rows grouped by an episode manifest. WP5 resolves the complete closed episode using user-specified `scope_ref` and `episode_ref`; it does not reconstruct episodes from aggregate V2 trace counts or accept caller-selected event subsets.
- **Compatibility constraint**: the existing work plan defines WP4 as a transport-only Gateway Runtime Observer. It does not currently produce semantic episode rows. The selection does not establish that the existing WP4 Observer is the intended producer or authorize expanding its responsibilities; producer ownership and input source remain unresolved.
- **Scope boundary**: this selects the architecture only. It does not authorize Gateway changes, live event capture, real-conversation access, durable storage, or external sharing.
- **Consequences**: validate the manifest + ordered-row contract with synthetic SQLite fixtures first. The `closed` flag and expected count are producer assertions, not independent capture-completeness proof.
- **Open before runtime**: establish the actual source ownership/access boundary and ACL; do not assume a separate human approver, because the requester is the sole project decision-maker. Fix the exact snapshot/profile/episode scope and any source-side access constraint; verify complete-capture receipt and recovery reconciliation for JSONL spool/shutdown snapshot; runtime episode-boundary evidence; user-specified semantic codebook and observed/derived provenance; opaque-reference custody and retention; packet display/retention and independent rater conditions. Recommended initial row policy is recorded in `docs/wp5-episode-assembler-design.md`; it governs continued fixture/contract work and does not itself identify or open a live source.

## WP5 recommended source-adapter boundary

- **Status**: selected target architecture; source admission and runtime integration remain gated
- **Decision source**: user direction in Discord message `1562639576923775088` to proceed with the recommended configuration
- **Decision**: keep WP4 transport-only. The Evaluator owns a source-agnostic `EpisodeResolver` contract and assembly. Source-specific adaptation and semantic event production remain a separate Evaluator-side stage consuming a user-selected, source-side immutable snapshot through an injected read-only connection. The user is the sole project decision-maker; no separate approver is presumed. Actual source access constraints still apply.
- **Initial admission policy**: one explicit episode boundary and one lineage; sort by source insertion ID; reject inactive/rewind or compaction-archived history, unresolved ancestor/child lineage, incomplete pagination, and any unresolved spool/recovery artifact. Require a source-side complete-capture receipt plus recovery reconciliation; row counts, `ended_at`, or `closed` alone are insufficient. Fixture-only `AdmissionEvidence` now requires eight explicit positive checks; it validates resolver contract shape, not the authenticity of source receipts.
- **Read consistency**: manifest and event rows are read inside one SQLite snapshot. A WAL fixture with a second writer reproduces a mutation between the two reads; the resolver must return the pre-update row set. This protects fixture resolution from mixed generations and does not prove an external snapshot is immutable or complete.
- **Content and retention**: conversation text may be inspected only for a user-specified, bounded purpose and scope through a source access path that is actually permitted; raw conversation or tool arguments are never persisted in the Evaluator. Snapshot storage, expiry, and deletion terms must be explicit before any read. Emit only allowlisted codes and opaque refs. Until those conditions are concrete, do not read source content and return `input_unavailable`.
- **Boundary**: this selects design defaults and a local interface, and authorizes continued local fixture/contract work. It does not by itself establish the source's ownership/access boundary, identify a snapshot, or execute a live SessionDB read or Gateway/runtime change.

## WP5 calibration comparator response contract

- **Status**: local synthetic contract implemented; independent human calibration remains unverified
- **Contract**: each rater response carries a bounded opaque `rater_ref`. The comparator rejects the same response file or repeated `rater_ref`; distinct refs with identical labels are counted as agreement, because identical judgments can be valid independent outcomes. The output omits `rater_ref`.
- **Evidence boundary**: a distinct ref is an input integrity check, not proof that two different people independently rated blind packets. Assignment, blinding, actual rater participation, and packet safety remain separate evidence requirements.

## Decision note — WP3 category-count reporting

- **Status**: accepted; evaluator fixture implementation verified, runtime integration remains open
- **Accepted at**: 2026-10-23 JST
- **Decision source**: user selected count-only reporting and category-level acceptance criteria in the current Discord exchange
- **Decision**: replace per-event accepted/rejected/duplicate/conflict lists with category-level counts. Reports must not expose per-event opaque references.
- **Counting contract**: `accepted` counts exact consumer ACKs; `rejected` is split by invalid outbox rows, invalid ledger rows, and invalid receipts; `conflict` reports Outbox and ledger conflict rows separately. `duplicate` remains `null` with a reason code until duplicate occurrences are durably observed. Reason buckets count rows/receipts, not unique events, and must not be summed as a distinct-event total.
- **Boundary**: this resolves the report-privacy format only. It does not complete WP2/WP3 or authorize Gateway, SessionDB, R2, or production access.
