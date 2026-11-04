"""Force the consented rebuild in a test, and prove it ran.

The retired legacy engine option used to be the suite's lever for "run
``_apply_redact_insert``" (``plans/retire-legacy-engine-option.md``).  These
helpers replace it with the shipped route: the tiered engine refuses, the
request carries the explicit rebuild consent, and the consented rebuild runs
with every gate users get (``rebuild_paint``, the glyph-loss acknowledgement,
``_verify_rebuild_edit``).

- ``force_rebuild(monkeypatch)`` (FR) makes ``_attempt_tiered_commit`` refuse
  with ``MULTI_SPAN_TARGET`` so an ordinary fixture reaches the consent branch.
  FR only forces the refusal: the consent must still come from the request
  (``allow_rebuild=True`` plus an accepting ``confirm_fallback``), or the edit
  returns ``REJECTED``.
- ``forced_rebuild()`` is the same patch as a context manager, for tests that
  do not take ``monkeypatch``.
- ``assert_rebuild_ran(model)`` (RAN) asserts that the last commit really was
  the consented rebuild, so a Tier 0/1 commit can never make a test that is
  named for the rebuild pass vacuously.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest import mock

from model.text_commit.dto import CommitTier, RejectReason

FORCED_REASON = RejectReason.MULTI_SPAN_TARGET


def _refusing_attempt(reason: str | None):
    def _attempt(*_args: Any, **_kwargs: Any) -> tuple[None, str | None]:
        return None, reason

    return _attempt


def force_rebuild(monkeypatch, reason: str | None = FORCED_REASON) -> None:
    """FR: every tiered attempt refuses with ``reason`` (zero mutation)."""
    import model.pdf_text_edit as pdf_text_edit

    monkeypatch.setattr(pdf_text_edit, "_attempt_tiered_commit", _refusing_attempt(reason))


@contextmanager
def forced_rebuild(reason: str | None = FORCED_REASON) -> Iterator[None]:
    """FR as a context manager."""
    import model.pdf_text_edit as pdf_text_edit

    with mock.patch.object(pdf_text_edit, "_attempt_tiered_commit", _refusing_attempt(reason)):
        yield


def accept_rebuild(_chain: tuple[str, ...]) -> bool:
    """An accepting ``confirm_fallback`` (a bare True acknowledges no glyph loss)."""
    return True


def assert_rebuild_ran(model) -> None:
    """RAN: the last commit was the consented rebuild, not a Tier 0/1 commit."""
    outcome = model.last_commit_outcome
    assert outcome is not None, "no commit outcome recorded"
    assert outcome.tier is CommitTier.TIER2_LEGACY, (outcome.tier, outcome.fallback_chain)
    assert outcome.fallback_chain, outcome
    assert outcome.fallback_chain[0].startswith("tier0:"), outcome.fallback_chain
