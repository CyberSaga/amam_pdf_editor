"""Staging-file names beside a save target (Windows path-length safe).

A save that must stay atomic stages its bytes in the *target's own directory*
(``os.replace`` across volumes is not atomic).  The staging name used to embed
the target's stem plus a 32-hex uuid, so it was 38-42 characters longer than
the target itself: a target the user could open and edit at, say, 235
characters produced a 277-character sibling, past the 260-character
``MAX_PATH`` that default Windows (``LongPathsEnabled=0``) enforces for the
ANSI-style paths ``shutil``/``os`` hand to the OS, and a stem past ~209
characters overflowed the 255-character component limit even with long paths
enabled.  ``staging_sibling`` therefore (1) never derives the name from the
stem, and (2) falls back to the ``\\\\?\\`` extended-length form when the
resulting path would still not fit.
"""

from __future__ import annotations

import gc
import os
import uuid
from collections.abc import Callable
from pathlib import Path

from utils import file_share_lock

# Windows MAX_PATH (260) counts the terminating NUL: a file path may hold 259.
WIN_MAX_FILE_PATH = 259
_EXTENDED_PREFIX = "\\\\?\\"
_EXTENDED_UNC_PREFIX = "\\\\?\\UNC\\"


def extended_length_path(path: str | os.PathLike[str]) -> str:
    """``path`` in ``\\\\?\\`` form when it is too long for the legacy API.

    No-op off Windows, for short paths and for paths already in extended form.
    The path is made absolute first (the prefix disables ``.``/``..``
    normalisation and relative lookup).
    """
    text = os.fspath(path)
    if os.name != "nt" or len(text) <= WIN_MAX_FILE_PATH or text.startswith(_EXTENDED_PREFIX):
        return text
    absolute = os.path.abspath(text)
    if absolute.startswith("\\\\"):  # UNC share: \\server\share\... -> \\?\UNC\server\share\...
        return _EXTENDED_UNC_PREFIX + absolute[2:]
    return _EXTENDED_PREFIX + absolute


def strip_extended_prefix(path: str | os.PathLike[str]) -> str:
    """``path`` without its extended-length prefix (the inverse of ``extended_length_path``).

    ``Path.resolve()`` keeps the prefix of a path too long for the legacy API
    and drops it for a short one, so two spellings of one file differ; strip
    both before comparing.  The UNC extended form goes back to the plain
    ``//server/share`` style share path.
    """
    text = os.fspath(path)
    if text.startswith(_EXTENDED_UNC_PREFIX):
        return "\\\\" + text[len(_EXTENDED_UNC_PREFIX):]
    if text.startswith(_EXTENDED_PREFIX):
        return text[len(_EXTENDED_PREFIX):]
    return text


def resolve_as_requested(path: str | os.PathLike[str]) -> Path:
    """``Path.resolve()`` that keeps the spelling of the name the caller asked for.

    ``resolve()`` returns the *on-disk* case of an existing file, so installing
    over ``resolve(path)`` renames nothing when the request only differs in case
    (``a.pdf`` -> ``A.pdf`` on a case-insensitive file system): the user asked
    for a name and the file keeps the old one (F10-FS-3).  ``os.replace`` onto
    the typed spelling gives the file that spelling.  Only a difference that
    ``os.path.normcase`` erases is restored; a symlink (whose resolved name is
    the link target's), an 8.3 form or a stripped trailing dot keep the
    resolved name.  Comparisons of "is this the same file" stay on plain
    ``resolve()`` (``Path`` equality is case-insensitive on Windows).
    """
    requested = Path(path)
    resolved = requested.resolve()
    if _differs_only_by_case(requested, resolved):
        return resolved.with_name(requested.name)
    return resolved


def _differs_only_by_case(requested: Path, resolved: Path) -> bool:
    return bool(
        requested.name
        and resolved.name != requested.name
        and os.path.normcase(resolved.name) == os.path.normcase(requested.name)
        and not requested.is_symlink()
    )


def on_disk_spelling(path: str | os.PathLike[str]) -> str:
    """``path`` with its last component spelled as the file is stored on disk.

    The inverse of ``resolve_as_requested`` for a path that is NOT a typed
    request: a save that replays the session's *stored* path (Ctrl+S sends
    ``saved_path or original_path``) carries no spelling the user chose, and
    that stored spelling is stale once another program renamed the file by
    case (Explorer ``report.pdf`` -> ``Report.pdf``); installing over it renamed
    the file back (F11-FS-3).  Only a difference ``os.path.normcase`` erases is
    adopted; any other path (missing file, symlink, a real different name) is
    returned untouched, and so is the directory part.
    """
    requested = Path(path)
    try:
        resolved = requested.resolve()
    except OSError:
        return os.fspath(path)
    if _differs_only_by_case(requested, resolved):
        return os.fspath(requested.with_name(resolved.name))
    return os.fspath(path)


def staging_sibling(target: str | os.PathLike[str], tag: str) -> Path:
    """A hidden, unique staging path in the same directory as ``target``.

    The name is ``.<12 hex>.<tag>.pdf``: about 25 characters whatever the
    target's stem, so a long stem can no longer push the sibling past the
    255-character component limit, and it still starts with ``.`` (hidden;
    recognisable as a leftover).  If the full path would exceed the legacy
    Windows limit (a long directory) it is returned in extended-length form; a
    ``Path``/``str`` of that form works with ``open``, ``shutil``,
    ``os.replace`` and MuPDF alike.
    """
    parent = Path(target).parent
    name = f".{uuid.uuid4().hex[:12]}.{tag}.pdf"
    return Path(extended_length_path(parent / name))


def replace_file(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
    """``os.replace`` that survives a handle held only by uncollected garbage.

    On Windows an open file handle blocks the replace (``PermissionError``,
    WinError 5/32).  The handle is often not a live document but PyMuPDF
    Page<->Annot reference-cycle garbage (``Page.first_annot`` / ``Annot.next``
    register every walked annotation in a strong ``Page._annot_refs`` dict
    while the annotation holds a strong parent page): ``Document.close`` does
    not release it, so the MuPDF file stream stays open until the cyclic GC
    runs.  A failed replace therefore collects once and retries once; a lock
    that survives the collection is real and is re-raised.  The happy path
    never pays for a collection (R10 MBT-1).

    This process's own deny-write share lock on ``dst`` (an open session's
    file, ``utils.file_share_lock``, OD-FS1-LOCK) is suspended for the install
    and re-taken on the installed file, whichever window holds it.
    """
    with file_share_lock.suspended(dst):
        try:
            os.replace(src, dst)
        except PermissionError:
            gc.collect()
            os.replace(src, dst)


def write_via_staging(
    target: str | os.PathLike[str],
    write: Callable[[str], None],
    tag: str = "save",
) -> None:
    """Produce ``target`` by writing a sibling staging file and ``os.replace``-ing it.

    ``write(stage_path)`` serialises into the staging file; only after it
    returned is the stage installed over ``target`` (atomic on one volume), so a
    writer that dies half way (disk full, an exception, a killed process)
    leaves an existing ``target`` byte-identical instead of truncated, and
    leaves no partial file at a new path either.  A symlinked ``target`` is
    resolved first, so the link's file is the one replaced.  The staging file
    is removed on any failure.  Use it for every write whose destination is a
    path the user chose and that may already hold their last good file.
    """
    resolved = resolve_as_requested(target)
    stage = staging_sibling(resolved, tag)
    try:
        write(str(stage))
        replace_file(stage, resolved)
    finally:
        try:
            stage.unlink(missing_ok=True)
        except OSError:
            pass
