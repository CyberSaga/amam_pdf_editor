"""Fails loudly on PyMuPDF version skew instead of silently masking bugs.

requirements.txt / pyproject.toml pin PyMuPDF to >=1.27,<1.28 (not just a
floor): the text-commit engine's Tier 0/1 fidelity checks assert
byte-identical content-stream bytes, and PyMuPDF's stream serialization /
extract_font behavior can shift between minors. A stray interpreter (e.g.
system Python resolving an older PyMuPDF instead of the repo's `.venv`) must
not be allowed to pass this suite while quietly exercising different stream
behavior — see docs/PITFALLS.md "PyMuPDF version skew masks runtime-only
bugs" and CLAUDE.md's `.venv\\Scripts\\python.exe -m pytest` requirement.
"""
from __future__ import annotations

from pathlib import Path

import fitz

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_pymupdf_version_within_pinned_range() -> None:
    major, minor, *_ = (int(part) for part in fitz.__version__.split(".")[:2] + [0])
    assert (major, minor) == (1, 27), (
        f"fitz.__version__ == {fitz.__version__!r} is outside the pinned "
        "range (>=1.27,<1.28 per requirements.txt). This interpreter is not "
        "the repo .venv — re-run via `.venv\\Scripts\\python.exe -m pytest`, "
        "or the .venv install is stale (`pip install -e .[dev]`)."
    )


def test_pymupdf_exposes_the_char_quad_the_upside_down_box_fix_compares() -> None:
    """GATE16-1: ``model.page_content_text`` finds PyMuPDF's mirrored boxes of
    upside-down (180-degree) chars by comparing MuPDF's own char quad with the
    one PyMuPDF reports, ``fitz.JM_char_quad`` (module-level in 1.27)."""
    assert callable(getattr(fitz, "JM_char_quad", None))


def _requirement_lines(name: str) -> list[str]:
    return [
        line.strip()
        for line in name.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_fonttools_is_a_pinned_runtime_dependency() -> None:
    """EXTB-SUBSET (owner decision C): CJK Ext-B rebuilds subset a Windows
    Ext-B font with fontTools at runtime, so fontTools is a core requirement
    (requirements.txt + pyproject dependencies, the same specifier), pinned
    exactly in constraints-ci.txt -- one pin per interpreter range, because
    fontTools 4.66 needs Python 3.11+ while CI runs 3.10 -- and the pin for
    THIS interpreter is the version installed here; no longer a dev-only
    optional extra."""
    import fontTools
    from packaging.requirements import Requirement
    from packaging.version import Version

    req_lines = [
        line
        for line in _requirement_lines((REPO_ROOT / "requirements.txt").read_text(encoding="utf-8"))
        if line.lower().startswith("fonttools")
    ]
    assert len(req_lines) == 1, req_lines
    req = [Requirement(req_lines[0])]
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    deps = pyproject.split("dependencies = [", 1)[1].split("]", 1)[0]
    assert f'"{req_lines[0]}"' in deps, (req_lines[0], deps)
    constraints = [
        Requirement(line)
        for line in _requirement_lines((REPO_ROOT / "constraints-ci.txt").read_text(encoding="utf-8"))
        if line.lower().startswith("fonttools")
    ]
    assert constraints, "fontTools is not pinned in constraints-ci.txt"
    for pin in constraints:
        (spec,) = list(pin.specifier)
        assert spec.operator == "==", pin
        assert Version(spec.version) in req[0].specifier, (pin, req[0])
    active = [pin for pin in constraints if pin.marker is None or pin.marker.evaluate()]
    assert len(active) == 1, active
    (active_spec,) = list(active[0].specifier)
    assert active_spec.version == fontTools.version, (active[0], fontTools.version)
    optional = _requirement_lines(
        (REPO_ROOT / "optional-requirements.txt").read_text(encoding="utf-8")
    )
    assert not [line for line in optional if line.lower().startswith("fonttools")], optional


def _declared_python_floor() -> tuple[int, int]:
    import re

    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^requires-python\s*=\s*">=(\d+)\.(\d+)"\s*$', pyproject, re.M)
    assert match, "pyproject.toml must declare requires-python as a plain '>=X.Y' floor"
    return int(match.group(1)), int(match.group(2))


def test_requires_python_floor_is_installable_with_the_pinned_runtime_deps() -> None:
    """F12-1: ``requires-python`` must be a floor the pinned runtime
    dependencies can actually install on.  PyMuPDF 1.27.x, Pillow 12.2 and
    numpy 2.2 all declare ``Requires-Python >=3.10`` (no PyMuPDF 1.27 wheel
    exists for cp39), so a ``>=3.9`` claim made ``pip install .`` pass the
    interpreter check and then die with an unclear 'No matching distribution
    found for PyMuPDF'.  The floor must also match the interpreter CI and
    mypy target, and no per-interpreter pin may exist for versions below it."""
    from importlib.metadata import metadata

    from packaging.requirements import Requirement
    from packaging.specifiers import SpecifierSet

    floor = _declared_python_floor()
    floor_text = f"{floor[0]}.{floor[1]}"
    for dist in ("PyMuPDF", "Pillow", "numpy"):
        requires = metadata(dist).get("Requires-Python")
        assert requires, f"{dist} declares no Requires-Python"
        assert SpecifierSet(requires).contains(floor_text), (
            f"pyproject requires-python floor {floor_text} is below {dist}'s "
            f"Requires-Python {requires!r}: nothing installs on {floor_text}"
        )

    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert f'python_version = "{floor_text}"' in pyproject, "mypy python_version != requires-python floor"
    assert f'target-version = "py{floor[0]}{floor[1]}"' in pyproject, "ruff target-version != floor"
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert f'python-version: "{floor_text}"' in ci, "CI does not run the declared floor interpreter"

    # No per-interpreter pin may exist only for interpreters below the floor.
    below = {
        "python_version": f"{floor[0]}.{floor[1] - 1}",
        "python_full_version": f"{floor[0]}.{floor[1] - 1}.0",
    }
    for line in _requirement_lines((REPO_ROOT / "constraints-ci.txt").read_text(encoding="utf-8")):
        marker = Requirement(line).marker
        assert marker is None or not marker.evaluate(below), (
            f"constraints-ci.txt pin {line!r} targets an interpreter below the "
            f"requires-python floor {floor_text} (dead configuration)"
        )

    # No doc that states the supported floor may still say 3.9.
    for rel in ("requirements.txt", "CLAUDE.md"):
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "Python 3.9" not in text, f"{rel} still advertises Python 3.9"
