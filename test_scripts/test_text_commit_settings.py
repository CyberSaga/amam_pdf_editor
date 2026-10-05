"""Red-light tests for the Qt-free text-commit settings DTO (Task 5)."""
from __future__ import annotations

import sys
from pathlib import Path

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
    preview by token).  Strict refusal and telemetry stay off."""
    settings = TextCommitSettings()
    assert settings.engine == "tiered"
    assert settings.max_tier == 1
    assert settings.strict is False
    assert settings.preview == "plan"
    assert settings.telemetry == "off"
    # UI step 7 retired the T16-3 ``confirm_degrade`` opt-in: the consent
    # modal now hangs off the request's explicit rebuild consent
    # (``EditTextRequest.allow_rebuild``), never off a global setting.
    assert not hasattr(settings, "confirm_degrade")


def test_env_kill_switch_forces_legacy():
    """PIN (T16-3): ``TEXT_COMMIT_ENGINE`` is demoted from an opt-in to a
    kill switch -- absent, users get ``tiered``; set to ``legacy``, the old
    redact+reinsert engine is still reachable without a code change."""
    assert TextCommitSettings.from_env({}).engine == "tiered"
    assert (
        TextCommitSettings.from_env({"TEXT_COMMIT_ENGINE": "legacy"}).engine
        == "legacy"
    )


def test_explicitly_stored_values_are_never_overridden_by_the_new_defaults():
    """GUARD (labelled; true before and after the flip).  Step 12 flips
    DEFAULTS only: a value the user stored (an environment variable is the
    only store these settings have) keeps its meaning, old values included."""
    assert TextCommitSettings.from_env({"TEXT_COMMIT_MAX_TIER": "0"}).max_tier == 0
    assert TextCommitSettings.from_env({"TEXT_COMMIT_PREVIEW": "legacy"}).preview == "legacy"
    stored = TextCommitSettings.from_env(
        {"TEXT_COMMIT_ENGINE": "legacy", "TEXT_COMMIT_PREVIEW": "plan"}
    )
    assert (stored.engine, stored.preview) == ("legacy", "plan")


def test_kill_switch_alone_keeps_the_legacy_preview():
    """``TEXT_COMMIT_ENGINE=legacy`` (the kill switch) with no stored preview
    keeps the tokenless legacy preview: the plan preview verifies a TIERED
    candidate, so under the legacy engine Apply would commit a different
    result than the one previewed (plan section 3) -- and a refused preview
    would leave Apply disabled.  The preview DEFAULT therefore follows the
    engine: plan for tiered, legacy otherwise."""
    kill = TextCommitSettings.from_env({"TEXT_COMMIT_ENGINE": "legacy"})
    assert (kill.engine, kill.preview) == ("legacy", "legacy")
    shadow = TextCommitSettings.from_env({"TEXT_COMMIT_ENGINE": "shadow"})
    assert shadow.preview == "legacy"
    assert TextCommitSettings.from_env({"TEXT_COMMIT_ENGINE": "tiered"}).preview == "plan"
    # An invalid preview falls back to the engine-derived default.
    assert (
        TextCommitSettings.from_env(
            {"TEXT_COMMIT_ENGINE": "legacy", "TEXT_COMMIT_PREVIEW": "hologram"}
        ).preview
        == "legacy"
    )


def test_constructor_preview_default_follows_the_engine_too():
    """The engine-derived preview default is a property of the DTO, not only
    of ``from_env``: ``TextCommitSettings(engine="legacy")`` built in code
    must never be the incoherent legacy-engine + plan-preview pair (Apply
    would wait for a tiered token and then commit through legacy).  An
    explicit ``preview`` argument still wins."""
    assert TextCommitSettings().preview == "plan"
    assert TextCommitSettings(engine="tiered").preview == "plan"
    assert TextCommitSettings(engine="legacy").preview == "legacy"
    assert TextCommitSettings(engine="shadow").preview == "legacy"
    assert TextCommitSettings(engine="legacy", preview="plan").preview == "plan"
    assert TextCommitSettings(engine="tiered", preview="legacy").preview == "legacy"
    assert TextCommitSettings(engine="legacy") == TextCommitSettings(
        engine="legacy", preview="legacy"
    )


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
            "TEXT_COMMIT_ENGINE": "shadow",
            "TEXT_COMMIT_MAX_TIER": "1",
            "TEXT_COMMIT_STRICT": "1",
            "TEXT_COMMIT_PREVIEW": "plan",
            "TEXT_COMMIT_TELEMETRY": "local",
            "TEXT_COMMIT_CONFIRM_DEGRADE": "1",
        }
    )
    assert settings.engine == "shadow"
    assert settings.max_tier == 1
    assert settings.strict is True
    assert settings.preview == "plan"
    assert settings.telemetry == "local"
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
    model = PDFModel(text_commit_settings=TextCommitSettings(engine="shadow"))
    try:
        assert model.text_commit_settings.engine == "shadow"
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
