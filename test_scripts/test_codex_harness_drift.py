"""Drift guard for the Codex harness (AGENTS.md, .codex/, docs/codex/).

Pure file checks: stdlib + pytest only, no project imports.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
AGENTS = REPO / "AGENTS.md"
CODEX_DIR = REPO / ".codex"
HOOKS_JSON = CODEX_DIR / "hooks.json"
CONFIG_TOML = CODEX_DIR / "config.toml"
ROLES_DIR = CODEX_DIR / "agents"
PROFILE_TEMPLATE = REPO / "docs" / "codex" / "pdf-editor.config.toml"
README = REPO / "docs" / "codex" / "README.md"

AGENTS_MAX_BYTES = 24 * 1024

# role -> (model, reasoning effort); the only mapping the harness allows.
ROLE_MAP: dict[str, tuple[str, str]] = {
    "reader": ("gpt-6.1-terra", "medium"),
    "fast-worker": ("gpt-6-luna", "low"),
    "deep-reasoner": ("gpt-6.1-sol", "xhigh"),
    "plan-code-reviewer": ("gpt-6.1-sol", "high"),
}

# Phrases that would make AGENTS.md contradict CLAUDE.md or the verified hook contract.
CONTRADICTION_MARKERS = (
    "claude.md wins",
    "claude.md overrides",
    "defer to claude.md",
    "follow it as the source of truth",
    "exit 2 blocks",
    "exit code 2 blocks",
    "exit 2 to block",
    "<<<<<<<",
    ">>>>>>>",
)
PLACEHOLDER_WORDS = re.compile(r"\b(TODO|FIXME|TBD)\b")

# The harness must stay task-agnostic. The terms it must not name are supplied from outside the
# tracked tree: GENERIC_GUARD_FILE points at a text file with one regex per line (blank lines and
# '#' lines ignored). Without it the check is skipped.
GENERIC_GUARD_ENV = "GENERIC_GUARD_FILE"


def _forbidden_terms() -> list[re.Pattern[str]]:
    source = os.environ.get(GENERIC_GUARD_ENV)
    if not source or not Path(source).is_file():
        return []
    lines = Path(source).read_text(encoding="utf-8").splitlines()
    return [re.compile(ln.strip(), re.IGNORECASE) for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]

MACHINE_PATH_PATTERNS = (
    re.compile(r"[A-Za-z]:\\+Users\\+[^\\\s\"']+"),
    re.compile("/" + "home" + r"/[^/\s\"']+/"),
    re.compile(r"\b[A-Za-z]:[\\/]"),
)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_toml(path: Path) -> dict:
    return tomllib.loads(_text(path))


def _harness_files() -> list[Path]:
    files = [AGENTS, HOOKS_JSON, CONFIG_TOML, PROFILE_TEMPLATE, README]
    files += sorted(ROLES_DIR.glob("*.toml"))
    return files


def test_agents_md_size_cap():
    assert AGENTS.is_file()
    size = len(AGENTS.read_bytes())
    assert size <= AGENTS_MAX_BYTES, f"AGENTS.md is {size} bytes, cap {AGENTS_MAX_BYTES}"


def test_agents_md_states_rulebook_split_and_has_no_contradiction_markers():
    text = _text(AGENTS)
    low = text.lower()
    found = [m for m in CONTRADICTION_MARKERS if m in low]
    assert not found, f"AGENTS.md carries contradiction markers: {found}"
    assert not PLACEHOLDER_WORDS.search(text), "AGENTS.md carries a placeholder word"
    assert "Codex rulebook" in text
    assert "CLAUDE.md remains the rulebook for Claude" in text


def test_agents_md_role_table_matches_role_map():
    text = _text(AGENTS)
    for role, (model, effort) in ROLE_MAP.items():
        rows = [ln for ln in text.splitlines() if ln.startswith(f"| `{role}` |")]
        assert len(rows) == 1, f"AGENTS.md role table lacks exactly one row for {role}"
        assert f"{model} / {effort}" in rows[0], f"{role}: row {rows[0]!r} != {model} / {effort}"


def test_hooks_json_parses_and_points_at_existing_scripts():
    data = json.loads(_text(HOOKS_JSON))
    hooks = data["hooks"]
    assert hooks, "hooks.json registers nothing"
    seen = 0
    for event, groups in hooks.items():
        for group in groups:
            for hook in group["hooks"]:
                assert hook["type"] == "command"
                command = hook["command"]
                for pattern in MACHINE_PATH_PATTERNS:
                    assert not pattern.search(command), f"{event}: machine path in {command!r}"
                scripts = [t for t in shlex.split(command) if t.endswith(".py")]
                assert scripts, f"{event}: command names no .py script: {command!r}"
                for script in scripts:
                    assert not Path(script).is_absolute(), f"{event}: absolute script path {script}"
                    assert (REPO / script).is_file(), f"{event}: missing script {script}"
                seen += 1
    assert seen >= 1


def test_role_files_parse_and_are_registered_both_ways():
    config = _load_toml(CONFIG_TOML)
    registered = config["agents"]
    reg_roles = {
        name: entry for name, entry in registered.items() if isinstance(entry, dict)
    }
    files = {p.stem: p for p in ROLES_DIR.glob("*.toml")}
    assert files, "no role files under .codex/agents"
    assert set(reg_roles) == set(files), (
        f"registered {sorted(reg_roles)} != role files {sorted(files)}"
    )
    for name, entry in reg_roles.items():
        assert entry.get("description"), f"{name}: registration lacks a description"
        target = (CODEX_DIR / entry["config_file"]).resolve()
        assert target == files[name].resolve(), f"{name}: config_file points at {entry['config_file']}"
        role = _load_toml(files[name])
        assert role.get("name") == name, f"{name}: role file name is {role.get('name')!r}"
        assert role.get("developer_instructions", "").strip(), f"{name}: empty developer_instructions"


def test_role_files_pin_allowed_model_and_effort():
    files = {p.stem: p for p in ROLES_DIR.glob("*.toml")}
    assert set(files) == set(ROLE_MAP), f"roles {sorted(files)} != allowed {sorted(ROLE_MAP)}"
    for name, path in files.items():
        role = _load_toml(path)
        want_model, want_effort = ROLE_MAP[name]
        assert role.get("model") == want_model, f"{name}: model {role.get('model')!r} != {want_model}"
        assert role.get("model_reasoning_effort") == want_effort, (
            f"{name}: effort {role.get('model_reasoning_effort')!r} != {want_effort}"
        )
        assert "Retry cap:" in role["developer_instructions"], f"{name}: retry-cap line missing"


def test_profile_template_parses_and_names_implementer():
    profile = _load_toml(PROFILE_TEMPLATE)
    assert profile["model"] == "gpt-6.1-sol"
    assert profile["model_reasoning_effort"] == "high"
    assert "profile" not in profile and "profiles" not in profile


def test_harness_stays_generic():
    terms = _forbidden_terms()
    if not terms:
        pytest.skip(f"{GENERIC_GUARD_ENV} not set")
    targets = [AGENTS, *sorted(ROLES_DIR.glob("*.toml"))]
    for path in targets:
        text = _text(path)
        for pattern in terms:
            match = pattern.search(text)
            assert match is None, f"{path.name} names a guarded term: {match.group(0)!r}"


def test_generic_guard_flags_a_listed_term(tmp_path, monkeypatch):
    guard = tmp_path / "terms.txt"
    guard.write_text("# comment\n\nsecret\\s+word\n", encoding="utf-8")
    monkeypatch.setenv(GENERIC_GUARD_ENV, str(guard))
    terms = _forbidden_terms()
    assert len(terms) == 1 and terms[0].search("a Secret   Word here")
    monkeypatch.delenv(GENERIC_GUARD_ENV)
    assert _forbidden_terms() == []


def test_no_machine_specific_paths_in_harness_files():
    for path in _harness_files():
        text = _text(path)
        for pattern in MACHINE_PATH_PATTERNS[:2]:
            match = pattern.search(text)
            assert match is None, f"{path.name}: machine path {match.group(0)!r}"


def test_detects_drift_in_synthetic_role_map(tmp_path):
    # The comparison used above must flag a changed pin, not only pass on the happy path.
    role = tmp_path / "reader.toml"
    role.write_text('name = "reader"\nmodel = "gpt-6-luna"\nmodel_reasoning_effort = "medium"\n', encoding="utf-8")
    parsed = _load_toml(role)
    assert (parsed["model"], parsed["model_reasoning_effort"]) != ROLE_MAP["reader"]
