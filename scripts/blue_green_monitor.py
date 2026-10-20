#!/usr/bin/env python3
##############################################################################
# Blue-Green Health Monitor & Auto-Switch
# Monitors both versions, detects issues, auto-switches if needed
##############################################################################

import json
import subprocess
import time
import sys
from datetime import datetime
from pathlib import Path


class BlueGreenMonitor:
    def __init__(self):
        self.log_dir = Path("/var/log/agent-level-evaluator")
        self.blue_log = self.log_dir / "blue_evaluator.log"
        self.green_log = self.log_dir / "green_evaluator.log"
        self.blue_plist = Path.home() / "Library/LaunchAgents/com.local.agent-level-evaluator.blue.plist"
        self.green_plist = Path.home() / "Library/LaunchAgents/com.local.agent-level-evaluator.green.plist"
    
    def get_service_status(self):
        """Get launchctl status for both services."""
        result = subprocess.run(
            ['launchctl', 'list'],
            capture_output=True, text=True
        )
        
        output = result.stdout
        blue_running = "com.local.agent-level-evaluator.blue" in output
        green_running = "com.local.agent-level-evaluator.green" in output
        
        return {
            'blue': {'running': blue_running},
            'green': {'running': green_running},
            'active': 'blue' if blue_running else 'green' if green_running else 'none'
        }
    
    def count_errors(self, log_file):
        """Count ERROR lines in log."""
        if not log_file.exists():
            return 0
        try:
            result = subprocess.run(
                ['grep', '-c', 'ERROR', str(log_file)],
                capture_output=True, text=True
            )
            return int(result.stdout.strip()) if result.stdout.strip() else 0
        except:
            return 0
    
    def get_log_tail(self, log_file, lines=5):
        """Get last N lines of log."""
        if not log_file.exists():
            return []
        try:
            result = subprocess.run(
                ['tail', '-n', str(lines), str(log_file)],
                capture_output=True, text=True
            )
            return result.stdout.strip().split('\n')
        except:
            return []
    
    def switch_to_green(self):
        """Switch active service from Blue to Green."""
        print("\n⚠️  Switching to Green version...")
        
        # Unload Blue
        subprocess.run(
            ['launchctl', 'unload', str(self.blue_plist)],
            capture_output=True
        )
        time.sleep(1)
        
        # Load Green
        subprocess.run(
            ['launchctl', 'load', str(self.green_plist)],
            capture_output=True
        )
        time.sleep(2)
        
        print("✅ Switched to Green version")
    
    def switch_to_blue(self):
        """Switch active service from Green to Blue."""
        print("\n⚠️  Switching to Blue version...")
        
        # Unload Green
        subprocess.run(
            ['launchctl', 'unload', str(self.green_plist)],
            capture_output=True
        )
        time.sleep(1)
        
        # Load Blue
        subprocess.run(
            ['launchctl', 'load', str(self.blue_plist)],
            capture_output=True
        )
        time.sleep(2)
        
        print("✅ Switched to Blue version")
    
    def print_dashboard(self):
        """Print monitoring dashboard."""
        print("\033[2J\033[H")  # Clear screen
        
        print("=" * 80)
        print("🔵🟢 Blue-Green Deployment Monitor")
        print("=" * 80)
        print(f"\n📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        
        # Service status
        status = self.get_service_status()
        print("=" * 80)
        print("📊 Service Status")
        print("=" * 80)
        
        blue_icon = "🔵 RUNNING" if status['blue']['running'] else "⚪ STOPPED"
        green_icon = "🟢 RUNNING" if status['green']['running'] else "⚪ STOPPED"
        
        print(f"   Blue:  {blue_icon}")
        print(f"   Green: {green_icon}")
        print(f"\n   Active: {status['active'].upper()}")
        
        # Error counts
        print("\n" + "=" * 80)
        print("⚠️  Error Analysis")
        print("=" * 80)
        
        blue_errors = self.count_errors(self.blue_log)
        green_errors = self.count_errors(self.green_log)
        
        print(f"   Blue errors:  {blue_errors}")
        print(f"   Green errors: {green_errors}")
        
        # Health check
        print("\n" + "=" * 80)
        print("🏥 Health Check")
        print("=" * 80)
        
        if status['blue']['running'] and blue_errors < 10:
            print("   🔵 Blue:  ✅ HEALTHY")
        elif status['blue']['running']:
            print(f"   🔵 Blue:  ⚠️  DEGRADED ({blue_errors} errors)")
        else:
            print("   🔵 Blue:  ❌ STOPPED")
        
        if status['green']['running'] and green_errors < 10:
            print("   🟢 Green: ✅ HEALTHY")
        elif status['green']['running']:
            print(f"   🟢 Green: ⚠️  DEGRADED ({green_errors} errors)")
        else:
            print("   🟢 Green: ❌ STOPPED")
        
        # Recent logs
        print("\n" + "=" * 80)
        print("📝 Recent Logs")
        print("=" * 80)
        
        if status['active'] == 'blue':
            print("\n   🔵 Blue (active):")
            for line in self.get_log_tail(self.blue_log, 3):
                print(f"      {line[:75]}")
        else:
            print("\n   🟢 Green (active):")
            for line in self.get_log_tail(self.green_log, 3):
                print(f"      {line[:75]}")
        
        # Auto-recovery check
        print("\n" + "=" * 80)
        print("🔄 Auto-Recovery Logic")
        print("=" * 80)
        
        if status['active'] == 'blue' and blue_errors > 50:
            print("   ❌ Blue has too many errors - Consider switch to Green")
        elif status['active'] == 'green' and green_errors > 50:
            print("   ❌ Green has too many errors - Consider switch to Blue")
        else:
            print("   ✅ No action needed")
        
        print("\n" + "=" * 80)
        print("💡 Commands")
        print("=" * 80)
        print("   Switch to Green:  python3 canary_monitor.py --switch-green")
        print("   Switch to Blue:   python3 canary_monitor.py --switch-blue")
        print("   View Blue logs:   tail -f /var/log/agent-level-evaluator/blue_evaluator.log")
        print("   View Green logs:  tail -f /var/log/agent-level-evaluator/green_evaluator.log")
        print("")


if __name__ == "__main__":
    monitor = BlueGreenMonitor()
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "--switch-green":
            monitor.switch_to_green()
            sys.exit(0)
        elif sys.argv[1] == "--switch-blue":
            monitor.switch_to_blue()
            sys.exit(0)
    
    try:
        while True:
            monitor.print_dashboard()
            time.sleep(10)
    except KeyboardInterrupt:
        print("\n\n✅ Monitoring stopped")
        sys.exit(0)
