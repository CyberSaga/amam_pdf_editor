from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Modules the pre-show path (``import view.pdf_view``, as main.run does without a CLI
# file) must NOT pull in: none is needed for the first sharp paint (plans/app-performance-v2.md M6).
DEFERRED = (
    "model.edit_commands",
    "model.text_commit.inspect",
    "utils.cjk_ext_b_font",
    "view.ext_b_subset_worker",
)

_PROBE = (
    "import json, sys\n"
    "import view.pdf_view\n"
    f"print(json.dumps([m for m in {DEFERRED!r} if m in sys.modules]))\n"
)


def _loaded_after_view_import() -> list[str]:
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_pre_show_import_skips_text_commit_modules():
    assert _loaded_after_view_import() == []


def test_lazy_edit_text_result_reexport_still_resolves():
    from model.edit_commands import EditTextResult as model_result
    from view.pdf_view import EditTextResult as view_result
    from view.text_editing import EditTextResult as te_result

    assert view_result is model_result
    assert te_result is model_result
