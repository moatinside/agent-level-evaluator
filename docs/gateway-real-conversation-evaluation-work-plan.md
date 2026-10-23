# Gateway実会話観測からAgent能力・レベルを評価するための作業計画書

- 作成日: 2026-10-20
- 状態: **WP0/WP1のv5 exact-set静的レビューPASS。2026-10-20の依頼によりWP2 transport primitiveとWP3 reportの隔離実装・fixture検証を開始。WP2 full acceptance／Gateway接続／実会話評価は未完**
- 対象:
  - Hermes Gateway: `/Users/yokapro/.hermes/hermes-agent`
  - Evaluator: `/Users/yokapro/Developer/agent-level-evaluator-upstream`（`moatinside/agent-level-evaluator`）
- この計画書が承認しない操作: Gateway再起動、設定有効化、LaunchAgent再有効化・変更、cron追加・変更、実会話の追加収集、Strict mode、外部送信、Agent Levelの自動昇格、commit、push。

## 1. 目的

Hermes Gatewayを通る通常の会話を、応答本文・ユーザー本文・生の識別子をEvidenceへ保存せずに観測する。観測結果を、以下の三層に分けて監査可能にする。

1. **Transport** — Gatewayイベントが取得・永続化・consumer読込・ACKまで到達したか
2. **Measurement** — 能力評価に必要な会話軌跡・ツール実行・訂正・結果の情報が、完全・部分的・未観測のどれか
3. **Evaluation eligibility** — 実際にAgent能力・レベルの評価へ使えるか。未観測・不完全・Shadow-onlyの記録は昇格入力にしない

最終的な到達点は、「Gatewayを通る通常会話について、収集済み件数と評価可能件数を混同せず、根拠付きで能力評価を行い、人間の承認なしにはLevelを昇格しない」状態である。

## 2. 今回の検証で確認した事実

### 2.1 Gateway起源として記録された観測は存在する

`/Users/yokapro/.hermes/runtime-evidence/agent-level/live-shadow.jsonl` を本文を表示せずに集計した。

- JSONLは **119件**、破損行は0件
- 記録期間: **2026-10-05T03:12:51Z〜2026-10-16T09:22:08Z**
- 全119件に `evidence_origin=hermes_gateway` とopaqueな `runtime_event_ref` がある
- 回答本文・メッセージ本文に相当するトップレベルキーは0件
- 全119件に整合性ハッシュがある

これはGateway起源として記録されたmetadata-only Evidenceが存在することを示す。一方、既存JSONLはraw session/message referenceを保存しないため、119件の各行が通常会話だったことは、このファイル単独では再証明できない。今後はsource/task classificationとcanonical receiptをV2必須項目にする。

### 2.2 ただし119件はAgent能力・Levelの評価結果ではない

119件の集計値はすべて次のとおりだった。

- `result=inconclusive`
- `acceptance_results.final_status=inconclusive`
- `negative_evidence=safe-stop / inconclusive`
- `level=5`
- `capability_id=self_reflection`
- `environment_class=shadow`
- `evidence_class=O`

`live_shadow_policy.py` は単一の完了応答を正規表現で検証するだけである。さらにEvidence生成時に `level=5` と `capability_id=self_reflection` を固定設定している。

```text
Gatewayの完了応答
  → required_patterns / forbidden_patterns による単一応答の正規表現検証
  → 固定された L5 / self_reflection ラベル
  → Shadow JSONL
```

この固定ラベルは、評価ルーティング用metadataであって、実測から導いたLevelではない。

### 2.3 `inconclusive` の直接原因として確認できる範囲

現行 `config.yaml` と、2026-10-14時点のbackupの両方で、`required_patterns` と `forbidden_patterns` はいずれも0件だった。`response_validation.py` は両方が空の場合、`no-rules` として `inconclusive` を返す。

隔離した実行でも、空ルールの入力は `inconclusive` を返し、Evidenceへ固定L5ラベルを付けて保存することを確認した。

ただし、119件の作成時にGatewayが読み込んでいた正確な設定スナップショットは保持されていない。したがって「119件の全件が空ルールだけでinconclusiveになった」とまでは断定しない。**空ルールは再現済みの原因候補であり、作成時設定との一致は未確認**である。

### 2.4 Legacy Evidenceとして隔離すべき理由

現行の `collect_operational_evidence.py` が生成する契約フィールドには `execution_mode`、`decision`、`side_effect_status` がある。一方、既存119件にはこの3フィールドがない。

よって119件は、現行ソースと同一の完全契約で作成されたと確認できない。安全な扱いは次のとおりである。

- 削除・書換え・再ラベル付けはしない
- `legacy_gateway_shadow` として読取専用で保持する
- Transportの過去観測としてだけ集計できるようにする
- 能力評価、Human Calibration、Promotionの分母・分子には使わない

### 2.5 現在は観測が無効

現行Gateway設定は次の状態である。

- `evaluator_shadow.enabled=false`
- `evaluator_shadow.capture_runtime_evidence=false`
- `mode=shadow`

2026-10-14時点のbackupでは、上の2フラグはtrueだった。現在の無効設定へ至った正確な変更時点・理由は、この調査では確定していない。

### 2.6 接続されていない経路

1. LaunchAgent `com.local.agent-level-evaluator.blue` は、`/Users/yokapro/agent-level-evaluator/blue/repo/evals/run_evals.py` を毎時実行する設定である。
2. このrunnerは `~/.hermes/skills/**/SKILL.md` をYAMLの正規表現で検査する。Gateway JSONLを読まない。
3. Gatewayの実会話JSONLは `~/.hermes/runtime-evidence/agent-level/` にあり、Evaluatorの既定consumerは `<root>/operational-evidence` と `<root>/evaluation-reports` だけを走査する。
4. 実際に既定consumerへ外部runtime sinkを指定しても、走査ファイル数は0件だった。
5. Promotion GateはShadowを既定で除外する。これは安全上正しいが、Shadowの読取・監査の経路は別に明示する必要がある。
6. Gateway側は `live_shadow_policy.py` を直接subprocess起動する。一方Evaluator側には別の `scripts/hermes_shadow_adapter.py` があり、`completed_response`イベントを受ける隔離Adapterとして存在する。両者は現在、単一の正規経路として結線されていない。

### 2.7 Gateway境界テストが証明したこと・していないこと

`tests/gateway/test_evaluator_shadow_runtime.py` と `tests/gateway/test_evaluator_shadow_config.py` は、合計 **26 tests passed** だった。

このテストは次を証明する。

- Shadow verdictが通常の最終応答を置換・停止しない
- scopedなmetadataをAdapterへ渡す設計
- timeout、malformed response、collector保存失敗時にShadow配信を変えない
- 設定のopt-in条件

一方、`subprocess.run`をmockしたケースを含むため、次は証明しない。

- 実Gatewayが現行ソースをロードしていること
- 実会話1件がOutbox/ledger/reportまで届くこと
- 通常会話の問い・根拠・ツール・訂正・結果を評価できること
- Agent Levelが正しく計測できること

## 3. 問題の定義

現状は「実会話のイベント発生をmetadata-onlyで観測した形跡」はある。しかし、次の4点が欠けるため、Agent能力・Level評価システムにはなっていない。

1. **正規経路の不在**: Gateway sink、Evaluator consumer、Reportのrootが一致していない
2. **Schema世代の不一致**: 既存119件は現行契約の必須区別フィールドを欠く
3. **測定対象の不足**: 最終応答の正規表現だけでは、会話軌跡・Evidence更新・ツール利用・ユーザー訂正・外部成果を測れない
4. **ラベルの誤用リスク**: producerが固定で付けるL5/self_reflectionを、測定済みLevelと誤解し得る

## 4. 推奨アーキテクチャ

### 4.1 基本方針

Evaluatorの事業ロジックやLevel採点をHermes Gatewayへ入れない。Gatewayが担うのは、**turn finalizerが終端状態とcanonical persistenceの結果を確定した後、その結果をmetadata-onlyで捕捉し、耐久Outboxへ渡すことだけ**とする。persistence未確認もcapture対象にできるが、確認済みreceiptのない記録は評価対象外とする。Evaluator repositoryが、consumer、ledger、report、semantic evaluation、human calibrationを担う。

```text
[Hermes Gateway]
  turn finalizer settled + persistence outcome known
  (receipt may be absent; status is explicit)
          |
          v
  RuntimeEvidenceObserver (thin / metadata-only)
          |
          v
  durable local outbox
          |
          |  idempotent consume + read-back ACK
          v
[Agent-level Evaluator]
  canonical ledger -> transport report
          |
          +--> measurement assembler (scoped, read-only)
                    |
                    v
               semantic evaluator / human calibration
                    |
                    v
               two-axis capability report
                    |
                    v
               human promotion decision
```

### 4.2 Option Aとの整合

以前の「Hermes本体を改造せず独立運用」という方針を文字どおり維持するなら、State DBを外部sidecarで監視する方法がある。しかし、sidecarは「turn finalizerが確定したpersistence結果」「最終delivery前後」「中断・失敗・再試行の正確な境界」を所有しない。

今回の目的がGatewayでの**実会話の正確な観測**である以上、推奨は以下である。

- Hermes側: genericな薄いObserver/Outbox hookのみ
- Evaluator側: すべての評価・集計・昇格ロジック

これは現在の直接subprocess型Shadow実装を、評価器非依存のCapture境界へ縮小する案である。ただしこれはHermes側の変更を含むため、実装開始前に別途承認を要する。

## 5. V2 Runtime Evidence Contract

### 5.1 永続化してよいEnvelope

V2は明示allowlist方式とする。未知のネストキーを含むEnvelopeは拒否し、raw contentのハッシュ化も許可しない。

| 区分 | 永続化する情報 | 永続化しない情報 |
|---|---|---|
| 参照 | keyed-HMACによるevent / session / episode / scope reference、key version | Discord ID、session ID、message IDの生値、単純SHA-256による低エントロピーID |
| 実行 | event kind、開始・終了時刻、完了/失敗/中断、canonical persistence receipt、delivery receipt状態 | 応答本文、ユーザー本文、draft、ツール引数、添付本文、raw exception |
| 構成 | runtime build/version、承認済みmanifestから作るconfiguration ID（承認前はnull） | 秘密情報、OAuth/API credential、`.env`の内容、raw content由来hash |
| 量的trace | tool call数、turn/iteration数、補正回数、bounded error code | tool name、tool output、ファイルパス、コマンド内容 |
| Envelope状態 | `transport_status=captured`、`measurement_status`、`evaluation_eligibility` | downstream ACK/measurement completion/eligibilityをEnvelopeへ書き戻すこと、producer断定のLevel/Capability/Promotion verdict |

### 5.2 必須の状態分離

| 軸 | 例 | 意味 |
|---|---|---|
| `transport_status` | Producer Envelopeでは `captured` のみ。Outbox/Consumerのpending / persisted / acknowledged / duplicate / conflict / unavailableは別のtransport receipt/reportに記録 | Envelopeのcapture段階と配送状態を混同しない。ACKは能力の証明ではない |
| `measurement_status` | Producer Envelopeでは not_assessed / partial / not_observable。`complete` は後続の測定記録のみ | Producerは評価入力の完全性を断定しない |
| `evaluation_eligibility` | Producer Envelopeでは transport_only / excluded。`eligible` は後続EvaluatorとHuman Calibrationの記録のみ | Producerは評価・昇格資格を付与しない |
| `semantic_verdict` | pass / partial / fail / not_observable | calibrated evaluatorまたは人間が付ける別の意味評価記録 |

Producer Envelopeはimmutableなcapture事実に限定する。Outbox persistence、Consumer ACK、report visibility、measurement completion、eligibility、semantic verdictは別レコードまたはReportで表し、Envelopeを書き換えて後段状態を遡及表示しない。

`level`と`capability_id`はGateway producerが固定値を付けない。Evaluatorが、契約バージョンとEvidenceを満たしたときだけ導出する。

### 5.3 能力評価の対象

単一のLevel値で会話を採点しない。少なくとも次の2軸を分離する。

1. **実行自律性** — 根拠収集、仮説更新、ツール実行、失敗時安全停止、結果の記録
2. **共同形成** — ユーザー訂正の受け取り、問いの再構成、未確実性の明示、次の検証設計

会話本文を参照しないTransport記録は、このどちらの意味評価にも十分ではない。通常会話のsemantic evaluationは、後述の承認済みscopeに限定したread-only episode assemblerとHuman Calibrationを経る。

## 6. 作業パッケージ

### WP0 — 現状固定・正規経路の決定

- **対象:** 両repository、既存119件
- **目的:** 作業前の事実、所有者、正規sink/report rootを固定する
- **作業:**
  1. Gateway checkoutの未コミット差分を分類し、既存変更を保全する
  2. Evaluatorのclean baseから新規worktreeを作る。既存dirty treeをreset/cleanしない
  3. Gatewayのcapture call site、canonical persistence receipt、delivery call site、現行sink、Evaluator consumer、reportを一枚のsource mapにする
  4. 119件のfile hash・行数・schema差異だけをmanifest化する。記録本文は読まない
  5. Legacy partitionの除外規則を文書化する
- **負の受入条件:** Legacy JSONLを削除・移動・修復・Promotion入力化しない
- **完了成果物:** source map、Legacy manifest、canonical root決定記録
- **次ゲート:** canonical ledgerとretention ownerの人間承認

### WP1 — V2 Contract・Privacy Threat Model

- **対象:** Evaluator repositoryのschema、契約、test fixtures
- **目的:** 何を保存し、何を保存せず、何を測定不能として扱うかを固定する
- **作業:**
  1. V2 EnvelopeのJSON Schemaとversion migration policyを定義する
  2. HMAC scope-referenceのkey owner、rotation、profile境界を定義する。key値はEvidence・ログ・repoへ出さない
  3. `transport_status`、`measurement_status`、`evaluation_eligibility`を必須化する
  4. producer-assigned Level/Capabilityを禁止し、legacy recordをmechanically excludedにする
  5. raw content、nested unknown key、low-entropy raw-ID hash、raw exceptionの検査を追加する
- **負の受入条件:** raw prompt/response、tool引数、raw識別子、認証情報をfixture・log・ledger・reportへ残さない
- **完了成果物:** versioned contract、privacy review checklist、schema validation tests
- **次ゲート:** V2 metadata contractの人間承認

### WP2 — Durable OutboxとConsumer ACK

- **対象:** Gateway側のthin capture module、Evaluator側consumer
- **目的:** captureと評価処理を分離し、応答経路をEvaluator subprocessから切り離す
- **作業:**
  1. Gatewayはturn finalizerが終端状態とpersistence結果を確定した後にV2 Envelopeをlocal durable outboxへenqueueする。未確認/失敗状態も明示し、receipt未検証の記録を評価対象外とする
  2. outboxは `event_ref + payload_hash + schema_version` でidempotencyを保証する
  3. consumerはEvaluator canonical ledgerへ保存し、保存済みのexact rowをread-backしてからACKする
  4. 同一event_refで異なるpayloadはconflictとして保持し、上書きしない
  5. Gateway応答パスはconsumer、semantic evaluator、reportを待機しない
- **負の受入条件:** `{status: ok}`だけのACK、consumer失敗時の原文再送、outbox失敗によるユーザー応答変更を許可しない
- **完了成果物:** Outbox state machine、ACK receipt schema、read-back tests
- **次ゲート:** isolated E2Eへ進む承認

### WP3 — Report・Promotion境界の再設計

- **対象:** Evaluator consumer、`evidence_report.py`、`promotion_gate.py`
- **目的:** Gateway観測の件数と評価可能Evidenceを明確に分離する
- **作業:**
  1. runtime ledger rootを明示設定化し、repository source treeとruntime dataを混在させない
  2. reportに emitted / outbox-persisted / consumer-ACKed / report-visible / measurement-complete / eligible の各数を出す
  3. ShadowとLegacyを既定Promotionからmechanically excludeする
  4. Shadow監査は明示flagでだけ閲覧可能にする
  5. configuration identityが異なる記録を混在集計しない
- **負の受入条件:** JSON Schema pass、outbox ACK、Shadow recordを能力評価・Promotionのsuccessと表示しない
- **完了成果物:** per-event IDを含まないcategory-level count report（accepted / rejected reason buckets / duplicate / conflict by boundary）、Promotion exclusion regression tests。duplicate occurrenceをdurableに観測できない場合は`null`＋reason codeを返し、0と扱わない
- **次ゲート:** runtime adapter統合の承認

### WP4 — Gateway Runtime Observer

- **対象:** Hermes Gateway
- **目的:** 実会話のcompleted / failed / interrupted / skippedを同一契約で観測する
- **作業:**
  1. current `EvaluatorShadowAdapter` の直接Evaluator subprocess依存を置換または隔離する
  2. turn finalizerがpersistence結果を確定した後にObserverを呼び、receiptまたは未確認状態を渡す
  3. completed、failed、interrupted、skippedを一度だけsettleし、persistence-unconfirmedは明示状態として評価対象外にする。Outbox自体のunavailableはEnvelopeで自己報告できないため、別の分母計測を設計する
  4. Gateway設定はversioned、explicit opt-in、既定OFFとする
  5. timeout、lock、disk/write failure、consumer unavailableで正常応答が変わらないことを測定する
- **負の受入条件:** Strict mode、delivery hold、応答本文の保存、Evaluator処理待ち、実会話送信を実装検証に使わない
- **完了成果物:** hermetic Gateway runtime tests、latency comparison、metadata-only scan result
- **次ゲート:** bounded Shadow pilotの運用承認

### WP5 — 実際の会話軌跡を評価するEpisode Assembler

- **対象:** Evaluator repositoryのread-only resolverとsemantic evaluator
- **目的:** 単一最終応答では評価できない「問いの更新・Evidence参照・ツール利用・ユーザー訂正・次の検証」を、必要最小限のepisodeとして扱う
- **作業:**
  1. 選択済みのsource方式Aに沿い、Evaluator側のsource adapter + semantic producerを推奨配置とする。source共通`EpisodeResolver` contractとmanifest + ordered-rowをfixtureで検証する。sourceの所有・アクセス境界、対象scope、入力データ、observed/derived provenanceはruntime admission条件として確定し、WP4はtransport-onlyに保つ。ユーザー以外の意思決定者は前提にしない
  2. episodeに必要な参照を固定する: 初期問い、Agent action summary、Evidence reference、更新理由、ユーザーfeedback type、decision impact、next validation
  3. 実会話本文の処理が必要な場合は、ユーザーが対象scope・目的・アクセス可能性・保持境界を具体化し、source管理境界で許容される場合に限り、bounded memory-only処理を行う。条件が揃わない間は接続せず、ledgerにはrubric label、opaque ref、bounded rationale codeのみを保存する
  4. 入力が不足するケースは推測せず `not_observable` または `partial` とする
  5. semantic evaluatorとHuman Calibrationのラベル軸を一致させる
- **負の受入条件:** user correctionを自律更新と誤認しない。外部成果・顧客購買・Go/No-Goの正しさを会話構造だけから判定しない
- **完了成果物（fixture-only）:** episode contract、closed-code sanitized evidence、metadata-only blind packet（人手採点用の表示・保存は未実装）
- **採用済みsource policy:** source-agnostic `EpisodeResolver`の背後にEvaluator側read-only adapter + semantic producerを置き、WP4はtransport-onlyに維持する。source管理側が用意するimmutable snapshotをread-only handleで注入し、ユーザー指定scope内のclosedな単一lineage episodeだけを全件・単一read snapshotで解決する。順序はsource row ID、上限はcallごとに明示。inactive/compacted履歴やrecovery未照合はfail-closed。raw本文・tool dataは永続化・ログ・stdoutへ出さず、episodeとpacketはin-memory限定。これは採用済み設計であり、再選定しない。
- **runtime gate:** SessionDBは候補に留まり未接続。実作業前に必要なのは、source管理境界内で選ばれたsnapshot/scopeとACL・complete-capture/recovery証跡の実測、semantic codebook/provenanceの実装根拠、本文を扱うならその目的と破棄条件、packet提示・rater responseの運用方法。別人の承認者は前提にしない。
- **判断記録:** ユーザーが唯一の依頼者・意思決定者である旨をDiscordで明示。source-admission checklistは別人の承認依頼ではなく、source境界と実行条件を定める記録として扱う
- **進捗:** fixture-onlyのcontract／episode assemblyは実装済み。直近API hardening後の再検証済み。推奨案AとEvaluator側adapter配置を採用し、WP4はtransport-onlyに維持。`EpisodeResolver`へper-call `max_event_refs`を必須で渡し、adapter内の上限適用とassembler側の返却行数再検証を実装。resolved結果にはcapture completeness、episode境界、single lineage、source order、inactive/compacted履歴、pagination、recovery照合の8項目からなる`AdmissionEvidence`を必須化し、欠落・false・非bool値を拒否するfixtureを追加。manifest/event rowを1つのSQLite read snapshotで読むよう修正し、manifest取得後・event取得前の同時更新で異世代を混ぜないこと、およびcaller既存read transactionを保持することをfixtureで確認（修正前test FAIL、修正後PASS）。API hardening前の記録ではfocused tests 38件PASS。Evaluator全体 `${HOME}/.hermes/hermes-agent/.venv/bin/python -m unittest discover -v -s tests -p 'test_*.py'` は210件PASS、失敗0/skip 0。対象2 Python fileの`py_compile`・Ruff、`git diff --check` PASS（いずれも最新API hardening前）。Evidenceは全てsynthetic/fixtureであり、Adapterの申告型とfixture transaction behaviorを検証するだけでsource receiptの真正性や実会話captureは未検証
- **直近変更・検証状態:** `ReadOnlyFixtureResolver.resolve`の必須`max_event_refs`、read-snapshot、校正比較器の独立性ガードを更新。各rater responseにopaque `rater_ref`を必須化し、同一file/refを拒否する一方、異なるrefで同じラベルが得られた場合は有効なagreementとして集計する。`rater_ref`は出力しない。WP5 focused suite 38件、校正比較器suite 7件、Evaluator全体215件がPASS（failures=0、errors=0、skipped=0）。対象4 Python fileの`py_compile`・Ruff、`git diff --check`、対象8ファイルのwhitespace/final-newline scanもPASS。実source接続なし。distinct refは入力整合性の確認であり、実raterの独立性・盲検・参加を証明しない。
- 2026-10-23の再検証: 対象worktree `feat/wp2-durable-transport` / HEAD `b3583a985a4d22f3ad147aa09f262f36a52a32ac`。初回実行ではWP5 suiteの2ケースが`source_schema_invalid`で失敗。隔離fixture probeで、WAL化後に全connectionを閉じてread-only connectionだけを開くとSQLiteが`unable to open database file`を返し、write-capable connectionで先にtableを読んでWAL/SHMを初期化するとread-only queryが通ることを確認。製品コードは変更せず、該当2 fixtureでwriterを保持し、read-only readerを開く前にtable queryを行うようテストsetupを修正。修正後はWP5 38/38、Human Calibration comparator 7/7、Evaluator全体215 tests PASS（errors=0、failures=0、skipped=1）、`py_compile`・Ruff PASS。read-only current-state reportは`unassessed`・0 records・`automatic_promotion=false`・`cron_cutover_allowed=false`、legacy auditは`ready_for_review`・`cron_cutover_allowed=false`。実source/SessionDB/Gateway API/R2/本番データには接続していない。
- **WP5 runtime未完了:** 実sourceの識別・所有/ACL、指定snapshot/scopeでのsource-side complete-capture receiptとrecovery reconciliation、semantic codebookとobserved/derived provenance、実データprivacy/completeness E2E、独立rater-B、sanitized packetの提示・response運用。これらは採用済みpolicyの再選定ではなく、実sourceがpolicyを満たすこととruntime経路の実装証拠が未取得という状態。初期row inclusion/lineage/pagination policyは設計値として確定済み。V2 Envelopeはaggregate countsのみで、fixture manifestの`closed`/countと`AdmissionEvidence`は実sourceの完全性を証明しない。**WP5全体は未完了。**

### WP6 — Hermetic E2EとFailure/Recovery検証

- **対象:** 両repositoryの隔離test environment
- **目的:** 実Gatewayの呼出順序を保ったまま、外部メッセージ・実Provider・実会話を使わず全経路を検証する
- **作業:**
  1. temporary Hermes home / isolated SessionDB / fake platform leaf / fake model responseで実Gateway runnerを通す
  2. producer → outbox → consumer → ledger → ACK → reportを接続する
  3. reportがexact committed rowを読むことを確認する
  4. response content/deliveryがcapture障害で変わらないことを確認する
- **必須ケース:**
  - completed turn
  - failed turn
  - interrupted turn
  - persistence未確認
  - malformed schema / nested forbidden key
  - outbox unavailable / lock / full相当
  - consumer unavailable
  - commit後ACK前の失敗とidempotent retry
  - duplicate event
  - same event_ref / different payload conflict
  - report read-back missing / stale
  - Legacy record
- **完了成果物:** 経路別テスト結果、read-back artifact、performance measurement
- **次ゲート:** bounded Shadow pilotの実行承認

### WP7 — Bounded Shadow PilotとHuman Calibration

- **対象:** 承認済みのplatform/channel/profile scopeのみ
- **目的:** 通常会話でtransport completenessとsemantic evaluationの妥当性を分離検証する
- **作業開始前に固定する事項:** scope、operator、開始/終了条件、最大event数、retention、監視項目、rollback手順、reconciliation query、incident時の停止権限
- **実施:**
  1. capture設定をShadow限定で有効化する
  2. Gatewayを外部shellから再起動する必要がある場合は、影響とrollbackを提示して別途承認を得る
  3. 1件以上についてoutbox、ledger、ACK、reportのread-backを実施する
  4. 実会話ケースをHuman Calibrationへ渡す前に、provenanceとsanitizationを監査する
  5. 独立rater-Bをrater-Aの結果非開示で実施し、agreement / overcall / undercall / not_observable mismatchを分離して報告する
- **負の受入条件:** Shadow成功をProduction、Strict、Level昇格、自動Promotionと扱わない
- **完了成果物:** Pilot runbook、transport report、calibration comparison、NO-GO/next-step decision record
- **次ゲート:** 継続観測、scope拡大、または停止の人間判断

## 7. 受入条件

| 判定対象 | 受入条件 |
|---|---|
| Gateway境界 | turn finalizerが終端状態とpersistence結果を確定した後、1 turnにつき最大1件のV2 eventを生成する。persistence未確認/失敗も明示し、そのEnvelopeは `excluded` とする。`confirmed` はcanonical receiptをconsumerが検証するまで信頼しない |
| Privacy | outbox、ledger、log、report、fixtureにraw本文・tool引数・raw ID・認証情報が存在しない |
| 応答安全性 | capture/outbox/consumer/reportの失敗で、通常の応答本文・delivery・persistenceを変更しない |
| Durable transport | ACKはexact persisted row、sink identity、event_ref、payload hashに束縛され、別transport receipt/reportとして記録される |
| Capture completeness | Outboxが利用不能でEnvelopeを残せない場合、それを「turnなし」と解釈しない。独立した分母・capture-unavailable計測をWP2の受入条件定義前に設計する |
| Recovery | duplicateはidempotent、同一ref異なるpayloadはconflict、ACK不確実時は再試行可能 |
| 可観測性 | emitted、persisted、ACKed、report-visible、complete、eligibleの各数を別々に表示する |
| 評価の誠実性 | producerの固定Levelを廃止し、未観測を`not_observable`として保持する |
| Promotion防止 | Shadow、Legacy、transport-only、semantic review未完了の記録はPromotion入力にできない |
| 実会話E2E | isolated E2Eの後、承認済みShadow scopeでGateway→outbox→ledger→reportのread-backができる |
| 人間校正 | 実会話由来でsanitizedなケースに限り、独立reviewを比較する |

## 8. 依存関係と承認境界

| 操作 | 必要な条件 | 別途承認 |
|---|---|---|
| WP0/WP1の文書・schema・isolated test | 計画内容の合意 | 実装対象branchの確認後 |
| Gateway source変更 | thin Observer設計とcore変更の許容 | 必須 |
| Gateway設定変更 | V2 contract + hermetic E2E成功 | 必須 |
| Gateway再起動 | 影響、実行tree、rollbackを提示 | 必須 |
| LaunchAgent変更/再有効化 | consumer運用手順とread-back成功 | 必須 |
| 実会話Shadow Pilot | runbookとscope固定 | 必須 |
| Level/Promotion | calibrationと必要Evidence gateを満たす | 必須 |

## 9. 最初の実装単位

実装許可を受けた場合も、最初に行うのはWP0とWP1だけである。Gateway設定は有効化せず、実Gatewayを再起動せず、既存119件にも触れない。

最初のレビュー対象は、以下の3点に限定する。

1. canonical source/sink/consumer/report map
2. V2 metadata-only contractとprivacy allowlist
3. Legacy 119件のimmutable exclusion policy

この3点を承認するまでは、Outbox、Gateway Observer、LaunchAgent、Shadow Pilotには進まない。

## 10. 現在の判断

- **確認済み:** Gateway実会話を観測する実装と実記録は存在した
- **未確認:** 119件の作成時にロードされた正確なGateway code/configuration identity
- **確認済み:** 現在のGateway設定はcapture無効
- **確認済み:** 現在のLaunchAgentはGateway Evidenceを消費しない
- **確認済み:** 既存の119件は固定L5ラベルかつ全件inconclusiveであり、Agent能力・Levelの測定値として使用できない
- **結論:** 既存実装を「観測がなかった」と扱うのではなく、**実会話観測のfirst attemptとして保全し、V2のtransport・measurement・evaluation境界を分離して作り直す**

## 11. 2026-10-20 WP0/WP1実行記録

### 作業場所・保全

- WP0/WP1作業時はEvaluator base commit `b3583a9` のdetached worktree `/Users/yokapro/Developer/agent-level-evaluator-worktrees/runtime-evidence-v2` で作業した。後続のWP2作業branchはSection 12に記録する。
- 元の`main` worktree、Hermes checkoutの既存未コミット変更、119件のJSONLは変更していない。
- Hermes source/config、Gateway、LaunchAgent、Provider、実会話には変更・接続・再起動を行っていない。

### 成果物

- `docs/gateway-runtime-source-map.md` — Gateway capture候補、persistence receipt、delivery seam、Evaluator consumer/report、所有境界。
- `docs/legacy-gateway-shadow-manifest.json` — 119件のファイルhash、件数、期間、schema差異、許可済み集計のみ。行内容・識別子を含まない。
- `schemas/runtime-evidence-envelope-v2.schema.json`
- `docs/runtime-evidence-v2-contract.md`
- `scripts/runtime_evidence_contract.py`
- `tests/test_runtime_evidence_contract.py`

V2は評価Evidenceではなく、metadata-onlyのtransport eventとして定義した。Producerが`level`、`capability_id`、semantic verdictやPromotion判定を出すことを拒否し、unknown nested fieldを含むeventを拒否する。V1記録は変換せず、V2入力として拒否する。

### 実行結果

- WP0/WP1初回実行: `python3 -m unittest discover -s tests -p 'test_*.py'` — **106件PASS**（既存91件に新規15件を加えた実行）。
- `python3 evals/run_evals.py --json` — **41/41 PASS**。これはskill構造チェックで、Gateway動作の証拠ではない。
- `python3 scripts/evaluate_current_state.py` — 対象worktreeでeligible record 0件、状態`unassessed`、自動昇格false、人間承認必須。
- `python3 scripts/audit_legacy_pipeline.py --root .` — `ready_for_review`。同出力はscheduler切替許可を意味せず、`cron_cutover_allowed=false`。
- `python3 scripts/evidence_report.py --summary` — 1 file/lineを走査、1件reject、eligible/considered 0件。走査対象は既存のPhase 2.3再分類JSONで、Gateway runtime JSONLではない。
- Legacy manifestのSHA-256・byte数・行数はsourceと一致。新規テキストのtrailing whitespace 0件、限定secret-pattern scan 0件。
- 実行環境にPython `jsonschema` / `fastjsonschema`、Node Ajv、Ruby `json-schema` がなく、第三者JSON Schema validatorによるdraft-conformance検証は未実施。ネットワークから依存を追加せず、ローカルvalidatorとschema-shapeのfixture検査を実行した。

### 独立レビューと修正

- 7成果物のhashを固定した読取専用レビューで、状態語彙の所有先不一致、persistence未確認の意味不整合、HMAC/receiptの未認証、未承認configuration hashの受入れ、timestampの形式差、自己申告provenanceの誤読リスクが指摘された。
- 作業計画と契約書でProducer Envelopeと後続transport/measurement/evaluation recordの所有先を分離し、turn finalizer確定後にpersistence未確認も明示的に記録する案へ整合した。未確認/失敗は`excluded`とし、Outbox利用不能をturn不存在と誤認しない独立分母をWP2の前提に追加した。
- 未承認の`agent_configuration_id` / `capture_configuration_id` はSchema上nullのみ許可。synthetic HMAC参照・persistence receiptは構造検査だけで認証扱いしないよう関数名と契約記述を明確化した。
- timestampはcanonical UTC（大文字`T`/`Z`、offsetなし、秒00–59）に統一。二度目のレビューでSchemaの粗い日付patternが`format` assertion任せと指摘されたため、Schema patternにGregorian月日・閏年制約を追加し、ローカルvalidatorは同じSchema patternを参照するよう修正した。
- `tests/test_runtime_evidence_contract.py`に日付patternの11ケース（閏年・非閏世紀・月末・offset等）を追加。focused suite **19件PASS**、全体`python3 -m unittest discover -s tests -p 'test_*.py'` **110件PASS**。追加のSchema/validator timestamp照合は8ケースPASS。
- `deleg_317f14e3`のレビュー対象は当時の別hash snapshot（plan SHA-256 `0d652d31…`）で、日時patternが不十分との指摘を受けた。後続の凍結`review-input-v3`（plan SHA-256 `e802e66a…`）ではGregorian日付・閏年patternへ更新済みであることを、`deleg_a7c501e7`のread-onlyレビューと400年周期の148,800候補照合で確認した（不一致0）。第三者JSON Schema validatorによる標準適合確認は未実施。
- `deleg_a7c501e7`はv3の7ファイルhash一致を確認し、前回の6指摘は閉じたと評価。追加のLow指摘（深い入力で`RecursionError`がvalidatorから漏れる）は、変更前に1,200階層fixtureで再現した。8192-byte下限preflightと上限付きcanonical serializationを追加し、同fixtureと1,000,000文字入力の拒否を確認した。
- 修正後の`tests/test_runtime_evidence_contract.py`は**21件PASS**、全体`python3 -m unittest discover -s tests -p 'test_*.py'`は**112件PASS**。修正前の回帰fixtureは`RecursionError`で失敗し、修正後は通過した。これはfixture検証であり、Gateway/runtime観測ではない。
- v3のレビュー後にvalidator/testが変わったため、そのレビューは現行candidateを承認していない。修正後ツリーのfresh independent review・人間承認まではWP2へ進まない。
- `deleg_b2f658a4`は`review-input-v4`（manifest SHA-256 `981a71a3624a19bac28b79f8e7fa82ec7b591a7d4efd963adf58b8e46e1f4556`）の7ファイルをhash照合し、全内容を静的レビューした。レビュー前後のmanifest・各file hashは一致。テスト・編集・mutable worktree・Gatewayへのアクセスなし。同一model/provider系列であり、cross-model independent reviewではない。
- v4のtimestamp pattern指摘は再現しなかった。JSON Schema文字列を`json.loads`したpatternのfraction部はdecoded regexのcodepoint `[92,46]`（backslash、period）に対応し、literal period escapeとして確認した。`.123Z`はpatternとlocal validatorの双方が受理し、単一backslashを含む不正なsuffixはpatternが拒否する。したがってこの指摘は未立証とし、schema/validatorの日時規則は変更していない。fractionと不正suffixの回帰testを追加した。第三者JSON Schema validatorによる適合性は未検証のまま。
- v4のLow指摘は再現した。従来の`seal_event()`は`canonical_json()`をサイズ制限なしで呼び、1,000,000文字入力を拒否せず、1,200階層入力で`RecursionError`を漏らした。`MAX_ENVELOPE_BYTES`ちょうどのhash前データにhashを追加した後の上限検査もなかった。`seal_event()`を上限付きserializer経由に変更し、hash前データとhash追加後のenvelopeを両方制限。超過は`event_too_large`、非JSON/deep inputは`not_json_value`のValueErrorとし、テストで3経路を固定した。
- 修正後の`tests/test_runtime_evidence_contract.py`は**25件PASS**、全体`python3 -m unittest discover -s tests -p 'test_*.py'`は**116件PASS**。`py_compile`と`git diff --check`もexit 0。fixture検証のみで、Gateway/runtime接続・実会話・第三者JSON Schema validatorは未実施。
- v4は修正前snapshotのレビュー結果であり、このcandidateを承認していない。修正後のexact-set fresh reviewと人間承認まではWP2へ進まない。

### 未決・停止ゲート

- canonical runtime-ledger root、retention owner、HMAC key custodian/rotation、read-only resolver境界は未決。source mapには選択肢と責任境界を記録したが、採択はしていない。
- V2 contractはdraft。HMAC参照とpersistence receiptの構文・構造を検査するだけで、実鍵による認証やcanonical persistenceの真正性確認はしていない。source/task classificationも構造上のclaimである。
- このSection 11作成時点ではWP2（Outbox/consumer ACK）、WP3（report/promotion接続）、WP4以降（Gateway変更・E2E・Shadow Pilot）は未着手だった。後続状態はSection 12を参照。
- canonical runtime-ledger root、retention/deletion ownerと期間、HMAC key custodian/storage/rotation/domain separation、read-only resolver scope、Outbox unavailable時の独立分母は未決。WP0/WP1当時は人間によるsource map・Legacy exclusion・V2 privacy contractの承認までWP2を停止する判断だった。2026-10-20の依頼はisolated developmentの開始を認めるものとして扱い、未決ポリシーの採択と実runtime接続には使わない。

## 12. 2026-10-20 WP2/WP3 isolated execution update

### 承認と作業場所

- ユーザーの「え！じゃWP2以降着手してよ」を受け、WP2の隔離開発を開始した。Gateway起動・設定・実会話・Provider・LaunchAgentの許可は含めていない。
- v5 exact-set reviewはmanifest `720fb7464d7c791745ed1f91a248071cdfa0197849d3ec5fd7bf542e32597924` と対象file hashesの一致を確認し、静的レビューPASS。実行テスト・runtime確認はレビュー範囲外。同一model/provider familyでありcross-model independent reviewではない。
- Evaluator worktree: branch `feat/wp2-durable-transport`, base `b3583a985a4d22f3ad147aa09f262f36a52a32ac`。開始時点のローカル`origin/main`と同一。
- Hermes worktree: `/Users/yokapro/Developer/hermes-worktrees/runtime-evidence-wp2`, branch `feat/runtime-evidence-outbox`, base `f09ccc3aa78294bbc391a1074ee4212f6aef9cb7`。開始時点のローカル`origin/main`と同一。
- remoteへのfetchは行っていない。したがってlocal `origin/main`以後のremote更新有無は未確認。既存Hermes checkoutのbranch `work/agent-level-runtime-evidence` と18件の既存未コミット差分は保全し、変更していない。
- commit、push、reset、clean、削除は行っていない。

### WP2 transport primitive

- Hermes: `gateway/runtime_evidence_outbox.py`。明示bootstrap済みDBのみを使用し、検証callbackを通ったV2 envelopeをSQLite Outboxへ保存する。event_refの重複はidempotent扱い、同じevent_refの異なるpayloadは別conflict行に保存し、既存行を上書きしない。consumer用の別プロセスやsubprocessは起動しない。
- Evaluator: `scripts/runtime_evidence_consumer.py` と`schemas/runtime-evidence-transport-ack-v1.schema.json`。Outboxをread-onlyで読み、明示指定されたledger DBへ保存する。新規接続ごとのexact-row read-backを確認してから、Envelopeと分離したACK receiptを保存・再読込する。event/receiptの重複・payload conflictを区別する。
- Outbox/ledger DBはruntime data path上で自動作成・migrationしない。initializerは明示呼出しのみ。通常のenqueue/consumeは既存のversioned schemaを検査し、欠落・不正schemaではfail closedする。
- Evaluatorの `tests/test_runtime_evidence_consumer.py` は、再試行、並行重複、conflict、ACK順序、read-only Outbox、same-version malformed DB、DB byte不変、explicit bootstrapをfixtureで検証する。

### WP3 transport report slice

- `scripts/runtime_evidence_transport_report.py` に、明示指定したOutbox/ledger/sink/max-recordsのみを読むread-only reportを追加した。既存`evidence_report.py`、`promotion_gate.py`、Agent Level判断には接続していない。
- Outbox、ledger、receiptがevent_ref・payload_hash・schema version・exact row hashで一致した件数だけをACKとして数える。未知のemitted分母、measurement-complete件数、semantic evaluation eligibilityは`null`と理由付きで返す。未観測を0として扱わない。
- report出力はcounts/statusに限定し、path、event reference、payload hash、本文、Levelを出さない。

### 検証結果

- 2026-10-21、Evaluator全fixture suiteはstreaming regression追加前の時点で`python3 -m unittest discover -s tests -p 'test_*.py'` — **160 tests, failures=0, errors=0, skipped=1**。skipは標準Python環境に`jsonschema`がないため。続行後の161件実行結果は下記。
- 2026-10-21の最終再実行: Hermes canonical runner `HERMES_PYTHON=/Users/yokapro/.hermes/hermes-agent/.venv/bin/python scripts/run_tests.sh tests/gateway/test_runtime_evidence_outbox.py` — **23 tests PASS, failures=0**。新worktreeにpytest環境がなかったため、既存Hermes venvを使用。
- 2026-10-21の最終cross-repository fixture E2E: 両repositoryの現在のsourceを同一TemporaryDirectoryのDBに接続し、**Outbox persisted → consumer ACK → exact ledger read-back → separate receipt → report_visible=1**を確認。Draft 2020-12 Envelope/ACK検証も同じHermes venv Python 3.11.15で実行。Hermesの`HERMES_HOME`はmodule import前にfresh TemporaryDirectoryへ設定し、ユーザー設定を読み込まない隔離実行とした。`emitted=null`は`independent_capture_denominator_not_implemented`の理由付きで維持。これはfixture E2EでありGateway runtime実行ではない。
- 2026-10-21の続行監査で、`max_records=100,000`とEnvelope 8192-byte／receipt 2048-byte上限の組合せでは、`fetchall()`が最大1,843,200,000 bytes（約1,757.81 MiB）のpayload行を同時に保持し得ることを確認（Python側の複製・object overheadを除く）。payload queryでの`fetchall()`を禁止する回帰testは修正前に失敗。Reportをcursor iteratorで逐次処理し、lookup mapにはcanonical EnvelopeのSHA-256 digestと固定metadataを保持する方式に変更。Focused report tests 10/10、Evaluator全fixture suite 161 tests（failures 0、errors 0、skipped 1）PASS。変更Python 2ファイルのRuff、`ty check`、`py_compile`、`git diff --check`もPASS。cross-store一致はcanonical digest・payload hash・schema versionで検証し、byte列をmapに保持しない。fixture/static検証であり、本番メモリ使用量は未測定。
- 2026-10-21の再実行（Evaluator worktree、既存Hermes venv Python）: 全fixture suite **161 tests PASS、skip 0**。標準Pythonでskipされた`jsonschema`依存のlegacy-schema拒否assertionを含めて通過。Evaluatorの変更14ファイル（Python 7）とHermesの変更2ファイルについて、JSON parse、Python compile、trailing whitespace/final newline確認を実行。両worktreeの変更PythonはRuff・`ty check` PASS、`git diff --check` PASS。
- 2026-10-21のbounded-report follow-up: canonical SQLite DDLはTEXT列長を制約しないため、Envelope/receipt BLOB上限だけでは`event_ref`、`payload_hash`、ledger `record_hash`が未制限のままPythonへfetchされる。Outbox・ledger・対象receiptの3回帰testは旧実装でそれぞれ失敗。V2 Schema由来のevent_ref 96-byte・payload_hash 71-byte・record_hash 71-byte上限をSQLでrow取得前に検査し、超過時は`report_record_size_exceeded`でfail closedとした。Focused report tests **16/16 PASS**。さらにSQLite TEXTの文字数とUTF-8 byte数が異なるケースをOutbox/ledger/receipt各境界で追加し、byte上限超過時にpayload decodeまたはreceipt validationへ進まないことを確認した。修正後の全fixture suiteは標準Python **167 tests、failures=0、errors=0、skipped=1**、既存Hermes venv **167 PASS、skip 0**。Ruff、`ty check`、`py_compile`、`git diff --check` PASS。Outbox→consumer ACK→report fixture E2Eも再実行し、`report_visible=1`、`emitted=null`を確認。実Gateway/runtime未接続。

- 追加の独立process試験では、親processがSQLite writer lockを保持し、producer/consumerの各2 processが`BEGIN IMMEDIATE`へ到達してロック解放まで未完了であることを確認。解放後はproducerが同一event_refを1行だけ保存し、consumerもevent 1行・receipt 1件へ収束した。Hermes側はOutbox commit後・read-back前、Evaluator側はledger commit後・ACK前とreceipt commit後・ACK返却前にprocessを強制終了し、再実行で重複せず回復することを確認した。
- 追加のSQLite fault-injectionでは、Outbox insert・ledger insert・ACK receipt insertそれぞれのSQL実行後に例外を発生させた。transaction rollback後の`in_transaction=False`、DB整合性、部分書込なし、再試行後のexact read-backとACK回復を確認した。
- Outboxの同一version DBに行を書き換えるtriggerがあると、従来はinsert後のread-backで初めて不一致になった。この再現を受け、canonical schema外のtrigger/view/table/index/DDLをwrite前に拒否する検査を追加。回帰testで拒否とDB bytes不変を確認した。
- SQLite schema一覧の`name NOT LIKE 'sqlite_%'`は`_`をwildcardとして扱い、`sqliteX_*`オブジェクトを除外していた。`GLOB 'sqlite_*'`へ変更し、Outboxのmutating triggerとConsumerのOutbox/ledger extra-tableをwrite前に拒否するfixtureを追加した。
- 同一processでのconsumer重複試験40回も失敗0。両initializerは制限umask下で新規DBを`0600`に作成。same-version malformed schemaは拒否し、既存DBのbytes不変を確認。
- 2026-10-21の追加監査で、Evaluator consumerが同version DBの列・一部unique keyだけを検査し、追加CHECK制約やcustom indexを受け入れる欠陥を確認。変更前fixture 4件がすべて失敗し、Outbox/ledger双方のcanonical table DDL照合とcustom index拒否を追加。修正後4件PASS、拒否時のDB bytes不変を確認。
- 2026-10-21の追加監査で、version 0 DBにuser viewがあるとinitializerがschema作成をcommitした後で拒否し、DB bytesを変えていた。Outbox/ledger initializerを、transaction前と`BEGIN IMMEDIATE`後にuser schema object全体（table/view/trigger/index）を検査するよう変更。両repositoryで変更前の回帰testはbytes不変assertionに失敗し、修正後は拒否とbytes不変を確認。
- 2026-10-21、SQLite `max_page_count`を各write connectionに適用するtemporary fixtureを追加。実際の`SQLITE_FULL`を観測し、Outboxは失敗行を残さず、ConsumerはACKを保留し、`integrity_check=ok`を確認。ページ上限解除後、同じイベントを1回だけ再処理できた。これはSQLite論理上限試験であり、実ファイルシステムの空き容量枯渇試験ではない。
- 2026-10-21、`#?%`を含むDBパスでOutbox/Consumerのread-only URI読み取りと書込み拒否を検証。実行後の行数不変を確認。
- 2026-10-21、既存backward-compatibility testの`production_runtime`成功表示を削除し、`fixture_probe`のin-memory assignmentとして明示。元fixtureファイルにprovenanceが追加されていないこともassertするよう変更。
- 2026-10-21、旧fixtureと現行`evidence-record.schema.json`の不一致を確定。fixtureに欠けるrequired fieldは`semantic_verdict`のみ。repositoryの既存方針は不正な履歴Evidenceを修復・再ラベルせず隔離保管することのため、旧fixtureを現行schemaへ通す修正は行わない。backward-compatibility testを「現行schemaで拒否される」assertionに変更し、無根拠な互換性成功表示を除去。
- 2026-10-21、DBの全親directory chainについて、symlink・`.`/`..`の曖昧なpath、root/effective-UID以外が所有するdirectory、sticky bitなしのgroup/world-writable directoryを拒否する検査を追加。ユーザー所有symlink・不安全mode・`..`の回帰testは修正前失敗、修正後PASS。root所有のOS symlinkは元path側と解決先双方を検査。
- 2026-10-21、macOS `acl_get_file(ACL_TYPE_EXTENDED)`で全parent directoryとDB inodeのextended ACLをfail-closed検査。ACL付きdirectory/fileを拒否するfixtureを追加し、ACL query後も別processの`BEGIN IMMEDIATE`がBUSYになることを確認。既存DB bytes不変も確認。LinuxではPOSIX ACL xattrを検査する実装とし、Linux上の実行確認は今回未実施。
- 2026-10-21静的検査: Evaluator 14変更ファイル（Python 7、JSON 3を含む）のcompile/parse/trailing whitespace、Evaluator変更Python 7ファイルとHermes変更Python 2ファイルのRuffおよび`ty check`、両worktreeの`git diff --check`がPASS。
- 2026-10-21、Evaluator fixture suite 160 testsでfailures 0、errors 0、skipped 1（標準Pythonに`jsonschema`なし）。Hermes venvの`jsonschema 4.26.0`を使ったbackward-compatibility suiteは5/5 PASSし、旧fixtureが`semantic_verdict`欠落で拒否されることを実行確認。
- third-party validator: Evaluatorの標準`python3`には`jsonschema`なし。既存Hermes venvの`jsonschema 4.26.0`で両SchemaのDraft 2020-12 `check_schema`を実行し、V2 Envelope/ACKの有効fixture受理、未知key・boolean整数定数・無効日付の拒否を確認した。依存追加・network accessなし。
- Legacy test fixture compatibility is resolved as a quarantine-boundary test: current schema requires `semantic_verdict`, the historical fixture lacks it, and the test now asserts rejection. No migration/defaulting is performed; the repository's accepted policy retains invalid historical Evidence outside active scan roots.
- WP2/WP3の追加candidateに対するfresh independent code reviewは未実施。v5 PASSは前段の凍結WP0/WP1 exact-setだけを対象とし、今回の追加ファイル・更新後work-planには適用しない。
- candidate codeではdirectory chainとDB inodeのACLをfixture検証した。ユーザー承認後、canonical runtime root `/Users/yokapro/.hermes/runtime-evidence/agent-level/v2`を作成し、parent chain/rootのowner・mode・ACLを確認した。DBは未作成。ホスト物理volume/remote destinationの容量枯渇は未検証（隔離APFS sparse imageのfilesystem ENOSPCとSQLite `max_page_count`の論理FULLはfixture確認済み）。Gateway接続、実会話も未検証。
- 2026-10-21、Mac上の隔離APFS sparse image（最大256MiB）で容量枯渇を検証。ballast書込みでOS `ENOSPC`を発生させ、Outboxは`outbox_unavailable`で停止し、失敗eventは行に残らず、容量回復後の再試行で1件保存・`integrity_check=ok`を確認。別のAPFS fixtureでは、1 byte書込みも`ENOSPC`となる状態でConsumerが`ledger_write_unavailable`となり、ledger event/receiptは0/0、`integrity_check=ok`。ballast除去後の再試行は`acknowledged`となり、event/receipt各1件、`integrity_check=ok`を確認。終了後の`hdiutil info`で試験volumeの未マウントを確認した。これは隔離APFS volume上の実際のfilesystem `ENOSPC`試験であり、ホスト物理volumeの枯渇・本番配置先・Gateway runtimeは未検証。

### 2026-10-21 R2 adapter provider smoke — user-authorized single operation

- **実行範囲:** ユーザーは後続で「じゃ、続けて」はこの合成metadata 1件のPUTと同一objectのGET read-backを行う許可意図だったと明確化した。対象操作はその1回に限定する。追加リクエスト、既存objectの削除、Gateway設定・起動、実会話送信は行っていない。objectは残置し、削除していない。
- **Keychain:** macOSのGeneric Password item label `R2Key`についてmetadata照会とPassword読取りが成功した。Access Key ID・Secret Access Keyの値は表示・保存・ログ出力していない。この結果は当該実行での読取り成功であり、継続的な可用性を示すものではない。
- **Provider smoke:** Hermes candidateのbudgeted journalとboto3 S3 adapterを通し、`write_once`は`persisted`を返した。後続GETのbyte列は送信payloadと完全一致した。object key: `runtime-evidence/v2/49f6731bb5db520e9f9b3f525e887dd3226feaa9f1f9329a68ef9464e65df369`。objectは残置し、削除していない。
- **Budget記録:** 実行時snapshotはClass A 1回、Class B 1回、payload 325 bytes。これは当該ローカルledgerの記録であり、Cloudflare account全体の利用量・課金上限を制御しない。
- **続行後のローカル検証:** Hermes focused transport suiteは4 files、68 tests passed、0 failed、1 skipped。skipはLinux専用testがmacOSでskipされたもの。対象PythonのRuffは`All checks passed!`、`uv lock --check`はexit 0（255 packages resolved）。
- **判定:** 実credential読取りと1回のadapter-level Provider smokeを観測した。ユーザーは後続で、この1回の合成metadata PUT/GETが「じゃ、続けて」による許可範囲だったと明確化した。この限定操作の許可は、追加通信・削除・受入承認を含まない。Gateway runtime integration、Outbox→remote journal/consumer/report接続、運用上の反復性・独立分母は未確認。これを実会話E2Eや運用実績として扱わない。

### 未完了・次の停止条件

- 2026-10-21の設計続行: host-volume容量枯渇までを対象とする独立remote metadata-only journal方針はユーザー承認済み。Cloudflare R2 bucket `agent-level-runtime-evidence-v2`は単発smokeの試験先として選定し、1回のadapter-level PUT/GETを検証済み。独立分母としてのjournal統合、ACK/read-back契約、remote retentionは未完了。`emitted`は引き続き`null`。
- 2026-10-21、ユーザーは推奨defaultsとpilot範囲の採用を指示した: runtime root `/Users/yokapro/.hermes/runtime-evidence/agent-level/v2`、directory `0700`、DB `0600`、retention 60日、削除責任者はユーザー本人、macOS Keychainでprofile別HMAC key、年次または漏えい疑い/owner変更時rotation、domain separation=`agent-level/runtime-evidence/v2`。対象failure scopeはhost-volume容量枯渇まで。独立remote metadata-only journalを採用する方針、pilot scopeは現`#agent-level`・default profile・手動・最大1件・schedulerなし。当初の記録時点ではprovider選定・外部送信は未実施であり、後続の限定R2 smokeを上記のlatest updateに記録した。Gateway設定変更/再起動の許可は含まれない。
- User recommendation adopted. Runtime root directoryを作成済み。parent chainおよびleafのowner/mode/ACL検証は完了。Outbox/ledgerの手動purge primitiveは実装しfixture DBで検証済み。canonical root上のDBは作成・使用しておらず、live purgeも未実施。HMAC用Keychain custodyと運用purge導線は未実装。R2 S3 credential loader candidateは、後続の単発smokeで`R2Key`の読取りと1回のPUT/GETを確認した。継続的なcredential availability、HMAC key custody、Gateway統合は未確認。
- 2026-10-21、方針記録更新後に再実行: Evaluator全fixture suite `/Users/yokapro/.hermes/hermes-agent/.venv/bin/python -m unittest discover -s tests -p 'test_*.py'` は167 tests PASS、skipなし。Hermes candidateは`HERMES_PYTHON=/Users/yokapro/.hermes/hermes-agent/.venv/bin/python scripts/run_tests.sh tests/gateway/test_runtime_evidence_outbox.py`で23 PASS、fail 0。両worktreeの`git diff --check`とEvaluatorの3文書whitespace検査もPASS。fixture evidenceであり、Gateway runtime/E2E/実会話ではない。
- 2026-10-21、local candidate focused検証: Evaluator suiteは標準Pythonで172 tests PASS・1 skip、Hermes venvで172 PASS・skipなし。Hermes Mac focused transport suiteは68 passed・0 failed・1 Linux-only skip（S3 adapter 16件を含む）。Outbox/ledger purgeは最大900行、60日cutoff、厳密境界保持、receipt先行削除、read-backをfixture DBで検証。macOS Gateway全体suiteは779 files、7,808 passed、11 failed、43 skippedで、直前の7,803-pass runと失敗test ID集合が一致。Ruff checkは変更対象を通過。Evaluator formatterはファイル全体で44 diff hunksを報告し、新規purge/owner-check箇所には差分なし。一括整形は行っていない。このfixture/local suite実行自体ではcanonical DB、Gateway、R2、実会話を検証していない。後続のR2 adapter smokeはユーザーが「じゃ、続けて」の許可意図に含まれる1回の合成metadata PUT/GETとして明確化した。追加R2操作の許可ではない。
- Pilotはcandidate reviewとrunbook完了後に1件のみ。独立reviewer/provider・immutable snapshotとfile setが未決で、外部review dispatchは未承認。Gateway設定変更・再起動およびlive pilotの実行は実施していない。
- WP2全体は未完了。R2試験bucketは単発smokeに限られ、独立分母としてのremote journal統合とconsumer ACK/read-back、Keychain HMAC実装/custody検証、canonical runtime DB pathの実使用、手動purgeの運用導線とremote retention、Gateway finalizer接続が残る。ローカルpurge primitiveのfixture PASSおよびadapter-level smokeは運用受入ではない。
- Gateway finalizerへのV2 Observer hook、runtime配置、既存report/promotionへの接続、Human Calibration、実会話E2Eは未実装・未検証。
- 独立reviewer/providerは未選定。Claude Code CLI 2.1.289の`auth status`はexit 0でsubscription-based accountと報告されたが、plan/quotaは不明。唯一承認済みの起動試行は`/opt/homebrew/bin/claude`不在で接続前に終了し、コード送信なし。再試行・別provider切替はしていない。named reviewer/providerとimmutable snapshot/file setの個別承認前にdispatchしない。
- 2026-10-21のHermes candidate base read-only seam audit: `agent/state_answer_shadow_runtime.py`は明示注入されるState Answer Shadow用collectorで、V2 durable Outboxとは未結線。`run_conversation`ではpreflight compression timeoutと`codex_app_server`経路がObserver開始前にreturnし、通常ループでは`finish_runtime_shadow()`後にcompression-timeoutの`partial/error`をresultへ追加する。さらに`turn_tool_validation._partial_exit()`は`completed=False, partial=True`を返すが`failed`とpersistence receiptを含まない。これを`finish_runtime_shadow()`へ渡す一時fixture probeは`terminal_status=completed, model_call_status=observed, persistence_receipt_status=unobserved`を再現した。既存の`tests/agent/test_state_answer_shadow_runtime.py`は6/6 PASSだが、このpartial-resultケースは対象外。Gateway sourceは変更していない。V2結線前にterminal分類・全return経路・settlement後のresult変換を別途受入テストへ含める。
- このbranch群のfixture PASSと単発R2 adapter smokeは、通常会話の観測・実運用の耐久性・評価可能件数・Level判定を証明しない。KeychainのHMAC custody、canonical DB pathと手動purge運用導線、remote retention、fresh independent review、Gateway runtime integrationが済むまで、運用接続は行わない。

### 2026-10-23 WP2/WP3 Evaluator-side isolated checkpoint

- **Scope:** Evaluator worktree内のsynthetic fixture検証とtest-only変更。Gateway source/config、SessionDB、Gateway API、R2、本番データには接続していない。
- **WP2 local verification:** `test_runtime_evidence_consumer.py`と`test_runtime_evidence_transport_report.py`を個別実行し、両方exit 0。隔離fixture上のconsumer ACK/report計測であり、remote independent denominatorの実装・検証にはならない。`emitted`は`null`のまま。
- **WP3 regression coverage:** `test_level_gate_scripts.py`へ、Legacy形式の合成pathがPromotion scan root外であること、異なる`agent_configuration_id`を混ぜて集計しないことを追加。Legacy testには、同じ有効recordをscan対象へ強制投入すると受理されるnegative controlを含めた。`test_evidence_report.py`にはCLI検証を追加し、既定ではShadowを除外し、`--environment-class shadow`指定時だけ閲覧できることを確認。
- **WP3 isolated report integration:** `scripts/evidence_report.py`に任意の`runtime_transport` subreportを接続。CLIで`--runtime-outbox-db`、`--runtime-ledger-db`、`--runtime-sink-id`、`--runtime-max-records`を全て指定した場合だけ動き、1つでも欠ければ拒否する。未指定時の既存report動作は維持し、既定path・環境変数fallback・runtime root自動読取りはない。Transport値はnested namespaceに分離し、`records`・Evidence gate統計・Promotion入力へ混ぜない。read-only DBで集計する。`report_schema_version=2`の`outcome_counts`はaccepted、reason別rejected、境界別conflictをcount-onlyで示し、durable観測のないduplicateは`null`＋reason codeとする。
- **Verification:** focused suitesはtransport report **22/22**、Evidence report **3/3**、Promotion boundary **7/7**。Evaluator全体はHermes venvで**224 tests PASS**（failures=0、errors=0、skipped=0）。実CLIをrepository外のtemporary working directoryから実行し、category counts・transport count表示・path/event_ref非出力を確認。Ruff、対象Pythonの`py_compile`、`git diff --check`もPASS。fixture DBの前後hash一致を確認。
- **テスト修正履歴:** 新CLI接続前のtest-first実行は未実装interfaceを検出。その後、synthetic JSONL fixtureの改行escapingを修正し、focused suitesと全体suiteを再実行してPASS。未解消のtest failureはない。
- **Status:** WP2全体は未完了。remote independent denominator/ACK integration、HMAC Keychain custody、canonical DB運用、retention、Gateway finalizer hookが残る。WP3 evaluator-side fixture slice（explicit read-only subreport、category counts、Legacy/Shadow/configuration境界）は検証済み。WP3のruntime adapter接続と実source受入は未実施・未確認であり、実接続禁止の境界を維持している。count-onlyの受入判断は解決済み。Gateway/SessionDB/API/R2/本番データへの接続、Gateway変更・起動、commit/pushはしていない。

### 2026-10-23 WP6 hermetic transport matrix (Claude Code)

- **Scope:** WP6のうちGateway runnerを必要としないtransport経路のみ。Hermes candidate worktreeの`gateway/runtime_evidence_outbox.py`をread-onlyでloadし（`HERMES_HOME`はfresh TemporaryDirectory、bytecode書込み無効）、`DurableRuntimeEvidenceOutbox.enqueue` → `RuntimeEvidenceConsumer` → ledger → ACK receipt → `build_runtime_evidence_transport_report`を同一TemporaryDirectory上で連結した。Hermes worktreeは変更していない。worktree不在時はsuite全体がskipする（`WP6_HERMES_WORKTREE=/nonexistent`で11 skip確認）。
- **追加:** `tests/test_wp6_hermetic_transport_e2e.py`（11 tests、test-only）。製品コード変更なし、製品bugの検出なし。

| WP6必須ケース | 判定 | 根拠 |
|---|---|---|
| completed turn | transport部分をcovered／runner経由はblocked（WP4） | WP6 `test_completed_turn_flows_outbox_to_ack_and_exact_report_readback` |
| failed turn | blocked（WP4・Gateway runner必要） | — |
| interrupted turn | blocked（WP4・Gateway runner必要） | — |
| persistence未確認 | covered（E2E追加） | WP6 `test_persistence_unconfirmed_is_transported_but_structurally_excluded`、contract `test_unconfirmed_persistence_is_captured_as_excluded` |
| malformed schema / nested forbidden key | covered（E2E追加） | WP6 `test_malformed_and_nested_forbidden_keys_are_rejected_before_outbox`、contract `test_rejects_unknown_nested_and_raw_content_keys_without_echoing_values`、Hermes `test_rejected_event_is_not_written` |
| outbox unavailable / lock / full相当 | covered（unavailableはE2E追加、lock/FULLは既存） | WP6 `test_outbox_unavailable_fails_closed_and_recovers_after_bootstrap`、Hermes `test_separate_processes_contend_on_sqlite_and_preserve_one_event_ref`・`test_sqlite_page_limit_fails_closed_then_enqueue_recovers` |
| consumer unavailable | covered（E2E追加） | WP6 `test_consumer_unavailable_withholds_ack_then_retry_acknowledges`、consumer `test_consumer_requires_explicit_ledger_bootstrap_and_does_not_create_it` |
| commit後ACK前の失敗とidempotent retry | covered（E2E追加） | WP6 `test_failure_after_ledger_commit_before_ack_retries_idempotently`、consumer `test_process_exit_after_ledger_commit_before_ack_recovers`、Hermes `test_process_exit_after_outbox_commit_recovers_as_duplicate` |
| duplicate event | covered（E2E追加） | WP6 `test_duplicate_event_is_idempotent_across_both_boundaries` |
| same event_ref / different payload conflict | covered（E2E追加） | WP6 `test_same_event_ref_different_payload_is_conflict_and_never_overwrites`、consumer/Hermes/report各conflict test |
| report read-back missing / stale | covered（E2E追加） | WP6 `test_report_does_not_count_ack_when_receipt_is_missing`・`test_report_does_not_count_ack_when_ledger_row_is_stale`、report `test_bad_receipt_is_not_counted_as_consumer_ack` |
| Legacy record | covered（E2E追加） | WP6 `test_legacy_v1_gateway_record_never_enters_outbox_or_report`、`test_level_gate_scripts.py` `test_runtime_legacy_directory_is_outside_promotion_scan_roots` |
| response content/deliveryがcapture障害で不変 | blocked（WP4・Gateway runner必要） | — |
| performance measurement | 未実施（runner前提） | — |

- **全E2Eケース共通assert:** `emitted=null`（reason `independent_capture_denominator_not_implemented`）、`evaluation_eligible=null`、`duplicate=null`、`promotion_input=false`、`legacy_evidence_included=false`。
- **検証結果:** 新規file 11/11 PASS（Hermes venv Python 3.11、標準`python3`とも）。Evaluator全体はHermes venvで**235 tests PASS**（failures=0、errors=0、skipped=0）、標準`python3`で**235 tests、OK、skipped=1**（`jsonschema`なし）。新規fileのRuff `All checks passed!`、`py_compile` PASS、`git diff --check` PASS。
- **副作用の記録:** 初回の標準`python3`（3.14）実行で、Hermes worktreeのgit-ignored `gateway/__pycache__/runtime_evidence_outbox.cpython-314.pyc`が生成された。tracked/untracked sourceへの変更はない。その後loaderで`sys.dont_write_bytecode`を有効化した。生成済みpycは削除していない。
- **判定:** これはfixture-only・hermetic transport検証であり、Gateway runtime、実会話、SessionDB、Gateway API、R2、本番データには接続していない。**WP6全体は未完了。** completed/failed/interrupted turnのrunner経由実行、capture障害下での応答本文・delivery不変、performance measurementはWP4（Gateway source変更、別途承認必須）に依存してblocked。commit/pushはしていない。

### 2026-10-23 WP4 Observer + WP6 runner cases (Claude Code)

- **承認:** ユーザーの「承認するからすすめて」を受け、Hermes隔離worktree（`/Users/yokapro/Developer/hermes-worktrees/runtime-evidence-wp2`、branch `feat/runtime-evidence-outbox`）内のGateway source変更に限定して実施。live Gatewayの起動・再起動、`~/.hermes`の設定・runtime file・state.db/SessionDB、R2、Keychain、network、本番データには接続していない。commit/pushなし。live操作（Keychain HMAC key、`config.yaml`有効化、canonical Outbox DB初期化、Gateway再起動、Shadow Pilot）は実行直前に影響とrollbackを提示して個別確認する。
- **WP4設計:** 新規`gateway/runtime_evidence_observer.py`。`_run_agent_inner`で`run_sync`返却後（finalizerのpersistence結果確定後）・delivery前に1回だけsettleし、completed/failed/interrupted/skippedを判定。例外はfailed、CancelledErrorはinterruptedとしてsettleし再送出する。失敗marker（partial、compression_exhausted、error、failed）は`completed`より優先。`persistence_confirmed`欠落は`unknown`、`False`は`unconfirmed`（excluded）。応答threadは判定と件数コピーのみで、HMAC・key取得・JSON化・Outbox書込みは専用worker threadが行う。queue満杯はdrop＋count、Outbox失敗はerror codeのcountのみで応答・delivery・persistenceを変えない。設定`RuntimeEvidenceConfig`は既定OFF、`config_version=1`・`enabled is True`・明示`outbox_path`・非空allowlist（platform/chat/profile）・`max_events` 1–1000・key provider注入が全て揃った場合だけ構築。Keychain custody未実装のため、実環境で設定をONにしても現状は構築されない。`EvaluatorShadowAdapter`は変更せず並存（既定OFF）、新経路はEvaluator subprocessを起動しない。
- **変更ファイル（Hermes worktree）:** 新規`gateway/runtime_evidence_observer.py`、`tests/gateway/test_runtime_evidence_observer.py`、`tests/gateway/test_runtime_evidence_wp6_runner_e2e.py`。変更`gateway/config.py`、`gateway/run.py`、`gateway/run_turn.py`、`gateway/run_turn_runner.py`（WP4分 +97/−2）。
- **WP4検証:** 新規observer suite **48 passed／0 failed**（fake agentで実`_run_agent`→`run_sync`→observerを通すケースを含む）。settle呼出しを外すmutationでseam test 4件FAILを確認後に復元。関連suite（Outbox、R2、State Answer Shadow、config、Evaluator Shadow関連）12 files **272 passed／0 failed／1 skipped**。gateway＋agent全体 **14,278 passed／12 failed／66 skipped**（1,284 files）。12 failedは編集4ファイルをHEADへ戻した再実行でも件数が同一（12 failed＋単独なら通る1件）で、既存失敗と判断したが**test ID集合の突合は未実施**。以前の「11 failed」はgatewayのみの範囲で直接比較できない。Ruff、`py_compile`、`git diff --check` PASS。
- **WP4 latency（fixture-only）:** caller側settleコスト OFF p50 0.1µs、ON p50 1.4–1.5µs、ON p99 7.5–8.0µs（3回×200 turn）。
- **WP6 runner cases:** `tests/gateway/test_runtime_evidence_wp6_runner_e2e.py`。conftestでHERMES_HOME隔離済み、全DBはpytest temp dir。fake agent/modelで実`_run_agent`→`run_sync`→observer→`DurableRuntimeEvidenceOutbox`を通し、Evaluator worktreeの`runtime_evidence_contract`/`consumer`/`transport_report`を`sys.dont_write_bytecode=True`で読み込み（`scripts` packageは読込中だけ差し替えて復元、worktree不在時はskip）、ledger→ACK→report read-backまで接続。
  - completed／failed（unconfirmed）／interrupted／persistence-unconfirmed completed：各1 envelope、Evaluator `validate_event`がGateway生成envelopeを受理、ACK `exact_match`、report `outbox_persisted=ledger_persisted=consumer_acknowledged=outbox_to_ledger_exact=report_visible=1`、transport_only/excludedの区分が期待どおり。Outbox/ledger DB bytesに本文fixture文字列なし。
  - exact committed-row read-back：ledger bytesがOutbox bytesと一致。ledger行を改変するとreportは`consumer_acknowledged=0`、`outbox_to_ledger_exact=0`。
  - ledger commit後・ACK前の失敗：`ledger_readback_mismatch`後の再試行で`duplicate` disposition、event/receipt各1行、ACK 1。
  - capture障害下の応答：Outbox未bootstrap、Outbox full（`OutboxError`注入）、Outbox writer lock保持中、consumer unavailable（ledger未bootstrap→後でACK）のいずれも、runnerの返却responseがobserver OFF baselineと同一（`session_id`除く）。
  - 全ケースで`emitted=null`（`independent_capture_denominator_not_implemented`）、`evaluation_eligible=null`、`promotion_input=false`。
  - **結果:** 新規 **8/8 PASS**。WP6 runner＋WP4 observer＋Outbox suite 3 files **84 passed／0 failed／1 skipped**。Ruff・`git diff --check` PASS。Evaluator全体はHermes venvで**235 tests PASS**（変化なし）。
  - **runner turn latency（fixture-only、fake model、100 turn×3回）:** OFF p50 1.144–1.152ms／ON p50 1.108–1.110ms、OFF p99 1.372–1.401ms／ON p99 1.481–1.521ms。本番値ではない。
- **未カバー経路・限界:** skippedを出す実Gateway呼出し箇所は未接続（判定とOutbox書込みのみ確認）。`_run_agent_via_proxy`未接続。`run_sync`冒頭のprovider認証失敗の早期returnは完了flagがなく`unknown`。`delivery_status`はsettleがdelivery前のため常に`unknown`。実際の割込みは結果shapeでのみ確認。`confirmed`はfinalizer自己申告のHMAC参照でありcanonical writerの検証可能receiptではない。`runtime_build_id`、`tool_error_count`、`correction_count`、`evidence_reference_count`は常に`null`。WP6の「応答不変」はrunner返却responseの比較であり、platform adapterのsend（実delivery）とSessionDBへの実persistenceは通していない（fake agentが`persistence_confirmed`を返す）。outbox fullは例外注入でありOutbox接続上の実`SQLITE_FULL`ではない（Outbox単体では既存fixtureで確認済み）。
- **判定:** すべてfixture-only。**WP4・WP6はruntime受入未了。** 実会話観測、運用耐久性、評価可能件数、Level判断を証明しない。

### 2026-10-23 WP4 gap closure — skipped / proxy / config.yaml bridge (Claude Code)

- **承認:** ユーザー「1-3の順で進めて」の手順1（隔離worktree内のWP4穴埋め）。Hermes worktree `feat/runtime-evidence-outbox` のみ変更。live Gateway、`~/.hermes`、SessionDB、Keychain、R2、networkには接続していない。commit/pushなし。
- **skipped:** `_handle_message`で会話turnを開始しない5つのgate（estop停止通知、Telegram topic root lobby、external drain拒否、`max_concurrent_sessions`拒否、turn-lease timeout拒否）に`_hm_record_skipped_turn`を追加。scope内なら`terminal_status=skipped`／`persistence_status=not_applicable`／`excluded`を1件settleし、返信は変更しない。commandやapproval intercept、busy-session queueは「turnを開始しないメッセージ」ではないため記録対象外。admission前（未認可等）はsourceが確定しないため対象外。
- **proxy:** `_run_agent_inner`のproxy分岐を、local経路と同じbegin→1回settle→例外時failed＋再送出で包んだ。proxyのerror／stale-generation結果は`completed`キーを持たないため`unknown`としてsettleする（failedへ推測で寄せない）。`persistence_confirmed`はremote側の自己申告で、canonical receiptではない。
- **config.yaml bridge（新規発見の欠陥）:** `config_loader._TOPLEVEL_BRIDGE`に`runtime_evidence`が無く、`config.yaml`の`runtime_evidence`（top-level・`gateway.`配下とも）が`GatewayConfig`へ届かず黙って無視されていた。bridge行を追加。回帰test 2件は修正前FAIL、修正後PASS。
- **テスト:** observer suite 48→61件（proxy 4、skipped gate 6、config bridge 3）。mutation確認: skipped記録／proxy settleを外すと6件FAIL、bridgeを外すと2件FAIL。runtime-evidence関連6 files **137 passed／0 failed／1 skipped**。config関連34 files **660 passed／0 failed**。Ruff・`git diff --check` PASS。Evaluator全体 **235 tests PASS**。
- **既存12件失敗の照合:** 一時`git worktree`（HEAD `f09ccc3`、変更なし）で失敗7 fileを実行し **12 failed**。変更後treeのgateway+agent全体（1,285 files、**14,299 passed／12 failed／66 skipped**）の失敗test ID集合と **完全一致**（`test_skip_background_review`1、`test_buzz_adapter`1、`test_scale_to_zero`2、`test_systemd_notify`1、`test_silent_partial_delivery_95382`1、`test_stale_finalize_suppression`2、`test_run_progress_topics`4）。今回の変更に起因する失敗はない。一時worktreeは`git worktree remove`済み。
- **残り:** `delivery_status`は常に`unknown`、`confirmed`は自己申告、`runtime_build_id`等はnull、HMAC key providerは未実装（`runtime_evidence_key_provider=None`のため設定をONにしてもobserverは構築されない）。WP4/WP6はいずれもfixture検証のみで運用受入ではない。

### 2026-10-23 WP2 HMAC key custody provider (Claude Code)

- **Keychain naming contract（固定）:** macOS Generic Password、service `agent-level/runtime-evidence/v2`、account `hmac:<profile>:v<version>`（pilotは`hmac:default:v1`）、値は小文字hex 64文字（32 bytes）。読取りは`/usr/bin/security find-generic-password -s … -a … -w`をshellなし・timeout 10秒で実行し、key値をargv・環境変数・file・log・例外文へ出さない。失敗は値を含まないcodeのみ（`keychain_item_unavailable`／`keychain_key_malformed`／`keychain_key_too_short`／`keychain_timeout`／`keychain_platform_unsupported`等）。
- **実装（Hermes隔離worktreeのみ）:** 新規`gateway/runtime_evidence_keychain.py`（lazy・cached `KeychainHmacKeyProvider`、失敗はfail-closedでcacheし毎turn再読しない）。`RuntimeEvidenceConfig`に`hmac_key_source`（`keychain`のみ受理）と`hmac_key_version`（既定1）を追加。`GatewayRunner._init_runtime_evidence_observer`は、設定がenabledかつ`hmac_key_source: keychain`かつprofileが1件のときだけproviderを構築する。構築時・起動時にはKeychainへアクセスせず、初回読取りはobserverのbackground workerで行う。読取り失敗は`envelope_build_failed`と`key_<code>`で計数し、Outbox書込みなし・応答不変。
- **テスト:** 新規`tests/gateway/test_runtime_evidence_keychain.py` **21 passed／0 failed**（`security`は全てfake runner/patch、実Keychain未使用）。runtime-evidence 8 files＋State Answer Shadow＋gateway/hermes_cli config系の計39 files **576 passed／0 failed／5 skipped**。Ruff・`git diff --check` PASS。Evaluator全体 **235 tests PASS**。
- **未実行（Claude Codeは実行していない）:** canonical Keychain itemの作成、canonical Outbox DB（`/Users/yokapro/.hermes/runtime-evidence/agent-level/v2/outbox.db`）の初期化、`~/.hermes/config.yaml`への`runtime_evidence`追加は、Claude Codeのauto mode安全判定で拒否されたため実施していない。ユーザー本人へ手順を引き渡した。Gateway再起動・Shadow Pilotも未実施。fixture検証のみで運用受入ではない。

### 2026-10-23 Parent-directory ACL policy fix (Claude Code)

- **欠陥:** Outbox（Hermes `gateway/runtime_evidence_outbox.py`）とledger（Evaluator `scripts/runtime_evidence_consumer.py`）の`_validate_parent_chain`は、親directoryに拡張ACLが1件でもあれば拒否していた。macOSは全ホームdirectoryに既定ACL `group:everyone deny delete`を付与するため、canonical path `/Users/yokapro/.hermes/runtime-evidence/agent-level/v2/outbox.db`の初期化が`outbox_permissions_invalid`で失敗した（ユーザー承認済みの初期化を実行した時点で発覚、DBは未作成）。fixture testはACLのないtemp dirで動いていたため検出できなかった。
- **方針変更（ユーザー承認済み）:** 親directoryは、libSystemの`acl_get_entry`／`acl_get_tag_type`で全entryを走査し、全entryが`ACL_EXTENDED_DENY`なら許可する。allow・未知tag・ACL APIの失敗はfail closedで拒否する。deny専用entryは権限を与えないため安全性は下げない。DB inode自体は従来どおり、ACLが1件でもあれば拒否する（厳格のまま）。Linuxの挙動は変更なし。両repositoryに同一の`_has_non_deny_acl`を実装した。
- **テスト（両repository、実ACLをtemp dirへ`chmod +a`で付与、後始末で`chmod -N`）:** deny専用の親directory → 初期化成功（`0600`）、deny＋allow混在 → 拒否・DB未作成、DB fileにdeny専用ACL → 拒否・bytes不変、`acl_get_tag_type`失敗の注入 → 拒否、canonical runtime rootに対する`_validate_parent_chain`の読取り専用probe → 受理（書込みなし）。既存の「allow ACLの親directory → 拒否」「DB fileのACL → 拒否」テストも維持してPASS。修正前の`_has_extended_acl`はdeny専用directoryと`/Users/yokapro`の両方で`True`（拒否）、修正後の`_has_non_deny_acl`は`False`（許可）、混在では`True`となることをprobeで確認した。
- **結果:** Hermes `test_runtime_evidence_outbox.py` **33 passed／0 failed／1 skipped**（skipは既存のLinux専用test）。Hermes runtime-evidence 7 files **163 passed／0 failed／1 skipped**。Evaluator `test_runtime_evidence_consumer.py` 45 tests OK、Evaluator全体 **240 tests PASS**（failures 0、errors 0、skipped 0）。Ruff、`py_compile`、`git diff --check`、変更4ファイルのtrailing whitespace確認はPASS。
- **live状態（このfixの時点）:** ユーザーの許可を得て、canonical Keychain item（service `agent-level/runtime-evidence/v2`、account `hmac:default:v1`）を作成済み。`~/.hermes/config.yaml`はbackup（`config.yaml.bak-20261023-runtime-evidence`）を取ったうえで`runtime_evidence`ブロックを`enabled: false`で追加済み。canonical Outbox DBの初期化は本fixの後に再実行が必要で、まだ作成されていない。Gateway再起動・Shadow Pilotは未実施。fixture検証のみで運用受入ではない。

### 2026-10-23 Step 3a — live統合候補の隔離作成 (Claude Code)

- **live状態の更新:** ユーザー承認後に再実行し、canonical Outbox DB `/Users/yokapro/.hermes/runtime-evidence/agent-level/v2/outbox.db` を初期化済み。mode `0600`・ACLなし・`integrity_check=ok`・table `outbox_events`／`outbox_conflicts`・`outbox_events` 0件。`config.yaml`の`runtime_evidence`は`enabled: false`のまま。Gatewayは未再起動で、live checkout（`/Users/yokapro/.hermes/hermes-agent`）のworking treeは変更していない（`git status` 18件のまま）。
- **統合候補:** `/Users/yokapro/Developer/hermes-worktrees/runtime-evidence-integration`（detached `f09ccc3aa7`）。live checkoutの変更済みtracked 12 fileと、importされる未追跡test 2 fileをコピーし、byte一致を確認。未追跡の`hermes_state_lifecycle/`、`nine-star-ki-ability/`、`bun.lock`、research mdはimportされていないため対象外。
- **Observer変更の適用（R2 module・`pyproject.toml`・`uv.lock`は除外）:** liveでは未変更の`config_loader.py`／`run_inbound.py`／`run_turn_runner.py`はObserver版をそのまま採用。`runtime_evidence_outbox.py`／`_observer.py`／`_keychain.py`と、それぞれのtest＋WP6 runner E2Eを追加。`config.py`／`run.py`／`run_turn.py`は`git merge-file`で3-way merge（base `f09ccc3`、ours=live、theirs=Observer）を行い、**conflictは0件**。Observer経路にR2／boto3のimportはない。
- **検証（live venv）:** runtime-evidence＋evaluator_shadow＋provider-hook 7 files **155 passed／0 failed／1 skipped**。config系61 files **764 passed／0 failed／11 skipped**。gateway＋agent全体1,285 files **14,306 passed／12 failed／66 skipped**。12件のfailureは、live状態だけを再現した一時コピー（Observerなし）で同じ7 fileを実行しても**同一のtest ID集合**で失敗した（269 passed／12 failed）。今回の統合によって増えた失敗はない。Ruff・`git diff --check`・trailing whitespace確認もPASS。一時コピーは`git worktree remove`で削除済み。
- **3b用の成果物（未実行）:** `.integration-manifest.txt`に13 file（変更6、新規7）のintegrated sha256と3a時点のlive sha256を記録。`.integration-3b-commands.sh`は次の手順をまとめた草案。①sha256の事前照合（liveが3a以降に変わっていたら中止）、②`~/.hermes/backups/runtime-evidence-3b-<ts>.tar`へのbackup、③copy、④`py_compile`、⑤`launchctl kickstart -k gui/$(id -u)/ai.hermes.gateway`、⑥health check。rollback手順は、tarを展開して戻し、新規fileは`mv`で退避（rmは使わない）し、再度kickstartする。**3bはユーザー承認前のため実行していない。**
- **未解決:** 3bの後もObserverは`enabled: false`のため捕捉しない。有効化（`enabled: true`＋再起動）とShadow Pilot 1件は、それぞれ別に確認してから実行する。delivery_status=unknown、persistence confirmed=自己申告などのWP4の既知制約は変わっていない。

### 2026-10-23 Step 3b/3c — live反映とbounded Shadow pilot 1件（Claude Code）

- **3b（live反映）:** ユーザーが`.integration-3b-commands.sh`を自身で実行（Claude Codeのauto modeは本番デプロイとして拒否）。backup `~/.hermes/backups/runtime-evidence-3b-20261023-121935.tar`。12:19:35にSIGTERM後、旧プロセス（PID 62994）の終了処理中はlaunchd再起動が「already running」で失敗し、旧プロセス終了後の12:21:02に新Gateway（PID 33957）が起動、12:21:10 Discord接続。別チャンネルで進行中だったHermesターン1件が中断された可能性がある。`enabled: false`のためOutbox 0件を確認。
- **3c準備:** ユーザー承認のもと`config.yaml`を`enabled: true`へ変更（Claude Code）。ledger DB `~/.hermes/runtime-evidence/agent-level/v2/ledger.db`の初期化とGateway再起動はユーザーが実行。12:23:31 Discord再接続。
- **Pilot 1件:** ユーザーが`#agent-level`へ1通送信（12:25:17受信、12:26:53応答送信）。Outbox `outbox_events=1`、`outbox_conflicts=0`。Envelopeはmetadataのみで、各refはHMAC化、送信本文は含まれないことを確認。主な値: `terminal_status=completed`、`persistence_status=confirmed`（finalizer自己申告のHMAC ref、canonical receiptではない）、`delivery_status=unknown`、`execution_mode=shadow`、`evaluation_eligibility=transport_only`、`measurement_status=partial`。
- **Consumer/ACK:** sink_id `agent-level-v2-ledger`で`consume_outbox_event(seq=1)` → `status=acknowledged`、`disposition=persisted`、`readback_status=exact_match`。
- **Transport report（read-only）:** `outbox_persisted=1`、`outbox_validated=1`、`ledger_persisted=1`、`outbox_to_ledger_exact=1`、`consumer_acknowledged=1`、`report_visible=1`、`structurally_transport_only=1`、anomaly全0、conflict 0。`emitted`／`evaluation_eligible`／`measurement_complete`／`duplicate`はnull＋理由コード。`promotion_input=false`、`semantic_capability_assessed=false`、`report_status=partial`。
- **停止:** pilot後に`config.yaml`を`enabled: false`へ戻した（`max_events: 1`でもあり追加捕捉なし）。反映には再起動が必要。
- **判定:** 実Gateway→Outbox→ledger→ACK→reportのread-backを1件で観測した。これはtransport経路の単発実証であり、運用の耐久性・独立分母・評価可能件数・能力評価・Level判定・Promotionを示さない。Human Calibration（WP7後半）、remote journal／独立分母、delivery_status、canonical persistence receipt、retention運用は未完了。
