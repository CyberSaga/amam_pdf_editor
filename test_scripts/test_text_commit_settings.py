"""Red-light tests for the Qt-free text-commit settings DTO (Task 5)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.pdf_model import PDFModel  # noqa: E402
from model.text_commit.dto import TextCommitSettings  # noqa: E402


def test_default_settings_are_tiered_and_conservative():
    """PIN (T16-3): the shipped default engine is the fidelity-preserving
    tiered one. Everything else stays conservative -- Tier 1 (``max_tier``),
    strict refusal and the plan preview are separate gates, not part of the
    engine default flip."""
    settings = TextCommitSettings()
    assert settings.engine == "tiered"
    assert settings.max_tier == 0
    assert settings.strict is False
    assert settings.preview == "legacy"
    assert settings.telemetry == "off"
    # T16-3 review round: the P0-C pre-commit consent modal is an opt-in, not
    # a consequence of the engine default. Under max_tier=0 a Tier 0 refusal
    # + legacy fallback is the COMMON path, so a default-on modal would ask
    # the user to approve almost every edit; T16-1's non-blocking degrade
    # notice is the disclosure channel the flip was accepted on.
    assert settings.confirm_degrade is False


def test_env_kill_switch_forces_legacy():
    """PIN (T16-3): ``TEXT_COMMIT_ENGINE`` is demoted from an opt-in to a
    kill switch -- absent, users get ``tiered``; set to ``legacy``, the old
    redact+reinsert engine is still reachable without a code change."""
    assert TextCommitSettings.from_env({}).engine == "tiered"
    assert (
        TextCommitSettings.from_env({"TEXT_COMMIT_ENGINE": "legacy"}).engine
        == "legacy"
    )


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
    assert settings.confirm_degrade is True


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
