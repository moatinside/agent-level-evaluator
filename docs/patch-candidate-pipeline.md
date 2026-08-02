# パッチ候補自動生成パイプライン — 設計書

> ステータス: **実装済み・検証済み**（2026-08-02）
> 目的: 「検出結果から自動でパッチ候補まで生成し、承認だけ人間に残す」機構

## 1. 全体像

```
state.db (tool_calls 21,784件)
   │
   ▼ ①検出 [完全機械]
repetition-detector.py --json  (T1〜T4 トリガー定義・コード固定)
   │  findings[] = [{trigger, kind, target, count, ...}]
   ▼ ②候補生成 [完全機械]
patch-candidate-generator.py
   │  → ~/.hermes/patch-queue/<id>.json (status=pending)
   ▼ ③承認 [人間のみ]
patch-approve.sh list / show / apply / reject
   │  apply → ファイル生成・chmod・status=applied・ログ追記
   │  reject → 候補削除（次週再検出で再提案）
   ▼ ④適用 [承認済みのみ自動実行]
~/bin/ 配下にスクリプト配置（guard-*.sh / check-*.sh / batch-*.sh 等）
```

**設計原則**: ①〜②は LLM の「気づき」に一切依存しない。④は人間の `apply` コマンド経由のみ。週次レポート（毎週日曜 9:00 cron）に ①〜③ の結果が自動表示され、承認待ちがある場合は案内が付く。

## 2. 検出トリガー定義（①・コード固定）

| ID | 条件 | 閾値 |
|----|------|------|
| T1 | 同一 terminal コマンド文字列 | 週 3 回以上（REP_THRESHOLD 環境変数で変更可） |
| T2 | 同一ファイルへの write_file/patch | 週 3 回以上 |
| T3 | 同一 URL への browser_navigate | 週 3 回以上 |
| T4 | 単一ツールの集中率 | 週のツール実行の 40% 超（自動化対象外ツールは除外） |

## 3. 候補生成（②・ルールベース）

検出結果の種類ごとに、実行可能な雛形を自動生成する:

| 候補タイプ | 由来 | 生成物 | 例 |
|-----------|------|--------|-----|
| C1-script-wrapper | T1 コマンド繰り返し | コマンドをラップする `~/bin/<slug>.sh` | 同一コマンド×9 → スクリプト化 |
| C2-file-guard | T2 ファイル編集繰り返し | 編集前スナップショットを取る `~/bin/guard-<slug>.sh` | 週27回編集 → スナップショット |
| C3-url-monitor | T3 URL 訪問繰り返し | 到達性チェック `~/bin/check-<slug>.sh` | URL×19 → 監視スクリプト |
| C4-tool-batch | T4 ツール集中 | バッチ処理の雛形 `~/bin/batch-<slug>.sh` | terminal 50% → バッチ化 |

### フィルタ（自動化済み・調査用の除外）

自動生成される候補から、以下は除外する（**自動化済みの再ラップは無意味**）:
- `~/.hermes/scripts/` 配下のスクリプト実行（仕組み化済み）
- `~/devops/update-deps.sh` 等の既存仕組み
- デバッグ用ワンライナー（`echo "==="`, `head -N`, `tail -N`, `--dry-run`, `.schema`, `.tables`, `wc -l`, `grep -vE`, `2>&1 |` 等）
- 既存候補と同一 ID（sha1(trigger|kind|target) の先頭10文字）は再生成しない

### リスク判定

- `DANGEROUS` パターン（`rm -rf`, `sudo`, `curl|sh`, `mkfs`, `dd of=` 等）に一致 → `risk: high`
- high の候補は承認一覧で 🟥 表示され、事前確認を促す

## 4. 承認ゲート（③・人間専用）

```bash
~/.hermes/scripts/patch-approve.sh list    # pending 一覧（🟥=high risk, 🟦=low）
~/.hermes/scripts/patch-approve.sh show <id>  # 適用内容の事前確認（内容全文表示）
~/.hermes/scripts/patch-approve.sh apply <id> # 承認して適用（唯一の適用経路）
~/.hermes/scripts/patch-approve.sh reject <id> # 却下（候補削除 → 次週再提案）
```

- **apply できるのは status=pending のみ**（applied/rejected は拒否）
- apply は「ファイル生成→chmod 755→status=applied→.applied.log 追記」を実行
- テスト時は `PATCH_QUEUE_DIR` 環境変数でキューを差し替え可能（本番キュー汚染防止）
- **LLM が apply を呼ぶのは人間の指示に従った場合のみ**（cron は①〜②まで。④は自動実行しない）

## 5. 週次レポート統合

`hermes-tools-check.sh` の #12（検出）・#13（候補生成＋承認案内）として cron に組み込み済み:

```
🔁 繰り返し検出（閾値: 週3回以上）— 自動化提案候補
  • 同一コマンド ×9: `...`
  ...
🧩 パッチ候補: 新規なし（既存候補がある or 検出なし）
  → 承認: `~/.hermes/scripts/patch-approve.sh list` で一覧 → `apply <id>`
```

## 6. 検証結果（2026-08-02・実データ）

| 検証項目 | 結果 |
|---------|------|
| 検出器 JSON 出力 | ✅ 実データ 26 件検出（T1〜T4） |
| フィルタ単体テスト | ✅ 9/9 PASS（調査コマンド除外・通常コマンド保持） |
| 候補生成ロジック | ✅ 5/5 PASS（.sh 二重拡張子修正・risk 判定含む） |
| apply 実動 | ✅ ファイル生成・chmod・status=applied・ログ追記 |
| reject 実動 | ✅ 候補削除・次週再提案 |
| 二重適用ガード | ✅ applied は apply 拒否 |
| キュー汚染防止 | ✅ PATCH_QUEUE_DIR 差し替えで実キュー非汚染を確認 |
| 週次レポート統合 | ✅ 承認案内表示確認（head 40→70 に拡張） |

実データから生成された候補 16 件は `~/.hermes/patch-queue/` に pending で保持中（本設計書の実証サンプル）。

## 7. 既知の制約と今後の拡張

- **C4-tool-batch は雛形のみ**（中身は承認時に具体化が必要）— ツール集中の「何をバッチ化するか」は機械的に推定できないため
- C2-file-guard は毎回手動実行が必要 — cron 登録は承認時に人間が判断
- 適用は create-file タイプのみ実装（apply-script は拡張予約）
- 検出対象は state.db の tool_calls に依存 — Hermes セッションログがなければ動作しない

## 8. ファイル一覧

| ファイル | 役割 |
|---------|------|
| `~/.hermes/scripts/repetition-detector.py` | ①検出（T1〜T4・--json 対応） |
| `~/.hermes/scripts/patch-candidate-generator.py` | ②候補生成（ルールベース・フィルタ付き） |
| `~/.hermes/scripts/patch-approve.sh` | ③④承認＋適用（人間専用） |
| `~/.hermes/scripts/hermes-tools-check.sh` | 週次レポート（#12 検出・#13 候補生成統合） |
| `~/.hermes/patch-queue/` | 候補キュー（pending/applied JSON + .applied.log） |
