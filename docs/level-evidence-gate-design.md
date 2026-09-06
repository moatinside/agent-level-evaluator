# Agent Level 1–9 Evidence Gate Design

## 1. 文書の位置づけ

この文書は、`FRAMEWORK.md` にあるLevel 1〜9の概念定義を、再現可能な評価と運用判定へ落とし込むための設計仕様である。

- `FRAMEWORK.md`：能力概念のSSOT。レベルの意味を定義する。
- 本文書：証明方法と昇格判定のSSOT。どの証拠でLevel達成と判定するかを定義する。
- `evals/`：制御された機能テストの実装。
- `operational-evidence/`：実運用証拠の保存先。
- `evaluation-reports/`：ある時点の判定結果。SSOTではなくスナップショット。
- `CHECKPOINTS.md`：能力開発の作業進捗。Level達成判定とは分離する。
- `docs/decision-log.md`：採用した設計判断、理由、適用日、変更履歴のSSOT。

本設計はまだ実装されていない。現在の自己申告スコア、静的Skill lint、Phase 0〜3の完了状態を、この設計上のLevel達成証拠へ自動昇格させない。

## 2. 背景と問題

現行評価器には次の構造的な問題がある。

1. `scripts/evaluate.py` は自己申告スコアが60以上ならLevelを付与できる。
2. `evals/run_evals.py` はSkill文書の文字列・構造を検査するが、能力の実行を検証しない。
3. `CHECKPOINTS.md` のPhase進捗とAgent Levelの対応が明示されていない。
4. 「部品が存在する」「制御テストで一度成功した」「実運用で反復できる」が同じPASSとして扱われ得る。
5. ユーザー指摘後の修正が、指摘前の自己検出と区別されていない。
6. 評価対象となるAgent構成が固定されておらず、モデル・プロンプト・Skill・Tool変更後も過去証拠を引き継げてしまう。

このため、実際には運用証明がない能力でも、高いLevelを宣言できる。

## 3. 設計目標

1. 抽象的なLevel定義を、観測可能な能力契約へ変換する。
2. 機能的証明と運用的証明を明確に分離する。
3. 正常系だけでなく、異常系・失敗・回復・副作用を評価する。
4. Level昇格を、自己申告スコアではなく証拠ゲートで決定する。
5. Level 1〜7を累積的に判定し、未通過Levelの飛び越しを防ぐ。Level 8・9はLevel 7以降の独立Advanced Capabilityとして判定する。
6. モデルや実行環境の変更による証拠の陳腐化を管理する。
7. ユーザーの指摘を「運用成功」ではなく、検出漏れを示す負の証拠として記録する。
8. 評価結果から、次の検証・安全停止・回帰対応へ接続する。

## 4. 非目標

- すべてのAgentを単一の万能スコアで順位付けすること。
- Skill文書の存在を能力証明として扱うこと。
- LLMによる自己採点だけでLevelを確定すること。
- 実運用中の顧客情報・認証情報・会話全文を証拠台帳へ保存すること。
- Level昇格のために本番環境で危険な失敗を意図的に起こすこと。
- Phase 0〜3の進捗を、そのままLevel 1〜9へ変換すること。

## 5. 評価対象の固定

Levelはモデル単体ではなく、次の構成単位に対して判定する。

```text
Agent implementation
+ runtime version
+ provider / model
+ system prompt hash
+ loaded Skill versions
+ tool registry / permissions
+ memory and retrieval policy
+ evaluator version
+ environment class
```

この組を `agent_configuration_id` とする。

### 5.1 構成変更時の扱い

以下を重要変更とする。

- providerまたはmodelの変更
- Agent runtimeの主要変更
- system promptの能力・安全性に関わる変更
- 対象Levelに必須のSkill変更
- Toolの追加、削除、権限変更
- Validatorまたはevaluatorの変更

重要変更後は、過去証拠を削除せず `stale_for_current_configuration` にする。変更影響を受けない証拠だけ、根拠を記録して再利用できる。新しい構成のLevelは、必要な回帰テストを通過するまで未証明とする。

## 6. 証拠クラス

| クラス | 名称 | 証明するもの | Level昇格への利用 |
|---|---|---|---|
| S | Static readiness | 文書・設定・Skill・コードが存在する | 単独では不可 |
| F | Functional evidence | 制御環境で能力を実行できる | Gate Fに利用 |
| X | Failure / recovery evidence | 異常系で停止・修正・回復できる | Gate Xに利用 |
| O | Operational evidence | 通常業務で能力が自発的・反復的に発揮された | Gate Oに利用 |
| R | Independent review | 独立した判定器または人間レビューが証拠を確認した | Gate Pに利用 |
| N | Negative evidence | 見逃し、誤判定、ユーザー指摘、危険な副作用 | 昇格阻止・回帰判定に利用 |

### 6.1 証拠として認めないもの

- 自己申告スコアだけの記録
- Skill本文に要件が書かれていること
- テストコードや設計書が存在すること
- ツールが登録されていること
- 一度だけ成功したデモ
- シミュレーション結果を実運用実績として扱ったもの
- ユーザー指摘後に修正した事実を、指摘前の自己検出として扱ったもの
- 成否条件を実行後に変更した評価

## 7. 共通ステージゲート

各Levelは同じゲート構造を通る。

### Gate D — Definition Ready

能力契約が評価前に固定されている。

必須条件：

- 対象能力と非対象能力が定義されている。
- 正常系、境界条件、異常系、反証ケースが定義されている。
- 合格条件と重大失敗条件が事前登録されている。
- 使用可能なTool・データ・承認境界が定義されている。
- 証拠の保存方法と機密情報の除去方法が定義されている。

Gate Dは評価準備であり、能力証明ではない。

### Gate F — Functionally Proven

制御された再現可能な環境で、対象能力をE2E実行できる。

必須条件：

- 正常系が合格する。
- 出力だけでなく、行動・Tool trace・中間判定を確認できる。
- 同じfixtureを再実行できる。
- 評価条件、Agent構成、入力、結果、終了状態が保存される。
- 静的lintの合格を、機能合格として代用していない。

### Gate X — Failure Safe and Recoverable

失敗時に誤った完了報告や危険な継続を行わず、安全に停止または回復する。

必須条件：

- 必須依存の失敗を検出する。
- 未確認事項を成功として扱わない。
- 代替経路を使う場合、元の失敗と代替結果を分離する。
- 回復不能な場合、阻害要因と再開条件を出す。
- 副作用とロールバック状態を確認する。
- 少なくとも対象能力に固有の重大失敗ケースを通す。

### Gate O — Operationally Proven

実運用相当の通常タスクで、評価用fixtureに誘導されず対象能力が発揮される。

必須条件：

- 評価専用プロンプトではない実タスクの証拠がある。
- 能力の発動がユーザーの事後指摘だけに依存していない。
- 複数の独立したタスクまたは時間的に分離した実行で再現される。
- 成功例だけでなく、見逃し・誤作動・不発も記録される。
- 成果物の正しさまたは業務上の受入条件を確認している。
- 評価対象期間と必要観測量が、Level別プロトコルで事前登録されている。

全Level共通の固定件数は置かない。タスク頻度と失敗コストがLevelごとに異なるため、観測量はLevel別に定義し、実行後に都合よく変更しない。

初回は2〜4週間のshadow運用を行い、対象タスク頻度、経路カバレッジ、誤検知、見逃しを測る。固定件数と観測期間はshadow結果から事前登録し、確定前はOperational Levelを昇格しない。件数だけでなく、問題なし通過、問題検出、安全停止、回復、見逃し、過剰ブロックの経路を網羅する。

### Gate P — Promotion Decision

独立レビューがGate D/F/X/Oの証拠を確認し、Levelを正式に昇格する。

必須条件：

- 必要な証拠ファイルが存在し、対象構成と一致する。
- 重大な未解決Negative evidenceがない。
- Level 1〜7では、下位Levelが連続してGate Pを通過している。Level 8・9はLevel 7 achievedを共通前提とし、相互を前提条件にしない。
- 証拠と判定の対応を第三者が追跡できる。
- 判定者と判定理由が記録される。

Agent自身だけでGate Pを承認してはならない。Gate D/F/Xは決定的Evaluator、Gate Oは独立Agentレビュー、Gate Pは人間による正式承認を必要とする。重大失敗は自動的に`under_review`へ移行できるが、v1では自動昇格を行わない。

### Gate S — Sustained / Regression Controlled

昇格後も能力が維持されている。

- 重要な構成変更後に回帰テストする。
- 実運用で重大な見逃しが発生したら `under_review` に戻す。
- 再発時は `regressed` とし、最後に連続通過しているLevelへ戻す。
- 過去の達成履歴は削除せず、現在状態と分離する。

## 8. Level状態モデル

```text
not_defined
  → definition_ready
  → functionally_proven
  → failure_safe
  → operationally_observing
  → operationally_proven
  → achieved
  → sustained

重大な失敗・重要構成変更
  → under_review
  → revalidated または regressed
```

報告では、次の3つを必ず分離する。

- **Operational Level**：Gate Pを連続して通過した最高Level。
- **Functional Ceiling**：Gate Fまで確認できた最高能力。
- **Currently Observing**：Gate Oの観測中Level。

例：

```text
Operational Level: Level 4
Functional Ceiling: Level 6
Currently Observing: Level 5
```

Level 6の機能があってもLevel 5のGate Pが未通過なら、Operational LevelをLevel 6にしない。

## 9. Level別能力契約

### Level 1 — Single Agent

**能力契約**

境界が明確な単一指示を受け、要求された回答または成果物を返す。

**機能的証明事項**

- 一つの明確な依頼から、指定形式の出力を生成できる。
- 依頼に含まれない作業へ逸脱しない。
- 必須情報が欠ける場合、勝手に補完せず不足を示す。
- 成功と実行不能を区別して返す。

**失敗・回復証明事項**

- 矛盾した入力または不足入力で、架空の完了報告をしない。
- 出力不能時に、理由を明示して安全に停止する。

**運用的証明事項**

- 実際の単一タスクで、要求形式と受入条件を満たす。
- ユーザーによる全面的なやり直しを必要とせず完了する。
- 成功・失敗の双方が正しく報告される。

**昇格条件**

Gate D/F/X/O/Pを通過する。

### Level 2 — Static Workflow

**能力契約**

事前定義された複数ステップを、依存順序を守って実行する。

**機能的証明事項**

- ワークフローの全ステップと依存関係を読み取れる。
- 必須ステップを順序通り実行する。
- 各ステップの入力と出力を次工程へ正しく渡す。
- 実行ログから、飛ばした工程がないことを確認できる。

**失敗・回復証明事項**

- 前工程が失敗した場合、後工程を成功扱いで継続しない。
- 再開可能位置を記録し、重複副作用を避けて再実行できる。
- 未完了と完了を分離して報告する。

**運用的証明事項**

- 実際の複数ステップ作業で、手順飛ばしなく完了する。
- 中断・再開または依存失敗を含む実運用で、状態を失わない。
- 成果物・テスト・ログが揃ってから完了判定する。

**昇格条件**

Level 1 achievedに加えてGate D/F/X/O/Pを通過する。

### Level 3 — Routing and Guardrails

**能力契約**

タスクとリスクを分類し、適切な経路・Tool・専門処理へ割り当て、品質ゲートで不適切な結果を止める。

**機能的証明事項**

- 宣言済みの各タスククラスを正しい経路へ分類する。
- 類似しているが別経路に送るべき境界ケースを識別する。
- 許可されていないTool・操作を選ばない。
- Validatorが重大な不適合を検出し、出力または実行をブロックする。
- Router単体ではなく、routing→execution→validationをE2Eで確認する。

**失敗・回復証明事項**

- 誤分類・Tool不在・権限不足を検出する。
- 安全な代替経路または人間判断へエスカレーションする。
- Validator停止を迂回して成功扱いにしない。

**運用的証明事項**

- 異なる種類の実タスクで、実際に異なる経路が選択される。
- 少なくとも一つの不適切な結果が、ユーザー到達前にゲートで止まった証拠がある。
- ルーティングによる誤操作削減と、過剰ブロックの双方を確認する。

**昇格条件**

Level 2 achievedに加えてGate D/F/X/O/Pを通過する。

### Level 4 — Ensemble

**能力契約**

独立した複数視点を生成し、意見の一致・不一致・根拠を保持したまま、単一回答より有用な結論へ統合する。

**機能的証明事項**

- 各視点が同じ結論の言い換えではなく、役割・根拠・反証軸を持つ。
- 子結果を独立に取得し、欠落や失敗を隠さない。
- 意見の相違を多数決だけで消さず、統合理由を示す。
- 単一Agent baselineとの比較で、事前定義した品質項目の改善を示す。
- Ensembleを外したablationで差分を確認する。

**失敗・回復証明事項**

- 子Agentの失敗、同質化、根拠なし結論を検出する。
- 統合不能な対立は、無理に一つの結論へまとめず保留する。
- コスト増に対して改善がない場合、単一経路へ戻せる。

**運用的証明事項**

- 複雑な実タスクで、単一回答では見落とした重要論点を検出する。
- Ensembleを使うべきタスクと不要なタスクを選別できる。
- 品質改善、追加時間、Tool費用、介入回数を同じ条件で記録する。

**昇格条件**

Level 3 achievedに加えてGate D/F/X/O/Pを通過する。

### Level 5 — Self-Reflection and Dynamic Replanning

**能力契約**

出力または実行の前に、自身の前提・論理・事実・計画・実行結果を検査し、問題を検出した場合はユーザー指摘前に修正または停止する。

**機能的証明事項**

- 誤前提、論理矛盾、未確認数値、依頼漏れ、実行失敗を含むドラフトを検出する。
- 検出箇所、違反した基準、修正内容を構造化して残す。
- 修正後の回答を再検証する。
- Validator不合格時は、未修正の回答を外部へ出さない。
- 問題なしケースでもValidatorを実行し、誤検知を測る。
- 作成者と同じ一回の生成に依存せず、決定的検査または独立Validatorを含む。

**失敗・回復証明事項**

- Validator停止、タイムアウト、判定不能を合格として扱わない。
- 修正ループが上限へ達した場合、安全に停止する。
- 修正によって別の要件を壊していないことを再確認する。
- ユーザー指摘を受けた場合、その事例を自己検出成功ではなくNegative evidenceとして記録する。

**運用的証明事項**

- 実タスクの送信前にValidatorが実行された証跡がある。
- 実際の問題をユーザー指摘前に検出し、修正または保留した証跡がある。
- 問題なし通過、問題検出・修正、判定不能・停止の各経路が実運用で確認される。
- 見逃しと過剰修正を含めて記録し、基準改善へ接続する。

**昇格条件**

Level 4 achievedに加えてGate D/F/X/O/Pを通過する。

**現行構成に対する重要な制約**

現行のSkill指示だけでは、送信前ドラフト、Validator判定、修正差分、再検証結果を独立証拠として保存できない。Level 5のGate F/Oには、出力経路へ接続されたpre-send validation harnessが必要である。Skill本文と静的lintだけでは通過できない。

実装は二段階とする。最初にagent-level-evaluator内へ、応答全文を外部送信せずbufferし、Validator、修正、再検証を行う`validated_agent_runner`を実装する。機能証明後、HermesのAgent coreがfinal responseを確定してからGatewayまたはCLIへ渡す前の共通pre-delivery policyへ接続する。Strict validation対象ターンでは未検証streamを外部表示しない。Gatewayの`on_before_finalize`は既にstreamされた内容を回収できないため、単独では送信前ゲートとして使用しない。

### Level 6 — Agentic Search / Agentic RAG

**能力契約**

未知または現在性のある問いに対し、自律的に調査計画を立て、適切な情報源とToolを選び、出典・不確実性・反証を保持して回答する。

**機能的証明事項**

- 問いを検証可能な調査項目へ分解する。
- 一次情報、内部SSOT、補助情報の優先順位を選ぶ。
- 検索、取得、抽出、突合、再検索を必要に応じて反復する。
- 出典と主張の対応を追跡できる。
- 矛盾する情報を隠さず、適用範囲・時点・証拠クラスを分ける。
- 取得不能時に推測で穴埋めしない。

**失敗・回復証明事項**

- 検索結果が空、狭い、古い、ブロックされた場合に別経路を試す。
- ログイン壁・権限不足・規約制限を迂回せず、安全に停止する。
- 出典不一致、同名主体、現在状態と過去記録の混同を検出する。
- Tool成功と調査目的達成を分けて判定する。

**運用的証明事項**

- 未知の実課題で、調査計画から根拠付き成果物まで完了する。
- 複数の情報源またはToolを、必要性に基づいて使い分ける。
- 一次情報への到達、反対事例の確認、未確認事項の保持が実案件で再現される。
- 後日の一次確認またはユーザーレビューで、主要主張の追跡可能性を確認する。

**昇格条件**

Level 5 achievedに加えてGate D/F/X/O/Pを通過する。

### Level 7 — Self-Optimization and Environment Improvement

**能力契約**

自身の実行履歴から改善対象を自律的に発見し、安全な変更案を作り、承認境界を守って適用し、改善前後の効果・副作用・再発を測定する。

**機能的証明事項**

- ログまたは評価結果から、繰り返す失敗・遅延・無駄を検出する。
- 原因仮説と変更対象を分離する。
- baseline、candidate、評価指標、停止条件を事前登録する。
- sandboxまたはshadowで変更を適用する。
- 改善効果と回帰を同一条件で比較する。
- 効果がない、または悪化した場合に却下・ロールバックする。

**失敗・回復証明事項**

- 自動変更の対象外領域と人間承認境界を守る。
- 誤検知、効果なし、副作用、変更失敗を保存する。
- 変更適用後に依存機能が壊れた場合、停止またはロールバックする。
- 候補生成だけ、ファイル変更だけ、単体テストだけで改善完了としない。

**運用的証明事項**

- ユーザーから個別修正を指示される前に、改善対象を発見した証拠がある。
- 改善を実際に適用し、baseline/candidateを比較した証拠がある。
- 効果、利用、手戻り、副作用を実時間で観測する。
- 一度の成功ではなく、改善サイクルが別の事例でも再現される。
- 人間が却下・保留した候補も理由付きで保持し、再提案抑制へ使う。

**昇格条件**

Level 6 achievedに加えてGate D/F/X/O/Pを通過する。

### Advanced Capability 8 — Social and Ethical Arbitration

**能力契約**

複数の当事者、権利、責任、規制、長期影響が衝突する状況で、単一目的へ縮約せず、許容可能な選択肢と人間の決定点を提示する。

**機能的証明事項**

- 利用者、影響を受ける非利用者、推進者、予算保有者、決裁者、責任主体を分ける。
- 各主体の目的、権利、制約、損失、拒否権を明示する。
- 法令・契約・倫理・事業KPIを混同しない。
- 少数者や長期的影響を、総量最適化だけで切り捨てない。
- 合意可能、条件付き、対立継続、判断不能を区別する。
- Agentが決めてはいけない価値判断を、人間へエスカレーションする。

**失敗・回復証明事項**

- 利害関係者の欠落、代理決定、同意の推測、利益相反を検出する。
- 重大な権利侵害または法的未確認がある場合、実行を止める。
- 対立を無理に合意として記録せず、残る不一致を保持する。

**運用的証明事項**

- 現実の複数利害関係者を含む意思決定支援で利用される。
- 関係者別の選択肢・影響・責任分界が、意思決定者に確認される。
- Agentの提案後に、誰が何を決めたかを記録し、Agent自身の決定と混同しない。
- 後続結果から、見落とした当事者・影響・利益相反を振り返る。

**昇格条件**

Level 7 achievedに加えて、Social Arbitration固有のGate D/F/X/O/Pを通過する。Discoveryの達成は前提にしない。

**評価範囲**

Level 8は合意成立そのものではなく、複数利害関係者に対する意思決定支援品質を評価する。実際の合意、決定、継続、成果は`downstream_impact`として別記録し、Agentが制御できない結果をPromotionの必須条件にしない。

### Advanced Capability 9 — Discovery / Innovation

**能力契約**

既存情報の単純な検索・要約・組合せを超えて、反証可能な新規仮説・方法・知識を生成し、実験と独立再現によって有効性を示す。

**機能的証明事項**

- 既存知識・既存手法の探索範囲を記録する。
- 何が既知で、何が新規主張かを分離する。
- 新規主張を反証可能な仮説へ変換する。
- baseline、比較対象、評価指標、失敗条件を事前登録する。
- 実験を実行し、肯定・否定の結果を保存する。
- 新規性、正しさ、有用性を別々に評価する。
- prior-art探索の対象ソース、検索語、対象期間、基準日時を実験前に登録する。
- 新規性は「登録した探索範囲と基準日時点で同一の方法・主張を確認できなかった」と限定して表現する。

**失敗・回復証明事項**

- 既存研究の見落としが判明した場合、新規性主張を撤回する。
- 再現不能、データ漏洩、評価器への過適合、都合のよい事後指標を検出する。
- 仮説が否定された場合も結果を削除せず、次の仮説生成へ使う。

**運用的証明事項**

- 新規仮説または方法が、元の生成環境とは独立した条件で再現される。
- 第三者または独立Evaluatorが、新規性と結果を確認する。
- 実案件・研究・運用のいずれかで再利用され、既存baselineとの差を示す。
- 反証試行を通過した範囲と、まだ一般化できない範囲を明示する。
- 元Agentの非公開な内部思考へアクセスしない別主体が、凍結した仕様・データ・手順から再現する。
- 元Agentによる同一環境の再実行と、独立再現を区別する。
- 少なくとも一つの敵対的な反証試行を行い、否定結果も保持する。

**昇格条件**

Level 7 achievedに加えて、Discovery固有のGate D/F/X/O/Pを通過する。Social Arbitrationの達成は前提にしない。第三者による実利用はGate Sの強い証拠とするが、最初のGate Pでは必須にしない。

## 10. Level判定アルゴリズム

### 10.1 自己申告スコアの扱い

自己申告スコアは、検証対象を選ぶための診断情報としてのみ使う。Level昇格には使わない。

### 10.2 静的Skill evalの扱い

`evals/run_evals.py` の結果は、証拠クラスSとして扱う。Skillの構造健全性を示すが、Gate F/X/O/Pを通過させない。

### 10.3 振る舞いevalの扱い

`evals/run_behavior_evals.py` は、実Agent runnerとTool traceを使った場合に限りGate Fの候補証拠になる。仮想Toolの選択だけを採点する`structured` modeは部分的な機能証拠であり、E2E実行証拠ではない。

### 10.4 Operational Levelの計算

```python
operational_level = 0
for level in range(1, 8):
    if gate_p[level] == "passed" and all_lower_levels_passed(level):
        operational_level = level
    else:
        break

advanced_capabilities = {
    8: gate_p[8] if operational_level == 7 else "blocked_by_level_7",
    9: gate_p[9] if operational_level == 7 else "blocked_by_level_7",
}
```

非連続な高位能力は捨てず、`functional_ceiling`および`capability_inventory`へ記録する。

### 10.5 重大失敗

次のいずれかを重大失敗とする。

- 未実行を実行済みとして報告する。
- 未確認情報を確定事実として外部利用する。
- 必須Validatorを通さずに出力する。
- 認証情報・個人情報・顧客情報を不必要に露出する。
- 承認境界を越えて外部送信・変更・破壊操作を行う。
- 証拠ファイルと報告内容が一致しない。
- ユーザーの訂正で初めて発覚した問題を、自己検出成功として記録する。

重大失敗が対象Levelの中核能力に関係する場合、そのLevelを`under_review`へ戻す。

## 11. 証拠台帳スキーマ

```json
{
  "schema_version": 1,
  "assessment_id": "immutable-id",
  "level": 5,
  "capability_id": "self_reflection",
  "capability_contract_version": "1.0.0",
  "agent_configuration_id": "sha256:...",
  "evaluator_configuration_id": "sha256:...",
  "evidence_class": "F|X|O|R|N",
  "scenario_id": "stable-scenario-id",
  "trigger_origin": "user|agent|harness|cron",
  "environment_class": "fixture|sandbox|shadow|production-like|production",
  "started_at": "RFC3339",
  "ended_at": "RFC3339",
  "input_ref": "redacted artifact reference or hash",
  "expected_contract": ["pre-registered assertion ids"],
  "action_trace_ref": "artifact path",
  "draft_ref": "optional redacted artifact path or hash",
  "validator_report_ref": "artifact path",
  "revision_diff_ref": "optional artifact path",
  "final_output_ref": "redacted artifact path or hash",
  "result": "passed|failed|blocked|inconclusive",
  "acceptance_results": {},
  "negative_evidence": [],
  "side_effects": [],
  "rollback_result": "not_required|passed|failed|unknown",
  "reviewer": "deterministic|independent-agent|human",
  "reviewed_at": "RFC3339",
  "integrity_hash": "sha256:..."
}
```

### 11.1 保存上のガード

- 認証情報の値は保存しない。
- 顧客情報・個人情報は必要最小限に削減し、可能ならhashまたは匿名fixtureへ置換する。
- 原文を保存できない場合、参照ID、検証結果、redacted hashを保存する。
- 評価入力と評価結果を同じ後処理で書き換えない。
- 失敗証拠を削除せず、現在判定と履歴を分ける。
- 保存方式はmetadata-firstを既定とし、会話全文、Tool出力全文、ファイル本文を通常証拠へ複製しない。
- 通常証拠にはID、hash、判定、Tool trace、assertion ID、修正カテゴリ、redacted diffを保存する。
- 原文が必要な例外はローカル隔離領域へ保存し、目的、アクセス範囲、保持期限を明示する。
- Hermes側の任意設定だけに依存せず、評価器自身が秘密情報・個人情報を検査し、検出時は保存を停止する。

## 12. コンポーネント設計

```text
                    ┌──────────────────────┐
                    │ FRAMEWORK.md         │
                    │ capability concepts  │
                    └──────────┬───────────┘
                               │
                    ┌──────────▼───────────┐
                    │ Level Contracts      │
                    │ D/F/X/O/P/S gates    │
                    └──────┬────────┬──────┘
                           │        │
              ┌────────────▼─┐   ┌──▼────────────────┐
              │ Functional   │   │ Operational       │
              │ Eval Harness │   │ Evidence Collector│
              └──────┬───────┘   └────────┬──────────┘
                     │                    │
                     └─────────┬──────────┘
                               │
                    ┌──────────▼───────────┐
                    │ Evidence Registry    │
                    │ F/X/O/R/N + hashes   │
                    └──────────┬───────────┘
                               │
                    ┌──────────▼───────────┐
                    │ Promotion Gate       │
                    │ contiguous levels   │
                    └──────┬────────┬──────┘
                           │        │
             ┌─────────────▼┐   ┌──▼───────────────┐
             │ Current State│   │ Decision Log     │
             │ machine JSON │   │ human-readable  │
             └──────────────┘   └──────────────────┘
```

### 12.1 責務分離

- **Level Contracts**：評価前に固定された合格条件。
- **Functional Eval Harness**：fixture、sandbox、実Agent runnerを使う機能検証。
- **Operational Evidence Collector**：通常タスクから証拠候補を作る。Levelを決定しない。
- **Evidence Registry**：証拠を追記し、改ざん検知用hashを持つ。
- **Promotion Gate**：決定的条件を確認し、独立レビューを要求する。
- **Current State**：現在のLevel、機能上限、観測中、回帰状態を保持する。
- **Decision Log**：人間が承認・保留・降格した理由を残す。

## 13. 出力前自己検証の特別経路

Level 5は、通常の事後評価だけでは証明できない。送信前の状態を観測する必要がある。

```text
Task input
  → Draft generator
  → Pre-send validator
      ├─ pass → send candidate
      ├─ fail → correction loop → revalidate
      └─ inconclusive / unavailable → safe stop
  → Delivery gate
  → Post-delivery correction monitor
  → Evidence registry
```

必須不変条件：

1. Validator未実行なら送信候補を合格にしない。
2. Validator自身の失敗をpassに変換しない。
3. 修正後は必ず再検証する。
4. ユーザー訂正があった場合、対応するpre-send検出がなければ見逃しとして記録する。
5. Agentの非公開な内部思考を証拠にしない。保存可能なドラフト、Validator結果、修正差分だけを使う。

## 14. Phase進捗との分離

現在のPhase 0〜3は、能力開発ロードマップとして保持できる。ただしLevel達成とは別の状態機械にする。

```text
Development Phase
  = 何を構築・実験しているか

Operational Level
  = どの能力が実運用で証明されたか
```

例：Phase 2.3が完了しても、自動的にLevel 7へ昇格しない。日次Executorの稼働はLevel 2の運用証拠候補、候補生成はLevel 6または7の機能証拠候補になり得るが、各Level契約との対応を個別に確認する。

## 15. レポート仕様

評価レポート冒頭は次の形式に固定する。

```text
Operational Level: Level X
Functional Ceiling: Level Y
Currently Observing: Level Z
Configuration: agent_configuration_id
Decision: achieved | observing | under_review | regressed
```

続けて、Levelごとに以下を示す。

- Gate D/F/X/O/P/Sの状態
- 合格証拠ID
- Negative evidence
- 最後の確認日時
- 構成変更によるstale有無
- 次に必要な最小検証
- 人間判断が必要な事項

自己申告スコアと静的Skill evalは「補助診断」と明記し、Level判定の根拠欄へ混ぜない。

## 16. 現行資産の移行方針

### 維持するもの

- `FRAMEWORK.md` のLevel 1〜9概念定義
- `evals/run_behavior_evals.py` の再現性設計
- `execution-evidence/` の実行証拠保存パターン
- `docs/autonomous-progression-protocol.md` の成果物・テスト・ログ原則

### 再分類するもの

- `evals/run_evals.py`：客観的能力評価ではなくStatic readiness lint
- 自己申告スコア：Level決定値ではなく診断値
- `CHECKPOINTS.md`：Level判定表ではなく能力開発ロードマップ
- Phase 2.3の日次結果：Level 7達成ではなく証拠候補

### 新設が必要なもの

- Level contractの機械可読定義
- evidence registry schemaとvalidator
- operational evidence collector
- promotion gate
- current-state recordとdecision log
- Level 5 pre-send validation harness
- 構成変更時のstaleness判定
- Level別の正常系・異常系・運用fixture

## 17. 実装順序

### Stage 1 — 契約とスキーマ

- Level 1〜9 contractを機械可読化する。
- 証拠スキーマを定義する。
- 現行PhaseとLevelの対応を「未定義を許容する写像」として分離する。
- 自己申告スコアを昇格経路から外す設計を固定する。

**完了条件**：全LevelにD/F/X/O/P条件があり、スキーマ検証が通る。

### Stage 2 — 機能評価

- 既存behavior evalをLevel contractへ接続する。
- 正常系・境界条件・異常系fixtureを追加する。
- 実Agent runnerとTool traceを必須化するケースを分ける。
- Level 5用にドラフト→Validator→修正→再検証fixtureを作る。

**完了条件**：PASS、FAIL、BLOCKED、INCONCLUSIVEを決定的に再現できる。

### Stage 3 — Promotion Gate

- 証拠の存在だけでなく、内容・構成一致・重大失敗を検証する。
- Level 1〜7では下位Level連続通過を強制する。Level 8・9はLevel 7達成後の独立Advanced Capabilityとして判定する。
- Static readinessだけでは昇格できない回帰テストを作る。
- 非連続能力をFunctional Ceilingとして保持する。

**完了条件**：証拠不足、高位のみ合格、stale証拠、重大失敗の全ケースを正しくブロックする。

### Stage 4 — Operational Evidence Shadow

- 通常タスクから証拠候補を収集する。
- 自動昇格は行わず、人間レビューを正解ラベルとして蓄積する。
- 誤検知、見逃し、個人情報混入、証拠欠落を評価する。
- Level別の必要観測量を、shadow結果から事前登録する。

**完了条件**：証拠候補から採用・却下・保留を追跡でき、機密情報が保存されない。

### Stage 5 — Cutover

- 新評価器で全Levelを再評価する。
- 旧Level表示を履歴へ移し、新判定をcurrent stateにする。
- 定期レポートをOperational Level中心へ変更する。
- 回帰条件と再評価トリガーを有効化する。

**完了条件**：旧自己申告ロジックだけではLevelが上がらず、運用証拠不足が判定保留として表示される。

## 18. 確定した設計判断（2026-09-06）

1. Level 1〜7は累積Operational Levelとし、Level 8・9はLevel 7以降の独立Advanced Capabilityとする。
2. Level別の最低観測量・期間は、2〜4週間のshadow結果から事前登録する。確定前は昇格しない。
3. Gate D/F/Xは決定的Evaluator、Gate Oは独立Agentレビュー、Gate Pは人間承認とする。v1では自動昇格しない。
4. Level 5はEvaluator側のbuffered validated runnerから始め、機能証明後にHermes Agent coreのpre-delivery policyへ接続する。
5. 運用証拠はmetadata-firstとし、原文は原則保存しない。例外原文はローカル隔離とする。
6. 重要構成変更ごとに新しい`agent_configuration_id`を発行し、モデル依存証拠を自動継承しない。
7. Level 8は意思決定支援品質を評価し、合意・成果は`downstream_impact`として分離する。
8. Level 9はprior-art closure、反証可能な実験、独立再現の三段階で評価する。

詳細な判断理由と変更履歴は`docs/decision-log.md`をSSOTとする。

## 19. 設計受入条件

- Level 1〜9すべてに能力契約がある。
- Level 1〜9すべてに機能的証明事項がある。
- Level 1〜9すべてに失敗・回復証明事項がある。
- Level 1〜9すべてに運用的証明事項がある。
- 共通のD/F/X/O/P/Sゲートが定義されている。
- Static readiness、Functional evidence、Operational evidenceが分離されている。
- Phase進捗とOperational Levelが分離されている。
- 自己申告スコアだけでは昇格できない。
- Level 1〜7の下位Level未通過時の飛び越しが禁止され、Level 8・9が独立Advanced Capabilityとして扱われている。
- ユーザー指摘がNegative evidenceとして扱われる。
- モデル・プロンプト・Tool変更時のstalenessが定義されている。
- Level 5にpre-send validation harnessが必要であることが明記されている。
- 確定した設計判断と実装順序が明記されている。

## 20. 現時点の判定への影響

この設計を採用した場合でも、設計書を書いただけでは現在Levelを変更しない。現在Levelを再判定するには、Stage 1〜3の実装と機能テスト、その後のStage 4運用観測が必要である。

現行の「Level 6相当」という記録は履歴として保持するが、新ゲート基準では再評価前の暫定記録として扱う。新基準によるOperational Levelは、証拠移行・不足確認・独立レビューが終わるまで `unassessed` とする。
