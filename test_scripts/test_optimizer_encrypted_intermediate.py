"""F8: an optimized copy of an encrypted PDF never stages its plaintext on disk (Model only, no Qt).

The working document of an encrypted source is decrypted (an authenticated handle, or
a snapshot rebuilt from decrypted bytes), so the optimized intermediate, and the
pikepdf repack a linearize run makes of it, must stay in memory: the only file the
job writes is the re-encrypted copy.  The test redirects every temp dir under
``tmp_path`` and records the bytes of every file there just before it is moved
(``os.replace``) or removed (``os.unlink``, which ``Path.unlink`` and ``rmtree`` use),
plus whatever is left at the end, so a plaintext stage cannot slip past unseen.
"""

from __future__ import annotations

import dataclasses
import os
import sys
import tempfile
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model import pdf_optimizer  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402

BODY = "F8 confidential body text"
# An Info /Title is a literal string object: any plaintext save carries it raw.
TITLE = "F8-PLAINTEXT-TITLE-MARKER"
USER_PW = "user-secret"
OWNER_PW = "owner-secret"


def _make_encrypted_pdf(path: Path) -> Path:
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), BODY, fontsize=12.0, fontname="helv")
    doc.set_metadata({"title": TITLE})
    doc.save(
        str(path),
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw=OWNER_PW,
        user_pw=USER_PW,
        permissions=int(fitz.PDF_PERM_PRINT | fitz.PDF_PERM_COPY),
    )
    doc.close()
    return path


def _norm(path: str | os.PathLike[str]) -> str:
    text = os.fspath(path)
    if text.startswith("\\\\?\\"):
        text = text[4:]
    return os.path.normcase(os.path.abspath(text))


def _holds_plaintext(data: bytes) -> bool:
    """True when ``data`` is an unencrypted copy of the fixture's content."""
    if TITLE.encode("ascii") in data:
        return True
    try:
        doc = fitz.open("pdf", data)
    except Exception:  # not a PDF at all: the raw scan above is all that applies
        return False
    try:
        if doc.needs_pass or (doc.metadata or {}).get("encryption"):
            return False
        return BODY in "".join(page.get_text() for page in doc)
    finally:
        doc.close()


@pytest.fixture
def staged_files(tmp_path: Path, monkeypatch) -> list[tuple[str, bytes]]:
    """``(path, bytes)`` of every file under ``tmp_path`` that is moved or removed."""
    temp_root = tmp_path / "tmp"
    temp_root.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temp_root))
    watched = _norm(tmp_path)
    seen: list[tuple[str, bytes]] = []
    real_replace = os.replace
    real_unlink = os.unlink

    def _record(path) -> None:
        try:
            name = _norm(path)
        except TypeError:
            return
        if not name.startswith(watched + os.sep) or not os.path.isfile(name):
            return
        try:
            seen.append((name, Path(name).read_bytes()))
        except OSError:
            pass

    def _replace(src, dst, *args, **kwargs):
        _record(src)
        return real_replace(src, dst, *args, **kwargs)

    def _unlink(path, *args, **kwargs):
        _record(path)
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "replace", _replace)
    monkeypatch.setattr(os, "unlink", _unlink)
    return seen


@pytest.mark.parametrize("dirty", [False, True], ids=["file-backed", "dirty-bytes"])
@pytest.mark.parametrize("secure", [False, True], ids=["fast-save", "secure-garbage4"])
@pytest.mark.parametrize("linearize", [False, True], ids=["plain-pack", "linearize"])
def test_encrypted_source_never_writes_a_plaintext_intermediate(
    tmp_path: Path, staged_files: list[tuple[str, bytes]], linearize: bool, secure: bool, dirty: bool
) -> None:
    if linearize and pdf_optimizer._pikepdf() is None:
        pytest.skip("pikepdf not installed in this environment")
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    source = _make_encrypted_pdf(source_dir / "locked.pdf")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    output = out_dir / "locked-optimized.pdf"

    model = PDFModel()
    try:
        assert _norm(model.temp_dir.name).startswith(_norm(tmp_path) + os.sep), (
            "the model temp dir must be under the watched root"
        )
        sid = model.open_pdf(str(source), password=USER_PW)
        session = model._sessions_by_id[sid]
        session.transferred_dirty = dirty  # dirty: the snapshot carries decrypted bytes
        session.secure_save_required = secure
        options = dataclasses.replace(model.preset_optimize_options("平衡"), linearize=linearize)
        model.save_optimized_copy(str(output), options)
        # Whatever the job left in the model temp dir, read before ``close`` removes it.
        staged_files.extend(
            (_norm(path), path.read_bytes())
            for path in Path(model.temp_dir.name).rglob("*")
            if path.is_file()
        )
    finally:
        model.close()

    leftovers = [
        (_norm(path), path.read_bytes()) for path in tmp_path.rglob("*") if path.is_file()
    ]
    observed = staged_files + leftovers
    assert any(name == _norm(output) for name, _data in leftovers)
    assert len(staged_files) >= 1, "the encrypted copy is installed by os.replace"
    leaked = sorted({name for name, data in observed if _holds_plaintext(data)})
    assert leaked == [], f"plaintext of the encrypted source reached disk: {leaked}"

    with fitz.open(str(output)) as result:
        assert result.needs_pass
        assert result.authenticate(USER_PW) == 2
        assert (result.metadata or {}).get("encryption")
        assert BODY in result[0].get_text()
        assert result.metadata.get("title") == TITLE
