"""Optimize-copy re-encryption never emits RC4 and keeps the source's effective permissions.

An RC4-40 / RC4-128 source used to be re-encrypted with the same broken cipher, so the
copy's (possibly freshly generated, strong) password protected a 40-bit key. The copy is
now AES-256 (revision 6). Revision 2 ignores /P bits 9-12 while revision 6 obeys them
(ISO 32000-1 Table 22), so permissions are compared as each file's *effective* grants
under its own revision (pikepdf ``Pdf.allow``), never as raw /P values.
"""

from __future__ import annotations

import sys
from pathlib import Path

import fitz
import pikepdf
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_TEXT = "confidential content"
_USER_PW = "secret"
_OWNER_PW = "ownerpw"

_PRINT = int(fitz.PDF_PERM_PRINT)
_MODIFY = int(fitz.PDF_PERM_MODIFY)
_COPY = int(fitz.PDF_PERM_COPY)
_ANNOTATE = int(fitz.PDF_PERM_ANNOTATE)

# (method, requested permissions, expected source revision, expected raw source /P).
# The raw /P is a fixture guard only: it proves the source is the case named, e.g. the
# fitz-written revision-2 PRINT|COPY file (-3884, bits 9-12 clear) or the legacy -44 mask
# (bits 9-12 set) other writers emit for the same grants.
_RC4_SOURCES = [
    pytest.param(fitz.PDF_ENCRYPT_RC4_40, _PRINT | _COPY, 2, -3884, id="rc4-40-print-copy"),
    pytest.param(
        fitz.PDF_ENCRYPT_RC4_40,
        _PRINT | _MODIFY | _COPY | _ANNOTATE,
        2,
        -3844,
        id="rc4-40-print-modify-copy-annotate",
    ),
    pytest.param(fitz.PDF_ENCRYPT_RC4_40, -44, 2, -44, id="rc4-40-legacy-minus-44"),
    pytest.param(fitz.PDF_ENCRYPT_RC4_128, _PRINT | _COPY, 3, -3884, id="rc4-128-print-copy"),
    pytest.param(
        fitz.PDF_ENCRYPT_RC4_128,
        _PRINT | _MODIFY | _COPY | _ANNOTATE,
        3,
        -3844,
        id="rc4-128-print-modify-copy-annotate",
    ),
    pytest.param(fitz.PDF_ENCRYPT_RC4_128, -44, 3, -44, id="rc4-128-minus-44"),
]


def _make_source(path: Path, method: int, permissions: int, user_pw: str, owner_pw: str) -> Path:
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), _TEXT, fontsize=12, fontname="helv")
    if method == fitz.PDF_ENCRYPT_NONE:
        doc.save(str(path))
    else:
        doc.save(
            str(path),
            encryption=method,
            owner_pw=owner_pw,
            user_pw=user_pw,
            permissions=permissions,
        )
    doc.close()
    return path


def _effective(path: Path, password: str) -> tuple[int, int, pikepdf.Permissions]:
    """(revision, raw /P, effective grants under that revision) as qpdf reads the file."""
    with pikepdf.open(path, password=password) as pdf:
        return int(pdf.encryption.R), int(pdf.encryption.P), pdf.allow


def _optimize(source: Path, output: Path, password: str | None) -> None:
    from model.pdf_model import PDFModel

    model = PDFModel()
    try:
        if password is None:
            model.open_pdf(str(source))
        else:
            model.open_pdf(str(source), password=password)
        model.save_optimized_copy(str(output), model.preset_optimize_options("平衡"))
    finally:
        model.close()


def _text(path: Path, password: str | None) -> str:
    doc = fitz.open(str(path))
    try:
        if password is not None:
            assert doc.authenticate(password) != 0
        return "".join(page.get_text() for page in doc)
    finally:
        doc.close()


def _encryption_meta(path: Path, password: str | None) -> str:
    # A locked handle reports empty metadata, so authenticate before reading it.
    doc = fitz.open(str(path))
    try:
        if password is not None and doc.needs_pass:
            assert doc.authenticate(password) != 0
        return (doc.metadata or {}).get("encryption") or ""
    finally:
        doc.close()


def _assert_aes256(path: Path, password: str | None) -> None:
    enc = _encryption_meta(path, password)
    assert "RC4" not in enc.upper(), f"the optimized copy must never be RC4: {enc!r}"
    assert "AES" in enc.upper() and " R6 " in f" {enc} ", (
        f"an RC4 source's optimized copy must be AES-256 (revision 6): {enc!r}"
    )


@pytest.mark.parametrize(("method", "requested", "src_rev", "src_p"), _RC4_SOURCES)
def test_rc4_user_source_copy_is_aes256_with_identical_effective_permissions(
    tmp_path: Path, method: int, requested: int, src_rev: int, src_p: int
) -> None:
    source = _make_source(tmp_path / "rc4-user.pdf", method, requested, _USER_PW, _OWNER_PW)
    rev, raw_p, src_allow = _effective(source, _USER_PW)
    assert (rev, raw_p) == (src_rev, src_p), "fixture is not the case named in its id"

    output = tmp_path / "rc4-user-optimized.pdf"
    _optimize(source, output, _USER_PW)

    _assert_aes256(output, _USER_PW)
    out_rev, _out_p, out_allow = _effective(output, _USER_PW)
    assert out_rev == 6
    assert out_allow == src_allow, (
        f"the AES copy must grant exactly the source's effective permissions "
        f"(source R{src_rev}: {src_allow}; copy R6: {out_allow})"
    )
    probe = fitz.open(str(output))
    try:
        assert probe.needs_pass, "the copy of a user-password source must stay locked"
        assert probe.authenticate(_USER_PW) == 2, "the user credential must stay user-level (R5-02)"
    finally:
        probe.close()
    assert _TEXT in _text(output, _USER_PW)


@pytest.mark.parametrize(("method", "requested", "src_rev", "src_p"), _RC4_SOURCES)
def test_rc4_owner_only_source_copy_is_aes256_opens_unprompted_with_identical_effective_permissions(
    tmp_path: Path, method: int, requested: int, src_rev: int, src_p: int
) -> None:
    source = _make_source(tmp_path / "rc4-owner-only.pdf", method, requested, "", _OWNER_PW)
    rev, raw_p, src_allow = _effective(source, "")
    assert (rev, raw_p) == (src_rev, src_p), "fixture is not the case named in its id"

    output = tmp_path / "rc4-owner-only-optimized.pdf"
    _optimize(source, output, None)

    _assert_aes256(output, None)
    out_rev, _out_p, out_allow = _effective(output, "")
    assert out_rev == 6
    assert out_allow == src_allow, (
        f"the AES copy must grant exactly the source's effective permissions "
        f"(source R{src_rev}: {src_allow}; copy R6: {out_allow})"
    )
    probe = fitz.open(str(output))
    try:
        assert not probe.needs_pass, "an owner-only source's copy must still open unprompted"
    finally:
        probe.close()
    assert _TEXT in _text(output, None)


@pytest.mark.parametrize(
    "method",
    [
        pytest.param(fitz.PDF_ENCRYPT_RC4_40, id="rc4-40"),
        pytest.param(fitz.PDF_ENCRYPT_RC4_128, id="rc4-128"),
    ],
)
def test_rc4_owner_auth_source_copy_is_aes256_and_owner_stays_owner(
    tmp_path: Path, method: int
) -> None:
    source = _make_source(tmp_path / "rc4-owner.pdf", method, _PRINT | _COPY, _USER_PW, _OWNER_PW)
    output = tmp_path / "rc4-owner-optimized.pdf"
    _optimize(source, output, _OWNER_PW)

    _assert_aes256(output, _OWNER_PW)
    probe = fitz.open(str(output))
    try:
        assert probe.needs_pass
        assert probe.authenticate(_OWNER_PW) in (4, 6), "the owner credential must stay owner-level"
    finally:
        probe.close()
    assert _TEXT in _text(output, _OWNER_PW)


@pytest.mark.parametrize(
    ("method", "requested", "expected_marker"),
    [
        pytest.param(fitz.PDF_ENCRYPT_AES_128, _PRINT | _COPY, " R4 ", id="aes-128"),
        pytest.param(fitz.PDF_ENCRYPT_AES_256, _PRINT | _COPY, " R6 ", id="aes-256"),
        pytest.param(fitz.PDF_ENCRYPT_AES_128, -44, " R4 ", id="aes-128-minus-44"),
        pytest.param(fitz.PDF_ENCRYPT_AES_256, -44, " R6 ", id="aes-256-minus-44"),
    ],
)
def test_aes_source_keeps_its_method_and_effective_permissions(
    tmp_path: Path, method: int, requested: int, expected_marker: str
) -> None:
    source = _make_source(tmp_path / "aes-user.pdf", method, requested, _USER_PW, _OWNER_PW)
    _rev, _p, src_allow = _effective(source, _USER_PW)
    output = tmp_path / "aes-user-optimized.pdf"
    _optimize(source, output, _USER_PW)

    enc = _encryption_meta(output, _USER_PW)
    assert "AES" in enc and expected_marker in f" {enc} ", f"AES source changed method: {enc!r}"
    probe = fitz.open(str(output))
    try:
        assert probe.authenticate(_USER_PW) == 2
    finally:
        probe.close()
    _out_rev, _out_p, out_allow = _effective(output, _USER_PW)
    assert out_allow == src_allow


def test_unencrypted_source_copy_stays_unencrypted(tmp_path: Path) -> None:
    source = _make_source(tmp_path / "plain.pdf", fitz.PDF_ENCRYPT_NONE, -1, "", "")
    output = tmp_path / "plain-optimized.pdf"
    _optimize(source, output, None)

    probe = fitz.open(str(output))
    try:
        assert not probe.needs_pass
        assert not (probe.metadata or {}).get("encryption")
    finally:
        probe.close()
    assert _TEXT in _text(output, None)


@pytest.mark.parametrize(
    ("encryption_meta", "expected"),
    [
        ("Standard V1 R2 40-bit RC4", fitz.PDF_ENCRYPT_AES_256),
        ("Standard V2 R3 128-bit RC4", fitz.PDF_ENCRYPT_AES_256),
        ("Standard V2 R3 40-bit RC4", fitz.PDF_ENCRYPT_AES_256),
        ("Standard V4 R4 128-bit AES", fitz.PDF_ENCRYPT_AES_128),
        ("Standard V5 R6 256-bit AES", fitz.PDF_ENCRYPT_AES_256),
        ("", fitz.PDF_ENCRYPT_AES_256),
        ("Unknown handler", fitz.PDF_ENCRYPT_AES_256),
    ],
)
def test_encryption_method_for_never_returns_rc4(encryption_meta: str, expected: int) -> None:
    from model.pdf_optimizer import _encryption_method_for

    method = _encryption_method_for(encryption_meta)
    assert method not in (fitz.PDF_ENCRYPT_RC4_40, fitz.PDF_ENCRYPT_RC4_128)
    assert method == expected


@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        pytest.param(_PRINT | _COPY, -1324, id="print-copy"),
        pytest.param(_PRINT | _MODIFY | _COPY | _ANNOTATE, -4, id="print-modify-copy-annotate"),
        pytest.param(-44, -1324, id="legacy-minus-44"),
    ],
)
def test_revision2_descriptor_mask_states_the_implied_extended_bits(
    tmp_path: Path, requested: int, expected: int
) -> None:
    """Supplementary pin of the captured mask (the allow-equality tests are the invariant):
    each R2 extended bit is set or cleared to match its governing bit."""
    from model.pdf_model import PDFModel
    from model.pdf_optimizer import _capture_encryption_descriptor

    source = _make_source(
        tmp_path / "rc4-40.pdf", fitz.PDF_ENCRYPT_RC4_40, requested, _USER_PW, _OWNER_PW
    )
    model = PDFModel()
    try:
        sid = model.open_pdf(str(source), password=_USER_PW)
        descriptor = _capture_encryption_descriptor(model, sid)
    finally:
        model.close()
    assert descriptor.method == fitz.PDF_ENCRYPT_AES_256
    assert descriptor.permissions == expected


@pytest.mark.parametrize(
    "requested",
    [
        pytest.param(_PRINT | _COPY, id="print-copy"),
        pytest.param(-44, id="minus-44"),
    ],
)
def test_revision3_descriptor_mask_is_unchanged(tmp_path: Path, requested: int) -> None:
    from model.pdf_model import PDFModel
    from model.pdf_optimizer import _capture_encryption_descriptor

    source = _make_source(
        tmp_path / "rc4-128.pdf", fitz.PDF_ENCRYPT_RC4_128, requested, _USER_PW, _OWNER_PW
    )
    _rev, raw_p, _allow = _effective(source, _USER_PW)
    model = PDFModel()
    try:
        sid = model.open_pdf(str(source), password=_USER_PW)
        descriptor = _capture_encryption_descriptor(model, sid)
    finally:
        model.close()
    assert descriptor.permissions == raw_p
