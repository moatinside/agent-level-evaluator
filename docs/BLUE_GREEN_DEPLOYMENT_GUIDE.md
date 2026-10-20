# 🚀 段階3 修正版: Blue-Green Deployment for macOS Service

## 概要

agent-level-evaluator を Mac mini の **バックグラウンドサービス化**し、**Blue-Green デプロイ**で段階的に新バージョンへ切り替える戦略。

```
┌──────────────────────────────────────────────────────┐
│  Mac mini (常時実行)                                 │
├──────────────────────────────────────────────────────┤
│                                                       │
│  🔵 Blue (Current Stable)                            │
│     - Stable version running                         │
│     - Port 9090 metrics                              │
│     - Log: /var/log/.../blue_evaluator.log          │
│                                                       │
│  🟢 Green (Candidate)                                │
│     - New version (standby)                          │
│     - Port 9091 metrics                              │
│     - Log: /var/log/.../green_evaluator.log         │
│                                                       │
│  ↓ monit or script で監視                            │
│                                                       │
│  24h後に、品質確認 → Green に切り替え                 │
│                                                       │
└──────────────────────────────────────────────────────┘
```

---

## 📋 実行ステップ

### **Step 1: Blue-Green 環境を構築**

```bash
chmod +x scripts/setup_blue_green.sh
bash scripts/setup_blue_green.sh
```

**出力例：**
```
✅ Blue-Green Setup Complete!

📊 Deployment Status:
   🔵 Blue (current active):  /opt/agent-level-evaluator/blue
   🟢 Green (standby):        /opt/agent-level-evaluator/green
```

**確認：**
```bash
# 両サービスが登録されているか確認
launchctl list | grep agent-level

# Blue のみ running
# Green は登録されているが未実行
```

---

### **Step 2: リアルタイム監視ダッシュボード起動**

```bash
python3 scripts/blue_green_monitor.py
```

**出力例：**
```
================================================================================
🔵🟢 Blue-Green Deployment Monitor
================================================================================

📊 Service Status
   Blue:  🔵 RUNNING
   Green: ⚪ STOPPED

   Active: BLUE

⚠️  Error Analysis
   Blue errors:  0
   Green errors: 0

🏥 Health Check
   🔵 Blue:  ✅ HEALTHY
   🟢 Green: ❌ STOPPED
```

---

### **Step 3: Green に新しいコミットをデプロイ**

```bash
# 現在の Blue コミット確認
cat /opt/agent-level-evaluator/blue/repo/.git/HEAD

# Green に新しいコミットをデプロイ
cd /opt/agent-level-evaluator/green/repo
git fetch origin
git checkout <新しいコミット>

# Green を起動テスト
# (次ステップで監視しながら実施)
```

---

### **Step 4: Green を起動して、24時間監視**

```bash
# Green を起動
python3 scripts/blue_green_monitor.py --load-green

# または 手動
launchctl load "$HOME/Library/LaunchAgents/com.local.agent-level-evaluator.green.plist"
```

**監視ポイント：**
```
✅ 確認項目（毎日/毎時チェック）

□ Green プロセスが継続稼働している
□ Green のエラーログが増加していない（< 50/日）
□ Blue のエラーログが増加していない（< 50/日）
□ ディスク使用量が正常（ログサイズ管理）
□ メモリ使用量が正常（< 512MB）
```

---

### **Step 5: 24時間後に判定 & 切り替え**

#### **✅ PASS: Green が安定している場合**

```bash
# Green に切り替え（昇格）
python3 scripts/blue_green_monitor.py --switch-green

# または 手動
launchctl unload "$HOME/Library/LaunchAgents/com.local.agent-level-evaluator.blue.plist"
launchctl load "$HOME/Library/LaunchAgents/com.local.agent-level-evaluator.green.plist"

# Blue を新しいスタンバイに更新（次の候補用）
# ... 次の new code を Blue へ
```

**結果：**
```
🟢 Green が新しい "stable" に
🔵 Blue が新しい "standby" に（update待ち）
```

#### **❌ FAIL: Green に問題がある場合**

```bash
# すぐに Blue に戻す（1秒以内に復旧）
python3 scripts/blue_green_monitor.py --switch-blue

# 原因分析
tail -200 /var/log/agent-level-evaluator/green_evaluator.log

# 修正 → 再度 Green へデプロイ
```

---

## 📊 コマンド早見表

| 操作 | コマンド |
|------|---------|
| **監視ダッシュボード起動** | `python3 scripts/blue_green_monitor.py` |
| **Blue ログ表示** | `tail -f /var/log/agent-level-evaluator/blue_evaluator.log` |
| **Green ログ表示** | `tail -f /var/log/agent-level-evaluator/green_evaluator.log` |
| **Green に切り替え** | `python3 scripts/blue_green_monitor.py --switch-green` |
| **Blue に戻す** | `python3 scripts/blue_green_monitor.py --switch-blue` |
| **サービス一覧確認** | `launchctl list \| grep agent-level` |
| **Blue 再起動** | `launchctl reload "$HOME/Library/LaunchAgents/com.local.agent-level-evaluator.blue.plist"` |
| **Green 再起動** | `launchctl reload "$HOME/Library/LaunchAgents/com.local.agent-level-evaluator.green.plist"` |

---

## 🔄 段階3: Blue-Green Canary フロー

```
Day 1 (朝)
  ↓
┌─────────────────────────────────────────────┐
│ Blue (current stable)                       │
│ ✅ Running | 📊 Metrics: port 9090          │
└─────────────────────────────────────────────┘
           ↓
      [Setup Green]
           ↓
┌─────────────────────────────────────────────┐
│ Blue: Running (primary)                     │
│ Green: Starting (candidate)                 │
│                                             │
│ 🔍 Monitoring: Both versions               │
└─────────────────────────────────────────────┘
           ↓
      [24h 監視]
           ↓
      Day 2 (朝)
           ↓
    ✅ Green OK?  →  🟢 Promote to Green
                      🔵 Blue → Standby
    
    ❌ Green NG?  →  Blue に即座に戻す
                      Green を修正
                      再度トライ
```

---

## ✅ 監視チェックリスト（24h）

| 時間 | チェック項目 | 状態 |
|------|----------|------|
| **初期（1h）** | Green 起動確認 | ☐ |
| **初期（1h）** | Green エラー数 = 0 | ☐ |
| **初期（1h）** | Blue 継続稼働 | ☐ |
| **4h毎** | エラーログ確認 | ☐ |
| **4h毎** | メモリ使用量 < 512MB | ☐ |
| **4h毎** | ディスク容量確認 | ☐ |
| **24h後** | 総合判定（PASS/FAIL） | ☐ |

---

## 🎯 まとめ

```
Option A 選択: Mac mini バックグラウンドサービス化

✅ 利点:
   - Hermes Agent 改造なし（独立運用）
   - 段階的なロールアウト可能（Blue-Green）
   - 即座なロールバック可能（1秒以内）
   - macOS native （launchd）で簡潔な管理

📅 実行スケジュール:
   Day 1 朝: Setup Blue-Green → Green 起動
   Day 2 朝: 品質確認 → Promote or Rollback
   
🚀 本番投入準備完了
```

---

**次ステップ：**

```
1. bash scripts/setup_blue_green.sh を実行
2. python3 scripts/blue_green_monitor.py で監視開始
3. 24h 期間中にエラー確認
4. Day 2 朝に昇格/ロールバック判定
```

**ユーザーが実行する準備はできましたか？**
