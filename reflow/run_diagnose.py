"""run_diagnose.py — 執行診斷腳本驗證 execute_reflow 修正效果"""
import subprocess, sys
result = subprocess.run(
    [sys.executable, "reflow/diagnose_position.py"],
    capture_output=True, text=True,
    cwd=r"<REPO>"
)
print(result.stdout)
if result.stderr:
    print("STDERR:", result.stderr[-3000:])
