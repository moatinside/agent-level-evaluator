#!/usr/bin/env python3
##############################################################################
# Canary Monitoring Dashboard - Real-time monitoring for Canary deployment
##############################################################################

import json
import subprocess
import time
import sys
from datetime import datetime, timedelta
from pathlib import Path


class CanaryMonitor:
    def __init__(self, canary_log_dir="/tmp/canary-deploy"):
        self.canary_log_dir = Path(canary_log_dir)
        self.deployment_info_file = self.canary_log_dir / "deployment_info.json"
        self.old_log = self.canary_log_dir / "old_version.log"
        self.new_log = self.canary_log_dir / "new_version.log"
        self.access_log = self.canary_log_dir / "access_canary.log"
        
        self.load_deployment_info()
    
    def load_deployment_info(self):
        """Load deployment info from JSON."""
        if not self.deployment_info_file.exists():
            print("❌ Deployment info not found")
            sys.exit(1)
        
        with self.deployment_info_file.open() as f:
            self.info = json.load(f)
    
    def check_process_health(self):
        """Check if both processes are running."""
        old_pid = self.info['old_pid']
        new_pid = self.info['new_pid']
        
        old_running = self._is_process_running(old_pid)
        new_running = self._is_process_running(new_pid)
        
        return {
            'old': {'pid': old_pid, 'running': old_running, 'port': self.info['old_port']},
            'new': {'pid': new_pid, 'running': new_running, 'port': self.info['new_port']},
        }
    
    def _is_process_running(self, pid):
        """Check if a process is running."""
        try:
            result = subprocess.run(['ps', '-p', str(pid)], capture_output=True, text=True)
            return result.returncode == 0
        except:
            return False
    
    def check_http_health(self):
        """Check HTTP health endpoints."""
        old_port = self.info['old_port']
        new_port = self.info['new_port']
        
        old_health = self._check_endpoint(f"http://127.0.0.1:{old_port}/health")
        new_health = self._check_endpoint(f"http://127.0.0.1:{new_port}/health")
        
        return {
            'old': old_health,
            'new': new_health,
        }
    
    def _check_endpoint(self, url):
        """Check if endpoint is responding."""
        try:
            result = subprocess.run(
                ['curl', '-s', '-o', '/dev/null', '-w', '%{http_code}', url],
                capture_output=True, text=True, timeout=2
            )
            status_code = result.stdout.strip()
            return {'status': status_code, 'ok': status_code == '200'}
        except Exception as e:
            return {'status': 'ERROR', 'ok': False, 'error': str(e)}
    
    def check_log_errors(self):
        """Count errors in both version logs."""
        old_errors = self._count_errors(self.old_log)
        new_errors = self._count_errors(self.new_log)
        
        return {
            'old': old_errors,
            'new': new_errors,
            'new_error_rate': (new_errors / max(1, new_errors + 100)) * 100,  # Rough estimate
        }
    
    def _count_errors(self, log_file):
        """Count ERROR lines in log file."""
        if not log_file.exists():
            return 0
        try:
            result = subprocess.run(['grep', '-c', 'ERROR', str(log_file)],
                                  capture_output=True, text=True)
            return int(result.stdout.strip()) if result.stdout.strip() else 0
        except:
            return 0
    
    def check_traffic_split(self):
        """Analyze traffic distribution from access log."""
        if not self.access_log.exists():
            return {'old': 0, 'new': 0, 'split': 'N/A'}
        
        try:
            result = subprocess.run(['tail', '-100', str(self.access_log)],
                                  capture_output=True, text=True)
            lines = result.stdout.strip().split('\n')
            
            old_count = sum(1 for line in lines if ':8000' in line or 'old' in line.lower())
            new_count = sum(1 for line in lines if ':8001' in line or 'new' in line.lower())
            
            total = old_count + new_count
            if total == 0:
                return {'old': 0, 'new': 0, 'split': '0:0'}
            
            old_pct = (old_count / total) * 100
            new_pct = (new_count / total) * 100
            
            return {
                'old_count': old_count,
                'new_count': new_count,
                'old_pct': f"{old_pct:.1f}%",
                'new_pct': f"{new_pct:.1f}%",
                'split': f"{old_pct:.0f}:{new_pct:.0f}"
            }
        except:
            return {'error': 'Failed to parse access log'}
    
    def print_dashboard(self):
        """Print monitoring dashboard."""
        print("\033[2J\033[H")  # Clear screen
        
        print("=" * 80)
        print("🎯 Canary Deployment Monitoring Dashboard")
        print("=" * 80)
        print(f"\n📅 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"📍 Log directory: {self.canary_log_dir}")
        
        # Process health
        print("\n" + "=" * 80)
        print("📊 Process Health")
        print("=" * 80)
        
        proc_health = self.check_process_health()
        for version in ['old', 'new']:
            status = '✅' if proc_health[version]['running'] else '❌'
            print(f"{status} {version.upper():8} | PID: {proc_health[version]['pid']:<6} | "
                  f"Port: {proc_health[version]['port']}")
        
        # HTTP health
        print("\n" + "=" * 80)
        print("🌐 HTTP Health Check")
        print("=" * 80)
        
        http_health = self.check_http_health()
        for version in ['old', 'new']:
            status = '✅' if http_health[version]['ok'] else '❌'
            print(f"{status} {version.upper():8} | Status: {http_health[version]['status']}")
        
        # Error analysis
        print("\n" + "=" * 80)
        print("⚠️  Error Analysis")
        print("=" * 80)
        
        errors = self.check_log_errors()
        print(f"   OLD version errors: {errors['old']:<6} (stable)")
        print(f"   NEW version errors: {errors['new']:<6} (canary) - rate: {errors['new_error_rate']:.2f}%")
        
        if errors['new'] > 50:
            print("   🔴 ALERT: New version error count high - consider rollback!")
        
        # Traffic split
        print("\n" + "=" * 80)
        print("🚦 Traffic Distribution (last 100 requests)")
        print("=" * 80)
        
        traffic = self.check_traffic_split()
        if 'error' in traffic:
            print(f"   ⚠️  {traffic['error']}")
        else:
            print(f"   OLD → {traffic['old_pct']:>6} ({traffic['old_count']} requests)")
            print(f"   NEW → {traffic['new_pct']:>6} ({traffic['new_count']} requests)")
            print(f"   Expected split: 95:5 | Actual: {traffic['split']}")
        
        # Status summary
        print("\n" + "=" * 80)
        print("📋 Deployment Status")
        print("=" * 80)
        
        all_healthy = (proc_health['old']['running'] and proc_health['new']['running'] and
                      http_health['old']['ok'] and http_health['new']['ok'])
        
        if all_healthy:
            print("✅ All systems nominal - Canary deployment proceeding normally")
        else:
            print("❌ Issues detected - Review errors above")
        
        print("\n" + "=" * 80)
        print("💡 Commands")
        print("=" * 80)
        print(f"   Rollback:       bash {self.canary_log_dir}/rollback.sh")
        print(f"   View old logs:  tail -f {self.old_log}")
        print(f"   View new logs:  tail -f {self.new_log}")
        print(f"   Refresh (10s):  watch -n 10 'python3 canary_monitor.py'")
        print("")


if __name__ == "__main__":
    monitor = CanaryMonitor()
    
    try:
        while True:
            monitor.print_dashboard()
            time.sleep(10)  # Refresh every 10 seconds
    except KeyboardInterrupt:
        print("\n\n✅ Monitoring stopped")
        sys.exit(0)
