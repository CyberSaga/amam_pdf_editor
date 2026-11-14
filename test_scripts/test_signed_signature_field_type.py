"""F16: the signed-document probe reads a field's ``/FT`` and ``/V`` fail-closed (Model only, no Qt).

``document_has_a_signed_signature`` gates the high-fidelity text edit, the
signature-loss consent dialog and open-time xref compaction.  It used to
recognise a field's type only when ``/FT`` was a DIRECT name, only passed a
type down ``/Kids`` and only read a signature field's OWN ``/V``: an indirect
``/FT 20 0 R`` (``20 0 obj /Sig``), a non-name ``/FT``, a terminal field
listed directly in ``/Fields`` whose ``/FT`` sits on a ``/Parent`` the walk
never visits, or a signature widget whose ``/V`` sits on such a parent all
read as "not signed", so a genuinely signed document answered ``False``.

Both ``/FT`` and ``/V`` are inheritable (ISO 32000-1 12.7.3.1), and MuPDF
1.27.1 reports a ``/Sig`` widget whose ``/V`` sits only on its ``/Parent`` as
signed.  The probe may answer "signed" for more documents than before, never
for fewer: every document the old probe called signed stays signed (the
``*_invariant`` cases below pin the shapes where resolving an indirect
``/FT`` could otherwise have LOWERED an inherited ``/Sig``).

Every fixture is a synthetic PDF built in ``tmp_path``, saved with
``garbage=0`` and reopened; each case first asserts the shape survived the
round trip, so the probe is never asked about a document PyMuPDF normalised.
"""

from __future__ import annotations

import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.inspect import (  # noqa: E402
    document_has_a_signed_signature,
    page_has_widgets_or_signatures,
)

SIG = (
    "<< /Type /Sig /Filter /Adobe.PPKLite /SubFilter /adbe.pkcs7.detached"
    " /ByteRange [0 0 0 0] /Contents <00> >>"
)


def _open_form(
    tmp_path: Path, objects: dict[str, str | None], fields: list[str]
) -> tuple[fitz.Document, dict[str, int]]:
    """A two-page PDF whose ``/AcroForm /Fields`` lists ``fields``, reopened.

    ``objects`` maps a name to the object's source text, where ``{name}``
    stands for a reference to that object (so cycles and forward references
    are just text); ``None`` reserves a slot that is never written.  The
    fields are not page annotations: only the form tree is probed."""
    doc = fitz.open()
    doc.new_page()
    doc.new_page()
    xrefs = {name: doc.get_new_xref() for name in objects}
    refs = {name: f"{xref} 0 R" for name, xref in xrefs.items()}
    for name, text in objects.items():
        if text is not None:
            doc.update_object(xrefs[name], text.format(**refs))
    listed = " ".join(refs[name] for name in fields)
    acroform = doc.get_new_xref()
    doc.update_object(acroform, f"<< /Fields [{listed}] >>")
    doc.xref_set_key(doc.pdf_catalog(), "AcroForm", f"{acroform} 0 R")
    path = tmp_path / "form.pdf"
    doc.save(str(path), garbage=0)
    doc.close()
    return fitz.open(str(path)), xrefs


def _chain(depth: int, top: str, leaf: str = "/V {sig}") -> dict[str, str | None]:
    """A terminal ``w`` (listed in ``/Fields``, carrying ``leaf``) under
    ``depth`` ancestors ``a0`` (its parent) .. ``a{depth-1}``; only the top
    one carries ``top`` (e.g. ``"/FT /Sig"`` or ``""``)."""
    objects: dict[str, str | None] = {
        "sig": SIG,
        "w": f"<< /T (w) /Parent {{a0}} {leaf} >>",
    }
    for i in range(depth):
        parent = f" /Parent {{a{i + 1}}}" if i + 1 < depth else ""
        extra = f" {top}" if i + 1 == depth else ""
        objects[f"a{i}"] = f"<< /T (a{i}){parent}{extra} >>"
    return objects


# (case id, objects, /Fields, (object, key, kind the reopened file must show), expected)
_CASES = [
    # --- the exploit shapes: a signature hidden from the old /FT read -> True
    (
        "indirect_ft_naming_sig_with_v",
        {"ft": "/Sig", "sig": SIG, "w": "<< /FT {ft} /T (s) /V {sig} >>"},
        ["w"],
        ("w", "FT", "xref"),
        True,
    ),
    (
        "terminal_in_fields_inherits_sig_from_unlisted_parent",
        {
            "sig": SIG,
            "p": "<< /FT /Sig /T (p) /Kids [{w}] >>",
            "w": "<< /Subtype /Widget /Parent {p} /V {sig} >>",
        },
        ["w"],
        ("w", "FT", "null"),
        True,
    ),
    (
        "terminal_in_fields_with_ft_and_v_on_unlisted_parent",
        {
            "sig": SIG,
            "p": "<< /FT /Sig /T (p) /V {sig} /Kids [{w}] >>",
            "w": "<< /Subtype /Widget /Parent {p} >>",
        },
        ["w"],
        ("w", "V", "null"),
        True,
    ),
    (
        "terminal_inherits_an_indirect_sig_two_levels_up",
        {
            "ft": "/Sig",
            "sig": SIG,
            "g": "<< /FT {ft} /T (g) /Kids [{p}] >>",
            "p": "<< /T (p) /Parent {g} /Kids [{w}] >>",
            "w": "<< /Subtype /Widget /Parent {p} /V {sig} >>",
        },
        ["w"],
        ("g", "FT", "xref"),
        True,
    ),
    (
        "kid_under_a_text_field_whose_own_parent_is_sig",
        {
            "sig": SIG,
            "tx": "<< /FT /Tx /T (tx) /Kids [{w}] >>",
            "p": "<< /FT /Sig /T (p) >>",
            "w": "<< /Parent {p} /V {sig} >>",
        },
        ["tx"],
        ("w", "Parent", "xref"),
        True,
    ),
    (
        "sig_twenty_parents_up",
        _chain(20, "/FT /Sig"),
        ["w"],
        ("a19", "FT", "name"),
        True,
    ),
    # --- a signature field's /V inherited along its own /Parent chain -> True
    (
        # R1: the widget names /Sig itself; the value sits on its unlisted parent.
        "sig_widget_with_v_on_an_unlisted_parent_without_ft",
        {
            "sig": SIG,
            "p": "<< /T (p) /V {sig} /Kids [{w}] >>",
            "w": "<< /FT /Sig /Subtype /Widget /Parent {p} >>",
        },
        ["w"],
        ("p", "FT", "null"),
        True,
    ),
    (
        # R1b: both name /Sig; only the unlisted parent carries the value.
        "sig_widget_with_v_on_an_unlisted_sig_parent",
        {
            "sig": SIG,
            "p": "<< /FT /Sig /T (p) /V {sig} /Kids [{w}] >>",
            "w": "<< /FT /Sig /Subtype /Widget /Parent {p} >>",
        },
        ["w"],
        ("w", "V", "null"),
        True,
    ),
    (
        # R3: the widget's /FT is indirect (-> /Sig); the value sits on its parent.
        "indirect_sig_widget_with_v_on_an_unlisted_parent",
        {
            "ft": "/Sig",
            "sig": SIG,
            "p": "<< /T (p) /V {sig} /Kids [{w}] >>",
            "w": "<< /FT {ft} /Subtype /Widget /Parent {p} >>",
        },
        ["w"],
        ("w", "FT", "xref"),
        True,
    ),
    (
        "sig_widget_with_v_two_parents_up",
        {
            "sig": SIG,
            "g": "<< /T (g) /V {sig} /Kids [{p}] >>",
            "p": "<< /T (p) /Parent {g} /Kids [{w}] >>",
            "w": "<< /FT /Sig /Subtype /Widget /Parent {p} >>",
        },
        ["w"],
        ("p", "V", "null"),
        True,
    ),
    (
        "kid_inheriting_sig_through_kids_with_v_on_its_own_parent",
        {
            "sig": SIG,
            "g": "<< /FT /Sig /T (g) /Kids [{w}] >>",
            "q": "<< /T (q) /V {sig} >>",
            "w": "<< /Subtype /Widget /Parent {q} >>",
        },
        ["g"],
        ("w", "V", "null"),
        True,
    ),
    (
        "sig_widget_under_a_direct_parent_dictionary_carrying_v",
        {"sig": SIG, "w": "<< /FT /Sig /T (w) /Parent << /T (p) /V {sig} >> >>"},
        ["w"],
        ("w", "Parent", "dict"),
        True,
    ),
    # --- an /FT nobody can read cannot prove "not a signature field" -> True
    ("non_name_ft_integer", {"w": "<< /FT 5 /T (w) >>"}, ["w"], ("w", "FT", "int"), True),
    ("non_name_ft_string", {"w": "<< /FT (Sig) /T (w) >>"}, ["w"], ("w", "FT", "string"), True),
    ("non_name_ft_array", {"w": "<< /FT [/Sig] /T (w) >>"}, ["w"], ("w", "FT", "array"), True),
    (
        "indirect_ft_to_a_non_name",
        {"n": "5", "w": "<< /FT {n} /T (w) >>"},
        ["w"],
        ("w", "FT", "xref"),
        True,
    ),
    (
        "indirect_ft_to_an_unwritten_slot",
        {"free": None, "w": "<< /FT {free} /T (w) >>"},
        ["w"],
        ("w", "FT", "xref"),
        True,
    ),
    (
        "parent_with_a_non_name_ft",
        {"p": "<< /FT 7 /T (p) /Kids [{w}] >>", "w": "<< /Parent {p} >>"},
        ["w"],
        ("p", "FT", "int"),
        True,
    ),
    (
        "direct_parent_dictionary",
        {"w": "<< /T (w) /Parent << /FT /Tx /T (p) >> >>"},
        ["w"],
        ("w", "Parent", "dict"),
        True,
    ),
    ("parent_chain_over_the_bound", _chain(100, ""), ["w"], ("a99", "FT", "null"), True),
    (
        "sig_placeholder_value_walk_over_the_bound",
        _chain(33, "", leaf="/FT /Sig"),
        ["w"],
        ("a32", "Parent", "null"),
        True,
    ),
    # --- invariant pins: shapes the old probe already called signed stay signed
    # (an indirect /FT naming /Tx under an inherited /Sig must not lower it)
    (
        "indirect_text_type_under_an_inherited_sig_with_v_invariant",
        {
            "ft": "/Tx",
            "g": "<< /FT /Sig /T (g) /Kids [{f}] >>",
            "f": "<< /FT {ft} /T (f) /Parent {g} /V (hello) >>",
        },
        ["g"],
        ("f", "FT", "xref"),
        True,
    ),
    (
        "indirect_text_type_under_an_inherited_sig_with_a_signature_v_invariant",
        {
            "ft": "/Tx",
            "sig": SIG,
            "g": "<< /FT /Sig /T (g) /Kids [{f}] >>",
            "f": "<< /FT {ft} /T (f) /Parent {g} /V {sig} >>",
        },
        ["g"],
        ("f", "FT", "xref"),
        True,
    ),
    (
        "indirect_text_type_under_an_inherited_sig_with_v_on_its_kid_invariant",
        {
            "ft": "/Tx",
            "g": "<< /FT /Sig /T (g) /Kids [{f}] >>",
            "f": "<< /FT {ft} /T (f) /Parent {g} /Kids [{k}] >>",
            "k": "<< /Subtype /Widget /Parent {f} /V (hello) >>",
        },
        ["g"],
        ("k", "FT", "null"),
        True,
    ),
    # --- pins: answers that must not move
    (
        "direct_sig_with_v",
        {"sig": SIG, "w": "<< /FT /Sig /T (w) /V {sig} >>"},
        ["w"],
        ("w", "FT", "name"),
        True,
    ),
    ("direct_sig_without_v", {"w": "<< /FT /Sig /T (w) >>"}, ["w"], ("w", "FT", "name"), False),
    (
        "indirect_ft_naming_sig_without_v",
        {"ft": "/Sig", "w": "<< /FT {ft} /T (w) >>"},
        ["w"],
        ("w", "FT", "xref"),
        False,
    ),
    (
        "indirect_ft_naming_tx_with_v",
        {"ft": "/Tx", "w": "<< /FT {ft} /T (w) /V (hello) >>"},
        ["w"],
        ("w", "FT", "xref"),
        False,
    ),
    (
        # An inherited /Sig already decides the type; an unreadable own /FT
        # adds nothing to resolve, and nothing on the chain carries /V.
        "unreadable_ft_under_an_inherited_sig_without_v",
        {"g": "<< /FT /Sig /T (g) /Kids [{f}] >>", "f": "<< /FT 5 /T (f) /Parent {g} >>"},
        ["g"],
        ("f", "FT", "int"),
        False,
    ),
    (
        "text_field_with_widget_kids",
        {
            "p": "<< /FT /Tx /T (p) /V (hello) /Kids [{k1} {k2}] >>",
            "k1": "<< /Subtype /Widget /Parent {p} >>",
            "k2": "<< /Subtype /Widget /Parent {p} >>",
        },
        ["p"],
        ("k1", "FT", "null"),
        False,
    ),
    (
        "text_widget_listed_alone_with_v_on_its_parent",
        {
            "p": "<< /FT /Tx /T (p) /V (hello) /Kids [{w}] >>",
            "w": "<< /FT /Tx /Subtype /Widget /Parent {p} >>",
        },
        ["w"],
        ("w", "V", "null"),
        False,
    ),
    ("button_field", {"w": "<< /FT /Btn /T (w) /V /Yes >>"}, ["w"], ("w", "FT", "name"), False),
    (
        "no_ft_anywhere",
        {"p": "<< /T (p) /Kids [{w}] >>", "w": "<< /T (w) /Parent {p} /V (hello) >>"},
        ["w"],
        ("p", "FT", "null"),
        False,
    ),
    (
        "unsigned_placeholder_inheriting_sig_from_its_parent",
        {"p": "<< /FT /Sig /T (p) /Kids [{w}] >>", "w": "<< /Subtype /Widget /Parent {p} >>"},
        ["w"],
        ("w", "FT", "null"),
        False,
    ),
    (
        "unsigned_sig_widget_under_an_unlisted_sig_parent",
        {
            "p": "<< /FT /Sig /T (p) /Kids [{w}] >>",
            "w": "<< /FT /Sig /Subtype /Widget /Parent {p} >>",
        },
        ["w"],
        ("p", "V", "null"),
        False,
    ),
    (
        "unsigned_sig_widget_two_parents_up_without_v",
        {
            "g": "<< /T (g) /Kids [{p}] >>",
            "p": "<< /FT /Sig /T (p) /Parent {g} /Kids [{w}] >>",
            "w": "<< /FT /Sig /Subtype /Widget /Parent {p} >>",
        },
        ["g"],
        ("g", "V", "null"),
        False,
    ),
    (
        "unsigned_sig_placeholder_with_a_parent_cycle",
        {"w": "<< /FT /Sig /T (w) /Parent {p} >>", "p": "<< /T (p) /Parent {w} >>"},
        ["w"],
        ("p", "Parent", "xref"),
        False,
    ),
    (
        "unsigned_sig_placeholder_with_a_dangling_parent",
        {"w": "<< /FT /Sig /T (w) /Parent 9999 0 R >>"},
        ["w"],
        ("w", "Parent", "xref"),
        False,
    ),
    (
        "unsigned_sig_placeholder_under_a_non_dictionary_parent",
        {"n": "5", "w": "<< /FT /Sig /T (w) /Parent {n} >>"},
        ["w"],
        ("w", "Parent", "xref"),
        False,
    ),
    (
        "unsigned_sig_placeholder_value_walk_at_the_bound",
        _chain(32, "", leaf="/FT /Sig"),
        ["w"],
        ("a31", "Parent", "null"),
        False,
    ),
    (
        "parent_cycle",
        {"a": "<< /T (a) /Parent {b} /V (hello) >>", "b": "<< /T (b) /Parent {a} >>"},
        ["a"],
        ("b", "Parent", "xref"),
        False,
    ),
    ("self_parent", {"a": "<< /T (a) /Parent {a} >>"}, ["a"], ("a", "Parent", "xref"), False),
    (
        "dangling_parent_reference",
        {"w": "<< /T (w) /Parent 9999 0 R /V (hello) >>"},
        ["w"],
        ("w", "Parent", "xref"),
        False,
    ),
    ("parent_chain_within_the_bound_without_ft", _chain(20, ""), ["w"], ("a19", "FT", "null"), False),
]


@pytest.mark.parametrize(
    ("objects", "fields", "shape", "expected"),
    [case[1:] for case in _CASES],
    ids=[case[0] for case in _CASES],
)
def test_signature_field_type_is_read_fail_closed(
    tmp_path, objects, fields, shape, expected
) -> None:
    doc, xrefs = _open_form(tmp_path, objects, fields)
    try:
        name, key, kind = shape
        assert doc.xref_get_key(xrefs[name], key)[0] == kind, "fixture shape did not survive the save"
        # A cycle must terminate: only the probe runs (no widget is loaded).
        assert document_has_a_signed_signature(doc) is expected
    finally:
        doc.close()


def test_an_indirect_sig_type_refuses_text_edits_on_a_page_without_widgets(tmp_path) -> None:
    """The text-edit gate shares the probe: page 2 carries no widget at all."""
    doc, xrefs = _open_form(
        tmp_path, {"ft": "/Sig", "sig": SIG, "w": "<< /FT {ft} /T (s) /V {sig} >>"}, ["w"]
    )
    try:
        assert doc.xref_get_key(xrefs["w"], "FT")[0] == "xref"
        assert list(doc[1].annot_xrefs()) == []
        assert page_has_widgets_or_signatures(doc, doc[1]) is True
    finally:
        doc.close()


def test_a_value_on_a_signature_widgets_parent_refuses_text_edits_on_a_page_without_widgets(
    tmp_path,
) -> None:
    """The same gate for R1b: the signature value sits only on the unlisted parent."""
    doc, xrefs = _open_form(
        tmp_path,
        {
            "sig": SIG,
            "p": "<< /FT /Sig /T (p) /V {sig} /Kids [{w}] >>",
            "w": "<< /FT /Sig /Subtype /Widget /Parent {p} >>",
        },
        ["w"],
    )
    try:
        assert doc.xref_get_key(xrefs["w"], "V")[0] == "null"
        assert list(doc[1].annot_xrefs()) == []
        assert page_has_widgets_or_signatures(doc, doc[1]) is True
    finally:
        doc.close()
