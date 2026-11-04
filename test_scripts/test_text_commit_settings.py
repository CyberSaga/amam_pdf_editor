"""Red-light tests for the Qt-free text-commit settings DTO (Task 5)."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.pdf_model import PDFModel  # noqa: E402
from model.text_commit.dto import TextCommitSettings  # noqa: E402


def test_default_settings_are_the_acceptance_configuration():
    """PIN (critique step 12, 2026-10-02; supersedes the T16-3 pin of
    ``max_tier=0``/``preview="legacy"``): the shipped defaults are the
    configuration the fourteen real edits were accepted under -- the tiered
    engine with Tier 1, and the plan preview (Apply commits the verified
    preview by token).  Strict refusal stays off."""
    settings = TextCommitSettings()
    assert settings.engine == "tiered"
    assert settings.max_tier == 1
    assert settings.strict is False
    assert settings.preview == "plan"
    # Retired with the shadow engine (ruling O4).
    assert not hasattr(settings, "telemetry")
    # UI step 7 retired the T16-3 ``confirm_degrade`` opt-in: the consent
    # modal now hangs off the request's explicit rebuild consent
    # (``EditTextRequest.allow_rebuild``), never off a global setting.
    assert not hasattr(settings, "confirm_degrade")


def test_retired_engines_are_rejected_by_the_constructor():
    """RETIREMENT PIN (plans/retire-legacy-engine-option.md, ruling O6): the
    ``engine`` field accepts only ``"tiered"``.  Building a retired engine in
    code is a programming error and raises -- there is no second write path
    to ``_apply_redact_insert`` that skips the consent gate."""
    assert TextCommitSettings(engine="tiered").engine == "tiered"
    for retired in ("legacy", "shadow", "warp-speed"):
        with pytest.raises(ValueError, match=retired):
            TextCommitSettings(engine=retired)


@pytest.mark.parametrize("retired", ["legacy", "shadow"])
def test_a_stored_retired_engine_runs_tiered_with_a_warning(retired, caplog):
    """RETIREMENT PIN (ruling O5): a stored ``TEXT_COMMIT_ENGINE=legacy|shadow``
    never crashes the launch; it logs a warning that names the retired value
    and the user gets the tiered engine (the rebuild stays available per edit
    through 改用重建文字)."""
    with caplog.at_level(logging.WARNING, logger="model.text_commit.dto"):
        settings = TextCommitSettings.from_env({"TEXT_COMMIT_ENGINE": retired})
    assert settings == TextCommitSettings()
    assert settings.engine == "tiered"
    messages = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any(
        "TEXT_COMMIT_ENGINE" in m and repr(retired) in m and "retired" in m for m in messages
    ), messages


def test_telemetry_is_retired_and_its_variable_warns(caplog):
    """RETIREMENT PIN (ruling O4, amended by the owner 2026-11-04): ``telemetry``
    had one consumer, the retired shadow engine.  The field is gone and
    ``TEXT_COMMIT_TELEMETRY`` is never parsed, but a stored value is no longer
    swallowed silently: a warning names the variable and tells the user to
    remove it."""
    assert not hasattr(TextCommitSettings(), "telemetry")
    with pytest.raises(TypeError):
        TextCommitSettings(telemetry="local")  # type: ignore[call-arg]
    for value in ("local", "off", "cloud"):
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="model.text_commit.dto"):
            settings = TextCommitSettings.from_env({"TEXT_COMMIT_TELEMETRY": value})
        assert settings == TextCommitSettings()
        messages = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
        assert any(
            "TEXT_COMMIT_TELEMETRY" in m and "retired" in m and "remove" in m for m in messages
        ), messages
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="model.text_commit.dto"):
        TextCommitSettings.from_env({})
    assert not [r for r in caplog.records if "TEXT_COMMIT_TELEMETRY" in r.getMessage()]


def test_explicitly_stored_values_are_never_overridden_by_the_new_defaults():
    """GUARD (labelled; true before and after the flip).  Step 12 flips
    DEFAULTS only: a value the user stored (an environment variable is the
    only store these settings have) keeps its meaning -- except a retired
    engine, which falls back to tiered (see the retirement pins above)."""
    assert TextCommitSettings.from_env({"TEXT_COMMIT_MAX_TIER": "0"}).max_tier == 0
    stored = TextCommitSettings.from_env(
        {"TEXT_COMMIT_ENGINE": "legacy", "TEXT_COMMIT_PREVIEW": "plan"}
    )
    assert (stored.engine, stored.preview) == ("tiered", "plan")


def test_constructor_preview_default_is_the_plan_preview():
    """With one engine the preview default no longer follows the engine
    (retired with it): it is ``"plan"``.  An explicit ``preview`` argument
    is accepted only as ``"plan"`` (slice 2 retired ``"legacy"``), and an
    invalid stored preview falls back to ``"plan"``."""
    assert TextCommitSettings().preview == "plan"
    assert TextCommitSettings(engine="tiered").preview == "plan"
    assert TextCommitSettings(preview="plan").preview == "plan"
    assert TextCommitSettings.from_env({"TEXT_COMMIT_ENGINE": "tiered"}).preview == "plan"
    assert TextCommitSettings.from_env({"TEXT_COMMIT_PREVIEW": "hologram"}).preview == "plan"


def test_the_legacy_preview_is_rejected_by_the_constructor():
    """RETIREMENT PIN (plans/retire-legacy-engine-option.md, slice 2, ruling
    O3): ``preview`` accepts only ``"plan"``, the same treatment as ``engine``.
    The tokenless CSS preview lives on only as the view-level flag
    ``set_text_plan_preview_required`` (the test lever)."""
    assert TextCommitSettings(preview="plan").preview == "plan"
    for retired in ("legacy", "hologram"):
        with pytest.raises(ValueError, match=retired):
            TextCommitSettings(preview=retired)


def test_a_stored_legacy_preview_runs_the_plan_preview_with_a_warning(caplog):
    """RETIREMENT PIN (slice 2): a stored ``TEXT_COMMIT_PREVIEW=legacy`` never
    crashes the launch; it logs a warning that names the retired value and the
    user gets the plan preview (Apply commits the verified preview by token;
    the rebuild stays available per edit through 改用重建文字)."""
    with caplog.at_level(logging.WARNING, logger="model.text_commit.dto"):
        settings = TextCommitSettings.from_env({"TEXT_COMMIT_PREVIEW": "legacy"})
    assert settings == TextCommitSettings()
    assert settings.preview == "plan"
    messages = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any(
        "TEXT_COMMIT_PREVIEW" in m and repr("legacy") in m and "retired" in m for m in messages
    ), messages


def test_engine_and_preview_constructor_defaults_match_the_shipped_tier():
    """The function-level ``max_tier`` defaults move with the DTO (critique
    step 12) so a caller that omits it gets the shipped tier, not Tier 0."""
    import inspect as pyinspect

    from model.text_commit.engine import TieredCommitEngine
    from model.text_commit.preview import PreviewSessionInput, open_preview_session

    shipped = TextCommitSettings().max_tier
    assert shipped == 1
    assert pyinspect.signature(TieredCommitEngine.__init__).parameters["max_tier"].default == shipped
    assert pyinspect.signature(open_preview_session).parameters["max_tier"].default == shipped
    assert PreviewSessionInput.__dataclass_fields__["max_tier"].default == shipped


def test_from_env_parses_valid_values():
    settings = TextCommitSettings.from_env(
        {
            "TEXT_COMMIT_ENGINE": "tiered",
            "TEXT_COMMIT_MAX_TIER": "0",
            "TEXT_COMMIT_STRICT": "1",
            "TEXT_COMMIT_PREVIEW": "plan",
            "TEXT_COMMIT_CONFIRM_DEGRADE": "1",
        }
    )
    assert settings.engine == "tiered"
    assert settings.max_tier == 0
    assert settings.strict is True
    assert settings.preview == "plan"
    # Retired in UI step 7: the variable is ignored, never parsed.
    assert not hasattr(settings, "confirm_degrade")


def test_from_env_invalid_values_fall_back_to_defaults():
    settings = TextCommitSettings.from_env(
        {
            "TEXT_COMMIT_ENGINE": "warp-speed",
            "TEXT_COMMIT_MAX_TIER": "9",
            "TEXT_COMMIT_STRICT": "yes-please",
            "TEXT_COMMIT_PREVIEW": "hologram",
            "TEXT_COMMIT_TELEMETRY": "cloud",
            "TEXT_COMMIT_CONFIRM_DEGRADE": "maybe",
        }
    )
    assert settings == TextCommitSettings()


def test_from_env_empty_environment_is_default():
    # Cross-check that BOTH engine literals (the dataclass field default and
    # the ``from_env`` fallback) moved together: this equality fails if only
    # one of them is flipped.
    assert TextCommitSettings.from_env({}) == TextCommitSettings()
    assert TextCommitSettings.from_env({}).engine == "tiered"


def test_pdf_model_accepts_settings_dto():
    model = PDFModel(text_commit_settings=TextCommitSettings(strict=True))
    try:
        assert model.text_commit_settings.strict is True
    finally:
        model.close()


def test_pdf_model_defaults_to_shipped_settings():
    model = PDFModel()
    try:
        assert model.text_commit_settings == TextCommitSettings()
        assert model.text_commit_settings.engine == "tiered"
        assert model.last_commit_outcome is None
    finally:
        model.close()
