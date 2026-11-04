"""Switch the View's plan-preview token gate off in a test.

``TEXT_COMMIT_PREVIEW=legacy`` was the suite's lever for "no plan preview, the
inline Apply commits without a token, the editor draws the CSS interim frame"
(``plans/retire-legacy-engine-option.md``, slice 2).  The setting is retired
(``TextCommitSettings.preview`` accepts only ``"plan"``); the lever left is the
view-level flag ``PDFView.set_text_plan_preview_required``.

``tokenless_view(view)`` clears that flag.  ORDER MATTERS:
``PDFController.activate()`` sets the flag from the settings (always True now),
so the helper must run AFTER ``activate()`` -- and again after anything in a
test that re-activates the controller (a second ``activate()``, a tab/session
rebuild that wires a fresh view).  Called before ``activate()`` it is silently
overwritten and the test would run in plan mode while believing it does not.
"""
from __future__ import annotations

from typing import Any


def tokenless_view(view: Any) -> Any:
    """Turn the plan-preview token gate off on ``view`` and return the view."""
    view.set_text_plan_preview_required(False)
    assert getattr(view, "_text_plan_preview_required", None) is False
    return view
