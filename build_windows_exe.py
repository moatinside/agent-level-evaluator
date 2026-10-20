#!/usr/bin/env python3
##############################################################################
# Build script: Create agent-level-evaluator.exe for Windows
# Requires: PyInstaller
##############################################################################

import subprocess
import sys
from pathlib import Path

REPO_DIR = Path(__file__).parent
DIST_DIR = REPO_DIR / "dist"
BUILD_DIR = REPO_DIR / "build"

print("=" * 80)
print("🔨 Building agent-level-evaluator.exe for Windows")
print("=" * 80)
print("")

# Step 1: Clean previous builds
print("📌 Step 1: Clean previous builds...")
subprocess.run(["rm", "-rf", str(BUILD_DIR)], check=False)
subprocess.run(["rm", "-rf", str(DIST_DIR)], check=False)
print("   ✅ Cleaned")

# Step 2: Create entry point script
print("")
print("📌 Step 2: Create entry point script...")
entry_point = REPO_DIR / "agent_level_evaluator_main.py"

entry_point.write_text("""#!/usr/bin/env python3
'''
agent-level-evaluator Windows entry point
Runs as systemd service replacement (Windows Task Scheduler)
'''

import sys
from pathlib import Path

# Add repo to path
repo_path = Path(__file__).parent
sys.path.insert(0, str(repo_path))

# Import and run evaluator
from evals.run_evals import main

if __name__ == "__main__":
    main()
""")
print("   ✅ Entry point created")

# Step 3: Run PyInstaller
print("")
print("📌 Step 3: Building executable with PyInstaller...")
print("   This may take 1-2 minutes...")

cmd = [
    "pyinstaller",
    "--onefile",  # Single executable file
    "--name", "agent-level-evaluator",
    "--console",  # Show console window
    "--add-data", f"{REPO_DIR / 'evals'}:evals",
    "--add-data", f"{REPO_DIR / 'scripts'}:scripts",
    "--add-data", f"{REPO_DIR / 'schemas'}:schemas",
    "--collect-all", "pytest",
    "--hidden-import=evals.run_evals",
    "--hidden-import=scripts",
    str(entry_point),
]

result = subprocess.run(cmd, cwd=str(REPO_DIR))

if result.returncode != 0:
    print("❌ Build failed")
    sys.exit(1)

# Step 4: Verify build
print("")
print("📌 Step 4: Verify build...")
exe_path = DIST_DIR / "agent-level-evaluator.exe"

if exe_path.exists():
    size_mb = exe_path.stat().st_size / (1024 * 1024)
    print(f"   ✅ Build successful!")
    print(f"   📦 File: {exe_path}")
    print(f"   📊 Size: {size_mb:.1f} MB")
else:
    print("❌ Executable not found")
    sys.exit(1)

# Step 5: Create version info
print("")
print("📌 Step 5: Create version info...")
version_file = DIST_DIR / "VERSION.txt"
version_file.write_text(f"""agent-level-evaluator Windows Edition
Version: 1.0.0
Build Date: $(date)
Platform: Windows x64
Python: 3.9+

Executable: agent-level-evaluator.exe
Setup: See README_WINDOWS.md
""")

print("=" * 80)
print("✅ Build Complete!")
print("=" * 80)
print("")
print("📦 Distribution Package:")
print(f"   Executable: {exe_path}")
print(f"   Size: {size_mb:.1f} MB")
print("")
print("🚀 Next Steps:")
print("   1. Copy agent-level-evaluator.exe to Windows machine")
print("   2. Run: setup_windows_service.ps1")
print("   3. Service starts automatically")
print("")
print("📝 See: docs/README_WINDOWS.md for complete guide")
print("")
