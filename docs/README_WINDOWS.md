# 🚀 Windows セットアップガイド - agent-level-evaluator

## 概要

agent-level-evaluator を Windows マシンで **Blue-Green デプロイ** で実行します。

```
🔵 Blue:  Stable version (常時実行)
🟢 Green: Candidate version (待機中)
```

---

## 📋 前提条件

- Windows 10/11 （64-bit）
- Administrator 権限
- PowerShell 5.0+

---

## 🚀 セットアップ（3ステップ）

### **Step 1: executable をダウンロード**

GitHub Release ページから `agent-level-evaluator.exe` をダウンロード：

```
https://github.com/moatinside/agent-level-evaluator/releases
```

例：
```
C:\Program Files\agent-level-evaluator\agent-level-evaluator.exe
```

### **Step 2: PowerShell スクリプトを実行**

GitHub から `setup_windows_service.ps1` をダウンロード。

**PowerShell を管理者として実行** して：

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser -Force

cd C:\Program Files\agent-level-evaluator

.\setup_windows_service.ps1 -ExePath ".\agent-level-evaluator.exe"
```

**出力例：**
```
================================================================================
✅ Setup Complete!
================================================================================

📊 Configuration:
   Blue Service: agent-level-evaluator-blue
   Green Service: agent-level-evaluator-green (standby)
   Log Directory: C:\Users\<username>\AppData\Roaming\agent-level-evaluator\logs
   Interval: Every 1 hour(s)
```

### **Step 3: 自動実行確認**

```powershell
# Task Scheduler を開く
taskschd.msc

# または PowerShell で確認
Get-ScheduledTask | Where-Object { $_.TaskName -like "*agent-level*" }
```

---

## 📊 動作確認

### **ログ確認**

```powershell
# Blue ログ表示
Get-Content "$env:APPDATA\agent-level-evaluator\logs\blue_evaluator.log" -Tail 20

# または リアルタイム監視
Get-Content "$env:APPDATA\agent-level-evaluator\logs\blue_evaluator.log" -Wait
```

### **サービス状態確認**

```powershell
# Task Scheduler でタスク確認
taskschd.msc

# または PowerShell
Get-ScheduledTask -TaskName "*agent-level*" | Format-Table TaskName, State
```

---

## 🔄 Blue-Green 切り替え（24時間後）

### **Green に昇格（成功時）**

```powershell
# Blue を停止
Stop-ScheduledTask -TaskName "agent-level-evaluator-blue"

# Green を開始
Start-ScheduledTask -TaskName "agent-level-evaluator-green"

# 確認
Get-ScheduledTask -TaskName "*agent-level*" | Format-Table TaskName, State
```

### **Blue に戻す（問題時）**

```powershell
# Green を停止
Stop-ScheduledTask -TaskName "agent-level-evaluator-green"

# Blue を開始
Start-ScheduledTask -TaskName "agent-level-evaluator-blue"
```

---

## 📂 ディレクトリ構造

```
C:\Program Files\agent-level-evaluator\
├── agent-level-evaluator.exe      # メインプログラム
├── setup_windows_service.ps1      # セットアップスクリプト
└── README_WINDOWS.md              # このファイル

C:\Users\<username>\AppData\Roaming\agent-level-evaluator\
└── logs/
    ├── blue_evaluator.log         # Blue version ログ
    └── green_evaluator.log        # Green version ログ
```

---

## 🔧 トラブルシューティング

### **「実行ポリシーエラー」が出た**

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser -Force
```

### **「管理者権限が必要」と出た**

```
PowerShell を右クリック → 「管理者として実行」
```

### **タスクが実行されない**

```powershell
# タスクの詳細を確認
Get-ScheduledTask -TaskName "agent-level-evaluator-blue" | Get-ScheduledTaskInfo

# 手動で実行
Start-ScheduledTask -TaskName "agent-level-evaluator-blue"
```

### **ログが生成されない**

```powershell
# ログディレクトリ確認
$logDir = "$env:APPDATA\agent-level-evaluator\logs"
Test-Path $logDir

# ディレクトリが無い場合は作成
New-Item -ItemType Directory -Path $logDir -Force
```

---

## 📝 Command Reference

| 操作 | コマンド |
|------|---------|
| **Blue 開始** | `Start-ScheduledTask -TaskName "agent-level-evaluator-blue"` |
| **Blue 停止** | `Stop-ScheduledTask -TaskName "agent-level-evaluator-blue"` |
| **Green 開始** | `Start-ScheduledTask -TaskName "agent-level-evaluator-green"` |
| **Green 停止** | `Stop-ScheduledTask -TaskName "agent-level-evaluator-green"` |
| **タスク一覧** | `Get-ScheduledTask \| Where-Object { $_.TaskName -like "*agent-level*" }` |
| **ログ表示** | `Get-Content "$env:APPDATA\agent-level-evaluator\logs\blue_evaluator.log"` |
| **Task Scheduler** | `taskschd.msc` |

---

## 🎯 監視期間（24時間）

### **Day 1: Blue 実行中**
- 毎時間自動実行
- ログ自動記録
- エラー監視

### **Day 2: 昇格判定**

✅ 成功時: Green に切り替え  
❌ 問題時: Blue に戻す

---

## 💡 Mac mini 版との同期

GitHub main ブランチの最新コードが自動的に反映されます。

新バージョンを使用する場合：
1. GitHub Release から新 exe をダウンロード
2. 既存 exe を置き換え
3. Task Scheduler が自動的に新バージョンを実行

---

**サポート:** GitHub Issues で報告してください  
**ドキュメント:** https://github.com/moatinside/agent-level-evaluator/docs/

