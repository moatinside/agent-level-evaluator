# PowerShell: Setup agent-level-evaluator on Windows
# Run as Administrator

param(
    [string]$ExePath = "$PSScriptRoot\agent-level-evaluator.exe",
    [string]$LogDir = "$env:APPDATA\agent-level-evaluator\logs",
    [int]$IntervalHours = 1
)

Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "🔧 Windows Setup: agent-level-evaluator Blue-Green Service" -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host ""

# Check Admin
$currentUser = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($currentUser)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "❌ This script must run as Administrator" -ForegroundColor Red
    Write-Host "   Right-click PowerShell → Run as Administrator" -ForegroundColor Yellow
    exit 1
}

# Step 1: Verify executable
Write-Host "📌 Step 1: Verify executable..." -ForegroundColor Cyan
if (-not (Test-Path $ExePath)) {
    Write-Host "❌ Executable not found: $ExePath" -ForegroundColor Red
    exit 1
}
Write-Host "   ✅ Found: $ExePath" -ForegroundColor Green

# Step 2: Create log directory
Write-Host ""
Write-Host "📌 Step 2: Create log directory..." -ForegroundColor Cyan
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
Write-Host "   ✅ Created: $LogDir" -ForegroundColor Green

# Step 3: Create Blue service (Task Scheduler)
Write-Host ""
Write-Host "📌 Step 3: Create Blue service (Task Scheduler)..." -ForegroundColor Cyan

$taskNameBlue = "agent-level-evaluator-blue"
$taskDescBlue = "Agent Level Evaluator - Blue (Stable) Version"

# Remove if exists
Unregister-ScheduledTask -TaskName $taskNameBlue -Confirm:$false -ErrorAction SilentlyContinue

# Create trigger (repeat every $IntervalHours hours)
$trigger = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Hours $IntervalHours) -Once -At (Get-Date)

# Create action
$action = New-ScheduledTaskAction -Execute $ExePath -WorkingDirectory (Split-Path $ExePath) `
    -Argument "--version blue --log-dir `"$LogDir`""

# Create task
Register-ScheduledTask -TaskName $taskNameBlue -Trigger $trigger -Action $action `
    -Description $taskDescBlue -RunLevel Highest | Out-Null

Write-Host "   ✅ Created: $taskNameBlue" -ForegroundColor Green

# Step 4: Create Green service (Task Scheduler)
Write-Host ""
Write-Host "📌 Step 4: Create Green service (Task Scheduler)..." -ForegroundColor Cyan

$taskNameGreen = "agent-level-evaluator-green"
$taskDescGreen = "Agent Level Evaluator - Green (Candidate) Version"

# Remove if exists
Unregister-ScheduledTask -TaskName $taskNameGreen -Confirm:$false -ErrorAction SilentlyContinue

# Create trigger (same as Blue)
$triggerGreen = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Hours $IntervalHours) -Once -At (Get-Date)

# Create action
$actionGreen = New-ScheduledTaskAction -Execute $ExePath -WorkingDirectory (Split-Path $ExePath) `
    -Argument "--version green --log-dir `"$LogDir`""

# Create task (but don't start it yet)
Register-ScheduledTask -TaskName $taskNameGreen -Trigger $triggerGreen -Action $actionGreen `
    -Description $taskDescGreen -RunLevel Highest | Out-Null

Write-Host "   ✅ Created: $taskNameGreen" -ForegroundColor Green

# Step 5: Start Blue service
Write-Host ""
Write-Host "📌 Step 5: Start Blue service..." -ForegroundColor Cyan
Start-ScheduledTask -TaskName $taskNameBlue
Write-Host "   ✅ Started: $taskNameBlue" -ForegroundColor Green

# Step 6: Verify tasks
Write-Host ""
Write-Host "📌 Step 6: Verify tasks..." -ForegroundColor Cyan
$tasks = Get-ScheduledTask | Where-Object { $_.TaskName -like "*agent-level*" }
$tasks | ForEach-Object {
    $status = if ((Get-ScheduledTaskInfo -TaskName $_.TaskName).LastTaskResult -eq 0) { "✅" } else { "⏳" }
    Write-Host "   $status $($_.TaskName)" -ForegroundColor Green
}

Write-Host ""
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "✅ Setup Complete!" -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "📊 Configuration:" -ForegroundColor Cyan
Write-Host "   Blue Service: $taskNameBlue" -ForegroundColor White
Write-Host "   Green Service: $taskNameGreen (standby)" -ForegroundColor White
Write-Host "   Log Directory: $LogDir" -ForegroundColor White
Write-Host "   Interval: Every $IntervalHours hour(s)" -ForegroundColor White
Write-Host ""
Write-Host "📝 Next Steps:" -ForegroundColor Cyan
Write-Host "   1. Check logs: Get-Content `"$LogDir\blue_evaluator.log`"" -ForegroundColor White
Write-Host "   2. Monitor tasks: taskschd.msc" -ForegroundColor White
Write-Host "   3. After 24h: Promote Green or keep Blue" -ForegroundColor White
Write-Host ""
Write-Host "💡 Commands:" -ForegroundColor Cyan
Write-Host "   Start Blue:   Start-ScheduledTask -TaskName `"$taskNameBlue`"" -ForegroundColor White
Write-Host "   Stop Blue:    Stop-ScheduledTask -TaskName `"$taskNameBlue`"" -ForegroundColor White
Write-Host "   Start Green:  Start-ScheduledTask -TaskName `"$taskNameGreen`"" -ForegroundColor White
Write-Host "   View tasks:   taskschd.msc" -ForegroundColor White
Write-Host ""
