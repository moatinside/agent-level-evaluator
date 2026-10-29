# Agent Level Evaluator — 実会話レビューv2の実稼働作業計画（作業計画の正本）

- 更新: 2026-10-28 JST
- 対象: `moatinside/agent-level-evaluator` のローカル `anthropic-insights-impl` worktree。HEAD `c8300ca168e00e465d717076f7e6653ed4043608`（detached）。`origin/main` は確認時点で同じHEAD。**本書とv2実装は未コミットで、リモートmainには存在しない**。
- 権限: 本書は作業順と受入条件を定める。Cron変更、外部評価の追加実行、Gateway/Production接続、commit/pushをこの文書だけで許可しない。
- 判定: **実会話レビューの定期実行は未稼働**。10/26の手動1件は保存済み、10/27・10/28の定期評価は失敗。次回予定は10/29 09:00 JST、ジョブは現在有効（10/28の設定読戻し）。

## 1. 文書の役割と統一した正本

このファイルが、保存済みHermes会話をClaude Codeで評価し、人が根拠を確認できるレポートを定期配信するための**唯一の実行順・未完了事項・受入条件の正本**である。更新時はここを先に直す。下記の文書を並行する実稼働計画として読まない。

- `docs/anthropic-insights-implementation-plan.md`: A〜Cのv2機能開発・10/26接続の設計と実行履歴。過去時点の「次回10/27」「Aから始める」は本書の次アクションを上書きしない。
- `docs/gateway-real-conversation-evaluation-work-plan.md`: metadata-only Gateway/Outbox/Shadow WP0〜WP7の別トラック。今回のレポートCron復旧の依存工程ではない。実行再開・運用接続は別途判断する。
- `docs/current-evaluation-architecture.md`: 評価経路とSSOTの案内。`docs/decision-log.md`: 採用判断の履歴。`AGENTS.md`: 実行者向けガードレール。状態と次の作業順は本書を参照する。
- 外部Cron設定・共有試行台帳・実レポート・Discordの投稿は**実状態の一次記録**。計画の記述より実行結果を優先し、差分があれば本書に反映する。計画は実稼働の証明にならない。

対象worktree以外（`usable-first-plan` worktree、Evaluator runtime、Hermes Gateway、`origin/main`）のファイルは今回変更しない。Git反映は実際の評価結果を見てから行うというユーザー判断を維持する。`AGENTS.md`への正本リンク追記は保護ファイルへの承認がタイムアウトしたため未反映。許可が得られるまでは同ファイルを編集しない。

## 2. 利用者へ渡す成果と成功の定義

許可された `AIBusinessDevelopment / #mobile（フランチャイズ）` の終了済み実会話を評価し、6軸の判定、発言位置に戻れる根拠抜粋、問いの軌跡、観測できない箇所を日本語レポートでこの `#agent-level` に届ける。ユーザーが過去の会話を思い出さずに「この軸は合う／違う」と校正できることを第一の成果とする。

**最初の運用受入:** (a) 許可候補の選定、(b) Claude Codeの評価完了、(c) `conversation-review-output/<evaluation_ref>/evaluation.json` と `report.md` の保存・読戻し、(d) 同じ評価参照のDiscordへの実投稿、(e) 発言位置・抜粋の照合と人が読める内容、を**同一の実行について**確認する。Cron exit 0、dry-run、Shadow Guard PASS、投稿だけ、保存だけはこの受入条件を満たさない。候補なしは正常な無通知状態だが、E2Eの検証には算入しない。

**継続運用受入:** 後続の適格な定期実行でも、試行・保存・配信の状態が別々に追え、失敗時は安全な分類と復旧手順が機能すること。実会話の人手校正と誤判定の扱いを確認する。十分な適格会話がない場合は未検証のまま残し、対象・上限を拡大しない。

## 3. 現在の観測と未確認

- Cron `35b6e4cf551e` は現在有効で、`once at 2026-10-29 09:00`・`repeat=1/1`。`no_agent=true`、`~/.hermes/scripts/agent-level-auto-evaluation.py`、本worktreeのworkdir、Discord配信先 `1547520274029608990` はread-backで確認済み。2026-10-28 13:02 JSTに識別情報の取扱い確認待ちで一時停止し、その後ユーザーが10/29の一回に限り現行の識別情報を含み得るprovider入力・保存・Discord配信を明示許可したため再開した。10/29の1回を超える実行は予約されていない。
- 共有試行台帳 `~/.hermes/agent-level-evaluator-automation/state.sqlite3` のread-only確認では、10/26は`succeeded`かつレポート名あり、10/27・10/28は`failed`かつレポート名なし。失敗で各日1回の枠を消費。失敗がClaude起動・応答検証・保存のどこで発生したかは未確認。
- 10/26の保存レポート `conversation-review-output/ec303c5c7254/` は実会話1件のv2出力。6軸のうち`not_observable`が4、`partial`が2。初期の問いは未観測、問いの更新は0、人手校正はpending。実行できた事実と、評価が有用だという判断は分ける。
- 2026-10-28 10:59 JSTのP0確認: Cron設定は有効・毎日09:00 JST・`no_agent=true`・`agent-level-auto-evaluation.py`・本worktree・このDiscordチャンネル配信で、次回は10/29 09:00 JST。共有台帳は10/27・10/28とも`failed`・レポートなし。現行台帳には`jst_day / attempted_at / session_ref / status / report_name`だけがあり、当時の失敗段階は保存されていないため後から特定できない。
- Cron実行DBのread-only照合でも10/27・10/28の実行は`failed`、incidentは`failure_type=script`。保存出力は両日とも汎用失敗通知、実行エラーは`Script exited with code 1`とstdoutのみで、stderr・traceback・失敗段階は記録されていない。10/26の実行は`completed`。この一次記録でも根本原因は未特定。
- 実行経路: Cron `35b6e4cf551e` → `~/.hermes/scripts/agent-level-auto-evaluation.py`（cycle stdoutを捕捉）→ `run_conversation_review_cycle.run_cycle`（台帳schema/日次上限/候補選定/試行予約）→ `evaluate_session`（会話DB read-only→redaction/prompt→`claude -p`→JSON抽出/6軸と根拠位置の検証→`evaluation.json`/`report.md`書込・読戻し）→台帳記録→wrapperが一致するレポートを読戻し→stdout→Cron Discord配信。失敗はこの段階ごとに分け、Cron配信失敗は評価失敗と別状態にする。
- 旧cycleは`error_type`のみをJSONへ出し、wrapperが汎用文へ変換していた。今回のローカル未コミット修正では、失敗段階・コードをallowlistで制限して通知・台帳へ渡し、既存台帳に2列を追加する移行処理を実装した。**実台帳へのschema移行は未実施**で、次の予定実行時に初めて適用される。10/27・10/28の原因を遡って復元するものではない。
- P1の失敗診断は実providerを呼ばない一時DB・一時出力・fake CLIで確認済み。5モジュール指定suiteは、直前batchで58件、前回修正後63件、追加review指摘への回帰修正後66件PASS（Python 3.11.15）。最新コマンドは`python3.11 -m unittest tests.test_evaluate_session_with_claude tests.test_auto_evaluate_recent_session tests.test_conversation_review tests.test_review_cycle tests.test_cron_wrapper`。`py_compile`、`git diff --check`もPASS。これらはローカルfixtureであり、実会話・Claude・Discord配信の証拠ではない。
- 2026-10-28のv3読み取り専用レビューはmanifest SHA-256 `ceb531aa8090f1ba7960bbfea2238a802fe4c96fb5160a3543ec950ca565a1c9`、11/11ファイルのhash一致を確認して`FINDINGS`。実装と同じモデル系列による静的レビューで、P1として氏名・組織名が評価入力・証拠抜粋に残る条件付き経路、P2として状態読取り失敗時の枠状態誤表示とsession_ref symlink経由のroot外書込みを指摘。前回v2レビューはwrapperのevaluation.json containment/reference/report bindingとcycleの`status == "OK"`未必須も指摘。v2の45/44件記載差は現行本書で解消済み。
- 2026-10-28の先行レビュー後の当時の状態: 後続レビューでは候補と評価参照・成果物パスのbinding、wrapper回帰テスト対象のhash pin、dry-run CLI例外表示の3点を追加指摘。限定修正前は該当テストが失敗し、修正後の関連11テストはPASS。氏名・組織名の取り扱いはこの時点では未承認で、後続の最終修正・明示許可・最新レビュー結果は次項以降を参照。
- 2026-10-28の先行P2修正snapshotレビューはmanifest SHA-256 `cd25989cbdcc7bd891311bc161928d7a9ef4aaed78bbcd8f7e0acf476d71f48c`、12/12ファイル一致・全文確認で`FINDINGS`。同一モデル系列の別プロセスによる静的レビューでP1識別子残存経路とP2を指摘。レビュー自体はテスト・Cron・providerを実行していない。
- 2026-10-28の最終post-fix review snapshot（manifest SHA-256 `90bb4d3237501f98bb1908c287cf78996b2caab93527cf21752735148202c03c`）では12/12ファイルを確認し、識別情報、未知role、success/dedupe原子性などの指摘を受けた。後続修正で未知role本文/role名を除外し、評価ledgerと成功attempt状態を1 transactionに統合、CLI parse errorを固定文にする回帰修正を行い、指定5モジュールsuite 66件で検証済み。
- 最新post-fix review snapshot（`/Users/yokapro/.hermes/cache/agent-level-p2-final2-review-qjmkv8wj`、manifest SHA-256 `1c046151f7efabb51bf6c7b04814a4ceb6a128145606c70bd44c2be5fc8e4671`）は12/12ファイルを全文確認し、`FINDINGS`、今回の一回実行を止める指摘0件。残余所見は、同時ローカルpath変更時の条件付きTOCTOU、異常CLI引数のstderr露出、one-run許可がCron設定に依存する点。別プロセス・同一モデル系列の静的レビューであり、レビュー担当はCron設定・provider・DB・Discordを実行確認していない。こちらでCronをread-backし、worktreeとsnapshotの12/12 hash一致を確認した。
- P2の非侵襲確認（10:59 JST）では、このターミナル環境から`claude`が解決し、`~/.local/bin/claude`が実行可能だった。CLIは起動しておらず、これはCron実行環境のPATHや過去の実行状態を証明しない。
- 前回のwrapper dry-runは許可済み候補を検出したが、Claude呼出し・保存・配信は通していない。件数は実行時の候補で変わるため、完了指標にしない。
- `agent-level-open-ended-loop`（`76ed8251a41a`）は固定fixtureのShadow回帰。実会話レビューとは入力・保存先・判定対象が異なる。「新規意味ケース4件」は日別ファイル内での新規性表示で、10/27と10/28のケース集合は同じ。これを新しいOperational Evidenceと数えない。修正するなら別トラックで扱う。
- 実装・計画は未コミットworktree上にある。10/26のテスト成功はその時点のmock/fixtureの結果であり、10/27・10/28の実Cron失敗を覆さない。

根拠: 本worktreeの `scripts/run_conversation_review_cycle.py`、`scripts/auto_evaluate_recent_session.py`、`scripts/evaluate_session_with_claude.py`、Cron wrapper、共有試行台帳の状態列、10/27・10/28のCron通知、`docs/anthropic-insights-implementation-plan.md` §9–10。

## 4. 実施順序と各ゲート

### P0 — 失敗の所在を安全に確定する（最優先）

- **作業:** Cron設定、実際に呼ばれるwrapper→v2 cycle→Claude CLI→検証→保存→stdout/Discordの経路を固定し、過去の失敗台帳・Cron終了状態と突合する。再実行で原因を推測しない。生の会話、provider stderr、プロンプト、認証情報をログやDiscordへ出さず、失敗段階を `candidate_scan / provider_launch / provider_response / result_validation / report_write / report_readback / delivery` 等の固定コードで表す。予期しない例外は`unknown / unknown_failure`へ写像し、例外メッセージや例外クラス名は保存しない。
- **成果物:** 呼出し経路、確認できた失敗境界、未特定の再現条件、段階別の安全な失敗分類、過去分に対する「段階未確認」の明示。
- **受入/停止:** 過去の試行で分かる境界と分からない境界を列挙する。過去ログだけで段階を確定できなければ`unknown`のまま。診断を加えずに次の実Claude試行を消費しない。次の09:00までにP1を入れられない場合、同じ失敗の反復を避けるため**Cron一時停止を提案**する（設定操作は別途確認し、未承認なら変更しない）。

### P1 — 安全診断と失敗経路の回帰テスト

- **作業:** cycleとwrapperの最小変更で、固定の失敗段階・分類を1件の試行記録と通知へ伝える。`NO_CANDIDATE`無通知、`DAILY_CAP`、`LOCKED`、`EVALUATION_FAILED`、`OK`、保存後に通知だけ失敗した状態を分離する。実プロバイダーを呼ばないfake CLI/一時DB/一時出力で、起動失敗、timeout、形式不正、根拠位置不正、保存失敗、読戻し失敗、wrapper出力失敗を検査する。成功出力に会話ID・本文・stderr・秘密情報が混入しないことをcanaryで確認する。
- **成果物:** 失敗段階を限定したコード・テスト結果・運用者が読める非機密の診断表示。
- **受入/停止:** 失敗時に同日再実行しない。失敗分類のテストと既存6軸・許可範囲・共有試行上限の回帰が通る。機密が疑われれば表示・送信を止め、分類だけ残す。外部providerが必要なテストや上限緩和をP1の必須条件にしない。

### P2 — 根本原因を特定して修正する

- **作業:** まず外部送信を伴わない環境確認・fake CLI・一時出力で、CLIの実行環境、応答形式/Schema、位置検証、保存/読戻しのどの段階かを切り分ける。原因が再現できれば最小修正を行い、修正前に失敗する合成テストと修正後の関連unittestを通す。実provider経路でしか分からない場合は`unknown`とし、P3の次の既承認枠を**診断run**として観測してからP2へ戻る。`except`で成功へ置換しない。
- **成果物:** 原因→修正箇所→回帰テストの対応、復旧/差し戻し手順。
- **受入/停止:** 原因を示す失敗の再現と修正後PASS、または「実provider診断run待ち」のどちらかを明示する。wrapperを戻す場合は保存済み旧版を比較し、v2評価・日次台帳・配信先が変わる影響を確認してから操作する。テストPASSだけで定期評価成功とは報告しない。

### P3 — 許可された実会話で定期E2Eを受入判定する

**実行判断（10/29一回限りのリスク受容）:** 2026-10-28 13:26 JSTの12ファイルread-only reviewは、evaluation recordとreportの全項目をDiscord送信前にfail-closedで確認する仕組みがなく、郵便住所・生年月日等の個人情報が含まれた場合に自動配信され得る構造を指摘した。実際の候補に該当情報があるかは未確認。この技術的指摘は残すが、ユーザーはこのリスクの説明後に10/29一回分の送信を明示的に許可し、P1による実行停止判断に異議を示した。よって今回に限り、P1は技術上の残余リスクとして記録し、実行ブロッカーとは扱わない。既存one-shotは変更せず実行対象とする。pre-delivery gateが実装済みとは主張しない。この例外は今回の一回だけで、再試行・追加配信・将来の定期運用を許可しない。

- **前提:** P0/P1を完了し、P2で再現した原因は修正済みであること。実providerでしか原因を観測できない場合は、次の既承認枠の予定実行を診断runとし、その結果でP2へ戻る。許可済み対象・外部送信範囲・JST共有日次1試行の枠を守る。枠が使用済みの日は翌日以降の予定実行を待つ。手動再実行や直接CLIで回避しない。Cronを一時停止した場合、再開の影響と実行日時を示し個別に確認する。
- **作業:** 実ジョブの結果、台帳の同じJST日、実レポートの評価参照、実際のDiscord投稿を相互照合。失敗が保存後の配信境界なら、レポートが安全と確認できる範囲で保存済み成果物の配信手順を別途設計し、Claude再評価で通知をリトライしない。
- **成果物:** 実行日・境界別結果・評価参照・配信確認・安全な根拠抜粋。候補なしの日は`no_candidate`とE2E未確認を記録。
- **受入/停止:** 診断runで失敗段階が判明しただけならP2へ戻り、E2E受入とは記録しない。§2の同一実行(a)〜(e)が揃えば受入。10/29一回に限り、レポートへ氏名・組織名以外の個人情報が含まれ得るリスクはユーザーが説明を受けて受容済みのため、このリスクのみを理由に実行を止めない。根拠抜粋が発言と合わない、保存物と投稿が違う、配信先が違う場合は当該runを不合格とし、訂正・再配信・再評価は別途許可なしに行わない。追加runや将来の定期運用にはこの受容を適用しない。

#### 10/29の一回実行：結果別の復旧手順

この実行は診断を兼ねる一回限りの実会話runとする。結果は必ずCron実行状態・JST日次台帳・評価成果物・Discord投稿を照合して分類する。許可チャンネル、候補選定規則、日次1試行枠は維持する。手動起動、直接CLI、同日再試行で枠を迂回しない。次の実会話runが必要になった場合は、判明した段階・修正・再テスト結果・新しい実行日時を示し、別途許可を得る。

1. **Cronの実行記録がない／起動を確認できない:** Cronのrun履歴、wrapper状態、台帳を照合し、未起動・実行中・記録不一致を分ける。台帳read-back不能などで試行枠が不明なら`unknown`として止め、消費なしと決めつけない。手動実行で穴埋めしない。
2. **`NO_CANDIDATE`:** 正常な無通知。実行失敗とはしないが、実会話E2Eは未確認。対象範囲を広げず、候補なしを記録する。別候補での実評価には新しい一回分の許可が必要。
3. **`DAILY_CAP`:** 同じJST日の試行枠が先に消費されている場合、wrapperが正常終了扱いでも候補評価は行われていない。日次台帳と該当する評価成果物をread-onlyで照合し、このrunを「評価なし・E2E未達」と記録する。枠の消費状態が不明なら`unknown`として止める。同日再試行や迂回はせず、別の実会話runには別途許可を得る。
4. **`LOCKED`:** 別の実行がロックを保持しているため、このinvocationでは評価せず、試行も予約していない。Cron記録、ロック保持側の完了状態、JST日次台帳、該当成果物を照合してから、その日の枠状態を判断する。ロックを迂回・再試行せず、このrunはE2E未達と記録する。
5. **状態・候補走査・Claude起動/応答・結果検証の失敗:** `error_phase / error_code`、Claude起動到達の有無、`daily_cap_consumed`（`true / false / null`）を分けて記録する。生の会話、prompt、stderr、秘密情報は報告へ出さない。再現可能な境界は一時DB/fake CLIで再現し、最小修正と回帰テストを行う。修正後も実providerの追加実行は新たな承認を待つ。
6. **保存・読戻し・評価台帳の不整合:** Discordへ成功レポートとして出さない。`evaluation_ref`、`evaluation.json`、`report.md`、試行記録をread-onlyで照合し、正本と同一性を確認する。不一致または状態不明なら不合格・追加実行停止とする。
7. **レポート保存後のDiscord配信失敗:** Claude評価を再実行しない。保存済み成果物の安全性、参照、本文を確認し、配信だけの復旧方法を別途決める。重複投稿を避け、追加投稿はその実施内容を示して許可を得てから行う。
8. **配信済みだが、根拠位置・抜粋・評価参照・内容または配信先に不整合がある:** E2E受入を不合格とし、以後の配信を止める。正しい発言位置との照合を行い、個人情報の実値を再掲せず分類だけを記録する。今回の一回限りのリスク受容は実行後の内容・根拠不整合を受け入れるものではない。訂正・再配信や再評価は自動実行しない。

**技術的受入:** 同一runで適格候補、Claudeの有効な評価、保存物とread-backの一致、同じ評価参照のDiscord投稿、根拠位置と抜粋の照合がすべて成立した場合に限り、初回の技術的E2E確認とする。これを評価内容の妥当性や継続運用実績とは呼ばず、人手校正へ分ける。

### P4 — 意味評価の校正と継続運用

- **作業:** P3で得た軌跡と6軸をユーザーが自然文で校正し、`review.json`へ対象軸・理由・未回答pendingを分けて保存する。モデル判定の一致/過大/過小/判定不能不一致を比較する。構造の異なる適格会話が得られたとき同じ確認を繰り返す。初期の問いが欠ける場合は会話選定・切詰め・要約のどこで欠けたかを確かめ、元記録にない内容は補わない。
- **成果物:** 読み手が判断できるレポート、人手校正、誤判定と未観測の一覧、定期運用runbook（候補なし／評価失敗／保存成功・配信失敗／重複防止／復旧）。
- **受入/停止:** 実際の人手校正があり、その訂正を比較結果に反映できる。固定fixtureのPASSやモデルの自己評価を妥当性の証拠に代用しない。1件の同意で普遍的精度やAgent Levelを主張しない。別チャンネル追加や長い会話の分割が必要なら別の決定に回す。

## 5. 変更境界・責任・記録

- Hermes（作業者）: コード・mockテスト・安全な診断・計画更新・成果の読戻し。ローカル出力は`conversation-review-output/`内に限定し、`evaluation.json`を機械可読の正本、`report.md`を配信表示とする。試行台帳は状態管理、Discordは配信の実測記録。生の会話全文とClaude入力全文を新たに保存しない。
- ユーザー: 実会話の意味校正と、Cron停止/再開や範囲・頻度変更、Git commit/push、Gateway/Production/Promotion等の別境界の判断。既に承認された現在の対象・頻度を拡大しない。
- 失敗時: 実行コード/種類と、未達の境界だけを通知。既存の1日1試行を守る。通知障害は評価失敗へ混ぜず、保存物の同一性を確認してから安全な再通知を検討する。
- Git: 未コミットの他作業を保全し、作業ブランチ/差分・対象ファイルを確認してから別依頼で反映する。レポート・台帳・秘密情報をstageしない。mainへの直接pushは事前確認が必要。
- 変更しない: `agent-level-open-ended-loop`、Gateway observer/Outbox/R2、Evidence GateのPromotion入力、通常Agent Runtime、スキル自動反映、外部送信対象、日次上限。Cronは確認済みの10/29 one-shot設定を維持し、追加変更は別途許可を得る。

## 6. 実稼働の判定欄（進捗更新用）

- P0: 完了（2026-10-28 10:59 JST）。実Cron設定、wrapper→cycle→Claude CLI→検証→保存→stdout/Discordの経路、過去試行台帳を照合。10/27・10/28は失敗枠を消費し、原因段階は過去記録から復元不能。過去分は`unknown`。
- P1: allowlist固定の`error_phase / error_code`、台帳移行コード、wrapper通知、読戻しと評価失敗の区別を実装。未知roleをprovider input/reportから除外し、成功dedupe recordとattempt終端状態を同一transactionにまとめ、CLI parse errorを固定文にする回帰修正を追加。指定5モジュールsuiteは66件PASS。10/29の一回に限り識別子を含む現行送信経路をユーザーが明示承認。実台帳schema移行は未確認。
- P2: 10/27・10/28の定期失敗の原因は未特定で、今回の修正は過去の失敗原因を説明しない。先行reviewのTOCTOU指摘は同時にローカルpathを変更できるactorがいる場合の条件付き残余リスクとして未修正。2026-10-28 13:21 JSTのreviewで`DAILY_CAP`・`LOCKED`と識別情報の停止条件に関するP2指摘は反映済み。2026-10-28 13:26 JSTのread-only reviewは個人情報のfail-closed pre-delivery gateが未実装であることを指摘した。実データに該当情報が含まれるかは未確認。ユーザーはリスク説明後に今回の一回分を許可したため、技術的残余リスクとして保持し、今回の実行ブロッカー判定は適用しない。
- P3: Cron `35b6e4cf551e` は最終read-backおよび現状確認で10/29 09:00 JSTの1/1実行が有効。ユーザーは個人情報gate不在のリスク説明後、今回の一回分の送信を許可した。P1指摘を技術的に解消したとは扱わず、今回限りのリスク受容として実行を認める。provider評価、成果物保存/readback、同一refのDiscord投稿は未確認。Cron・コードの追加変更、再試行、追加配信は行わない。
- P4: 未達。10/26手動レポートの人手校正はpending。
- 実稼働受入: **未達・10/29の一回実行待ち**。Cron `35b6e4cf551e` は10/29 09:00 JSTのone-shot有効。2026-10-28 13:26 JSTのreviewが指摘したprivacy gate不在は未解消だが、ユーザーは開示された個人情報混入リスクを受け入れ、今回一回の送信を許可した。したがって今回の実行はブロックしない。実会話評価・保存/readback・Discord投稿は未確認であり、候補なしや失敗はE2E成功としない。再試行・追加配信・将来の実行は別途許可が必要。対象チャンネル・既定1日1試行上限・Gateway・Promotion・Productionは変更していない。評価結果レビュー前のcommit/pushなし。
