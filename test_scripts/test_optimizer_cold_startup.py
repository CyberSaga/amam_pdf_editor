from __future__ import annotations

from pathlib import Path
import subprocess
import sys


def test_importing_optimizer_does_not_load_process_executor():
    script = "import sys; import model.pdf_optimizer; assert 'concurrent.futures.process' not in sys.modules"
    result = subprocess.run([sys.executable, '-c', script], cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
