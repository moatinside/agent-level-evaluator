# 🚀 段階3: Canary Deployment ガイド

## 概要

Mac mini上で、古いバージョン（stable）と新しいバージョン（canary）を**プロセスレベルで並行実行**し、トラフィックを 95:5 に分割する戦略です。

```
┌──────────────────────────────────────────────────────┐
│  Mac mini (単一ホスト)                                 │
├──────────────────────────────────────────────────────┤
│                                                       │
│  Port 8000: Old version (stable)  - 95% traffic      │
│  Port 8001: New version (canary)  - 5% traffic       │
│                                                       │
│  ↓↓↓                                                  │
│  nginx Load Balancer (weight-based routing)           │
│  ↓↓↓                                                  │
│  External clients                                     │
│                                                       │
└──────────────────────────────────────────────────────┘
```

---

## 📋 前提条件

- [ ] nginx がインストールされている
- [ ] Python 3.9+ が利用可能
- [ ] `jq` がインストールされている（rollback用）
- [ ] `curl` がインストールされている
- [ ] Git リポジトリの変更が commit 済み

---

## 🚀 実行ステップ

### Step 1: 最新コードをコミット＆push

```bash
cd /Users/yokapro/Developer/agent-level-evaluator-upstream

# 確認
git status
git log --oneline -5

# Push to GitHub
git push origin main
```

### Step 2: Canary デプロイ開始

```bash
# スクリプトに実行権限をつける
chmod +x scripts/canary_deploy.sh
chmod +x scripts/canary_rollback.sh
chmod +x scripts/canary_monitor.py

# Canary デプロイ実行
bash scripts/canary_deploy.sh
```

**出力例：**
```
============================================================================
✅ Canary Deployment Started Successfully!
============================================================================

📊 Deployment Summary:
   Old (stable):   439eb5e on port 8000 (PID: 12345) - 95% traffic
   New (canary):   86b489c on port 8001 (PID: 12346) - 5% traffic

📋 Next Steps:
   1. Monitor logs: tail -f /tmp/canary-deploy/{old_version,new_version}.log
   2. Check health: curl http://127.0.0.1:8000/health && curl http://127.0.0.1:8001/health
   3. Test nginx: curl http://127.0.0.1:8080/api/test
   4. After 24h: Review logs and decide whether to promote or rollback
```

---

### Step 3: リアルタイム監視（24時間）

```bash
# ダッシュボードで監視（10秒ごとに更新）
python3 scripts/canary_monitor.py
```

**ダッシュボード例：**
```
================================================================================
🎯 Canary Deployment Monitoring Dashboard
================================================================================

📅 Time: 2026-10-20 16:45:30
📍 Log directory: /tmp/canary-deploy

================================================================================
📊 Process Health
================================================================================
✅ OLD      | PID: 12345  | Port: 8000
✅ NEW      | PID: 12346  | Port: 8001

================================================================================
🌐 HTTP Health Check
================================================================================
✅ OLD      | Status: 200
✅ NEW      | Status: 200

================================================================================
⚠️  Error Analysis
================================================================================
   OLD version errors: 0      (stable)
   NEW version errors: 0      (canary) - rate: 0.00%

================================================================================
🚦 Traffic Distribution (last 100 requests)
================================================================================
   OLD → 95.0% (95 requests)
   NEW →  5.0% (5 requests)
   Expected split: 95:5 | Actual: 95:5
```

---

### Step 4: ログ確認

```bash
# 実時間でログを監視
tail -f /tmp/canary-deploy/old_version.log
tail -f /tmp/canary-deploy/new_version.log

# アクセスログ確認
tail -f /tmp/canary-deploy/access_canary.log
```

---

### Step 5: テスト（オプション）

```bash
# health check
curl -v http://127.0.0.1:8000/health
curl -v http://127.0.0.1:8001/health

# サンプル リクエスト（トラフィック分散テスト）
for i in {1..100}; do
  curl http://127.0.0.1:8080/api/test
done

# アクセスログで分散確認
grep ":8001" /tmp/canary-deploy/access_canary.log | wc -l  # Should be ~5
grep ":8000" /tmp/canary-deploy/access_canary.log | wc -l  # Should be ~95
```

---

## ✅ 監視期間（24時間）チェックリスト

| 時間 | 確認項目 | 状態 |
|------|---------|------|
| **初期（1h）** | 両プロセス起動確認 | ☐ |
| **初期（1h）** | HTTP health check 確認 | ☐ |
| **初期（1h）** | トラフィック分散 95:5 確認 | ☐ |
| **継続（4h毎）** | ERROR ログ確認（許容: <50） | ☐ |
| **継続（4h毎）** | Response latency 確認（target: <500ms） | ☐ |
| **継続（4h毎）** | Backward compat issues 確認 | ☐ |
| **24h後** | 総合判定（PASS/FAIL） | ☐ |

---

## 🔄 緊急対応：Rollback

**問題が検出された場合、すぐに rollback：**

```bash
bash scripts/canary_rollback.sh
```

**自動実行されること：**
- 新バージョン（canary）プロセスを kill
- 旧バージョン（stable）をそのまま運用継続
- Git状態を元に戻す
- ログをアーカイブ

---

## 📊 24時間後の判定基準

### ✅ PASS（新バージョンに昇格）

```
条件:
  ✓ Error rate < 0.5%
  ✓ Response latency < 500ms
  ✓ Backward compat issues = 0
  ✓ No process crashes
  ✓ Traffic distribution 正確（95:5 ± 2%）
```

**次ステップ：**
```bash
# 新バージョンを stable に昇格
git tag v1.0-canary-promoted-20261020
git push origin main --tags

# 旧バージョンを廃止
# Port 8000 の service を停止
kill <OLD_PID>

# Port 8001 を本番ポート（例：8080）に変更
```

---

### ❌ FAIL（Rollback 実施）

```
条件:
  ✗ Error rate ≥ 0.5%
  ✗ Response latency ≥ 500ms
  ✗ Backward compat issues > 0
  ✗ Process crashes 発生
  ✗ Traffic split anomaly
```

**次ステップ：**
```bash
# Rollback 実行
bash scripts/canary_rollback.sh

# 失敗原因分析
less /tmp/canary-deploy/archive_*/new_version.log

# コード修正 → 再度 Canary 実施
```

---

## 📂 ファイル構成

```
/tmp/canary-deploy/
├── deployment_info.json          # デプロイメタデータ
├── old_version.log               # 旧バージョン ログ
├── new_version.log               # 新バージョン ログ
├── access_canary.log             # nginx アクセスログ
├── nginx_canary.conf             # nginx 設定ファイル
├── monitor.sh                    # 監視スクリプト
├── rollback.sh                   # Rollback スクリプト
└── archive_<timestamp>/          # ログアーカイブ
    ├── old_version.log
    ├── new_version.log
    ├── access_canary.log
    └── deployment_info.json
```

---

## 💡 トラブルシューティング

### Q: 新バージョンが起動しない

```bash
# ログ確認
tail -100 /tmp/canary-deploy/new_version.log

# ポート競合確認
lsof -i :8001

# 手動起動テスト
cd /Users/yokapro/Developer/agent-level-evaluator-upstream
git checkout 86b489c
python3 -m agent_level_evaluator.server --port 8001 --log-file /tmp/test.log
```

### Q: トラフィック分散が 95:5 でない

```bash
# nginx ログ確認
tail -50 /tmp/canary-deploy/access_canary.log | grep -E ":8000|:8001"

# nginx config 確認
cat /tmp/canary-deploy/nginx_canary.conf

# nginx reload
sudo nginx -t
sudo nginx -s reload
```

### Q: 旧バージョン側でエラーが増加している

```bash
# 旧バージョン ログ詳細確認
tail -200 /tmp/canary-deploy/old_version.log

# Rollback 検討（新バージョンが原因でない場合）
bash scripts/canary_rollback.sh
```

---

## 🎯 まとめ

| ステップ | 実行 | 時間 | 成果 |
|---------|------|------|------|
| Step 1 | git push | 1分 | コード本番環境へ |
| Step 2 | canary_deploy.sh | 2分 | 両バージョン起動 |
| Step 3 | canary_monitor.py | 継続 | リアルタイム監視 |
| Step 4-5 | ログ確認・テスト | 継続 | 品質確認 |
| 24h後 | PASS/FAIL 判定 | 5分 | 昇格 or Rollback |

---

**本番 Canary デプロイ、頑張ってください！** 🚀
