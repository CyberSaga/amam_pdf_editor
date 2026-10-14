"""Part-5 Stage D1: the finalize policy as one exhaustive reason x state matrix.

Part 5's edge-matrix census (plans/true-text-ui-part5.md, Stage 0 item 4) found
that the finalize policy sets (keep / discard / close-always) are pinned one
reason at a time, so several cells of the matrix had no test of their own:
FOCUS_OUTSIDE x unverified, SCENE_REBUILD / SESSION_SWITCH / MODE_SWITCH x
{refused, empty, token}, every DISCARD reason x {unverified, refused, token}.
This file drives ``PDFView._finalize_text_edit(reason)`` for EVERY reason in
``TextEditFinalizeReason`` against the four input states a user can be in:

* ``empty``      the box is open and untouched;
* ``unverified`` typed text, the plan preview has not delivered a token yet;
* ``refused``    typed text the plan preview refuses (no token will ever come);
* ``token``      typed text with a verified preview token.

and asserts the outcome the policy sets promise -- keep reasons keep the
editor and the input and send nothing (or commit a verified token), discard
reasons discard and send nothing (the token is never sent), close-always
reasons commit a verified token and otherwise discard with a visible warning.
The composing (preedit) column lives in ``test_text_commit_finalize_policy.py``.

Real app (``main.run`` through the harness of
``test_text_commit_finalize_by_result.py``), synthetic documents, recorders
only; no PDF outside ``tmp_path`` is touched.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import view.text_editing as text_editing  # noqa: E402
from test_scripts.test_text_commit_finalize_by_result import (  # noqa: E402
    _EDIT_B,
    _App,
    _author,
    _original_texts,
)
from view.text_editing import TextEditFinalizeReason  # noqa: E402

_REFUSED_INPUT = "Pump Ro"  # shorter: needs Tier 1, so max_tier=0 refuses it
_STATES = ("empty", "unverified", "refused", "token")


@pytest.fixture
def launch(qapp, monkeypatch):
    apps: list[_App] = []

    def _launch(path: Path, **kwargs) -> _App:
        app = _App(monkeypatch, path, **kwargs)
        apps.append(app)
        return app

    yield _launch
    for app in apps:
        app.close()


def _policy(reason: TextEditFinalizeReason) -> str:
    if reason in text_editing._KEEP_EDITOR_REASONS:
        return "keep"
    if reason in text_editing._DISCARD_REASONS:
        return "discard"
    assert reason in text_editing._CLOSE_ALWAYS_REASONS, f"{reason} has no policy"
    return "close_always"


def _enter_state(app: _App, state: str):
    """Open "Pump Room" and bring the editor into ``state``; returns
    ``(editor, typed_text)``."""
    editor = app.open_editor("Pump Room")
    if state == "empty":
        assert editor.toPlainText() == "Pump Room"
        return editor, "Pump Room"
    if state == "unverified":
        app.type_replacing_all(editor, _EDIT_B)
        assert editor.toPlainText() == _EDIT_B
        assert editor.current_plan_token() is None, "the preview already landed"
        return editor, _EDIT_B
    if state == "refused":
        app.type_replacing_all(editor, _REFUSED_INPUT)
        assert app.wait(lambda: editor.plan_rejection_reason() is not None), "no preview refusal"
        app.pump(60)
        assert editor.current_plan_token() is None
        return editor, _REFUSED_INPUT
    assert state == "token"
    app.type_replacing_all(editor, _EDIT_B)
    app.wait_token(editor)
    return editor, _EDIT_B


@pytest.mark.parametrize("state", _STATES)
@pytest.mark.parametrize("reason", list(TextEditFinalizeReason), ids=lambda r: r.value)
def test_every_finalize_reason_x_input_state_follows_its_policy(
    tmp_path: Path, launch, reason: TextEditFinalizeReason, state: str
) -> None:
    app = launch(
        _author(tmp_path / f"{reason.value}_{state}.pdf"),
        preview="plan",
        max_tier="0" if state == "refused" else "1",
    )
    editor, typed = _enter_state(app, state)
    requests_before = len(app.requests)
    since = time.monotonic()

    result = app.view._finalize_text_edit(reason)
    app.pump(300)
    outcome = result.outcome.value
    policy = _policy(reason)
    sent = len(app.requests) - requests_before
    warnings = app.warnings_since(since)

    if policy == "discard":
        # An explicit user discard: never sent, the token is never used.
        assert outcome == "discarded", (reason, state, outcome)
        assert app.editor() is None and sent == 0 and app.commits == []
        assert app.page_texts() == _original_texts()
    elif state == "empty":
        # Untouched box: nothing to apply, nothing to lose.
        assert outcome == "no_op", (reason, state, outcome)
        assert app.editor() is None and sent == 0 and app.commits == []
        assert app.page_texts() == _original_texts()
    elif state == "token":
        # Verified edit: every non-discard reason commits it exactly once.
        assert outcome == "committed", (reason, state, outcome)
        assert app.editor() is None and sent == 1, (reason, sent)
        assert len(app.commits) == 1
        assert app.page_texts() != _original_texts()
    elif policy == "keep":
        # Un-applied input (no verified preview): kept, nothing sent.
        assert outcome == "refused", (reason, state, outcome)
        assert app.editor() is editor and editor.toPlainText() == typed
        assert sent == 0 and app.commits == []
        assert app.page_texts() == _original_texts()
    else:
        # Close-always with un-applied input: discarded, but never silently.
        assert outcome == "discarded", (reason, state, outcome)
        assert app.editor() is None and sent == 0 and app.commits == []
        assert any("已捨棄" in m for m in warnings), (reason, state, app.toasts)
        assert app.page_texts() == _original_texts()
    assert app.modals == [], (reason, state, app.modals)
