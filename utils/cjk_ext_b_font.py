"""CJK Ext-B glyphs for htmlbox inserts: an in-memory subset of a Windows Ext-B font.

PyMuPDF 1.27's ``insert_htmlbox`` has no font for CJK Ideographs Extension B
and later (U+20000 and up, planes 2 and 3) and draws ``.notdef`` for them.  Owner
decision C on OD-UNI1-COMMIT (round 11, EXTB-SUBSET): draw them with a Windows
Ext-B font, subset IN MEMORY to only the glyphs the insert needs (embedding the
whole font would add 11.7 MB / 17.2 MB to every saved file).

``ext_b_htmlbox_resources(html)`` returns the markup with every Ext-B run (in
text nodes only) wrapped in its own ``<span style="font-family: ...">``, the
``@font-face`` rules and the subset font programs to hand to htmlbox through an
in-memory ``fitz.Archive``.  ``htmlbox_args_with_ext_b(html, kwargs)`` packages
that into the ``(html, kwargs)`` a ``Page.insert_htmlbox`` call needs.
``model.font_stream_compaction.insert_htmlbox_tracked`` -- the model's one
htmlbox chokepoint -- applies it to every insert, so the rebuild's real insert,
its protected-span replays, push-down replays and the scratch reference renders
its verification compares against are all drawn the same way; the editor's live
preview (``view/text_editing.py``, which may not import ``model``) calls the same
helper (S12-EXTB-PREVIEW), and an AST guard in ``test_font_stream_compaction.py``
requires it of every ``insert_htmlbox`` call in ``view/``, ``controller/`` and
``utils/``.

Font choice (candidates in preference order, picked per character):

1. SimSun-ExtB (``simsunb.ttf``): a single-face TrueType file covering 60,349
   code points at U+20000 and above (all of Ext-B plus Ext-C to Ext-F, up to
   U+2EBE0).
2. MingLiU-ExtB (``mingliub.ttc`` face 0): 47,095 such code points; used for
   the 11 compatibility ideographs SimSun-ExtB lacks (U+2F825, ...) and when
   ``simsunb.ttf`` is missing.

The two draw near-identical Ming/Song shapes.  Both carry OS/2 ``fsType`` 0x8
(editable embedding; subsetting not restricted), which is what embedding a
subset in a PDF needs.  Both the system Fonts folder and the per-user one
(``%LOCALAPPDATA%/Microsoft/Windows/Fonts``, where a no-admin install lands;
F13-ENV-2) are searched, the system copy first; a font registered elsewhere
through ``HKCU`` is not followed.  Not on Windows, or with neither file
installed, nothing is wrapped: htmlbox draws ``.notdef`` and the rebuild verification refuses,
naming the fonts (``MISSING_FONT_HINT``).

Each subset gets a deterministic PostScript name ``PdfEditorExtB-<key>-<hash>``
(at most 31 characters: MuPDF keeps 31 of a font name) derived from the font
and the code points it holds, so two different subsets on one page never share
``(font name, glyph id)`` keys, and ``FONT_NAME_PREFIX`` identifies their glyphs
in ``get_texttrace`` (whose 16-bit cut of the code point -- U+20000 becomes
U+2000, a space -- must not hide them from glyph evidence).

The text layer of what is drawn this way stays lossy: htmlbox writes the code
point cut to 16 bits (U+20B9F -> U+20B9) -- accepted limitation, TODOS
OD-UNI1-COMMIT.

Live preview off the GUI thread (S14-EXTB-PREVIEW-WORKER, owner decision C on
F13-EXTB-PERF-1): a NEW character set costs 0.12-0.25 s of fontTools work (cmap
load, subset, save).  The editor's preview therefore asks
``htmlbox_args_with_ext_b(..., cached_only=True)``, which only reads the caches
and raises ``ExtBSubsetNotReady`` instead of computing; a ``QThread`` worker
(``view/ext_b_subset_worker.py``) calls ``warm_ext_b_subsets(html)`` to fill them
and the preview re-renders.  The caches are thread-safe (``_PeekCache``).  The
commit path keeps computing synchronously: it runs once per Apply, not once per
pause in typing.

``fontTools`` is imported lazily, here only (pinned by
``test_layer_boundaries.test_fonttools_is_imported_only_by_the_ext_b_subsetter``).
Qt-free.

A ``fontTools`` that cannot be imported (a venv made before it became a runtime
dependency, a partial install) is a broken program, not a font without the
glyphs: ``fonttools_import_error()`` / ``ext_b_component_missing()`` tell the
two apart, nothing is cached as "no coverage" while the import fails, the cause
is logged once at ERROR, and the rebuild refusal is ``EXT_B_COMPONENT_MISSING``
("reinstall the program") instead of "use other characters" (F13-ENV-3).
"""
from __future__ import annotations

import functools
import hashlib
import importlib
import io
import itertools
import logging
import os
import re
import sys
import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, NamedTuple, TypeVar

logger = logging.getLogger(__name__)

EXT_B_FIRST = 0x20000
EXT_B_LAST = 0x3FFFF  # planes 2 (SIP) and 3 (TIP)
FONT_NAME_PREFIX = "PdfEditorExtB-"
_MAX_FONT_NAME = 31

COMPONENT_MISSING_HINT = (
    "the CJK Ext-B font library fontTools cannot be imported (the installation "
    "is incomplete or broken; reinstall the program's requirements)"
)

MISSING_FONT_HINT = (
    "CJK Ext-B needs the Windows font SimSun-ExtB (simsunb.ttf) or "
    "MingLiU-ExtB (mingliub.ttc), and neither is installed"
)

# (file name in the Windows Fonts directory, collection face index, key).
_CANDIDATES: tuple[tuple[str, int, str], ...] = (
    ("simsunb.ttf", 0, "SimSun"),
    ("mingliub.ttc", 0, "MingLiU"),
)

_EXT_B_RUN = re.compile(f"[{chr(EXT_B_FIRST)}-{chr(EXT_B_LAST)}]+")  # one run of Ext-B characters
_TAG_SPLIT = re.compile(r"(<[^>]*>)")


_V = TypeVar("_V")


class _CacheInfo(NamedTuple):
    hits: int
    misses: int
    maxsize: int
    currsize: int


class _PeekCache(Generic[_V]):
    """A small thread-safe LRU like ``functools.lru_cache`` that can also be
    *peeked*: ``peek(*key)`` answers from the cache without ever computing, which
    is how the GUI thread learns that a subset is (not) ready without paying for
    it (S14-EXTB-PREVIEW-WORKER).  The compute runs outside the lock, so a
    second thread asking for the same key meanwhile computes it too (harmless:
    both store equal values)."""

    def __init__(self, fn: Callable[..., _V], maxsize: int) -> None:
        self._fn = fn
        self._maxsize = maxsize
        self._lock = threading.Lock()
        self._data: OrderedDict[tuple[Any, ...], _V] = OrderedDict()
        self._hits = 0
        self._misses = 0
        functools.update_wrapper(self, fn)

    def __call__(self, *key: Any) -> _V:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                self._hits += 1
                return self._data[key]
            self._misses += 1
        value = self._fn(*key)
        with self._lock:
            self._data[key] = value
            self._data.move_to_end(key)
            while len(self._data) > self._maxsize:
                self._data.popitem(last=False)
        return value

    def peek(self, *key: Any) -> _V | None:
        """The cached value, or ``None`` (a miss); never computes, never counts."""
        with self._lock:
            return self._data.get(key)

    def cache_clear(self) -> None:
        with self._lock:
            self._data.clear()
            self._hits = 0
            self._misses = 0

    def cache_info(self) -> _CacheInfo:
        with self._lock:
            return _CacheInfo(self._hits, self._misses, self._maxsize, len(self._data))


def _peek_cache(maxsize: int) -> Callable[[Callable[..., _V]], _PeekCache[_V]]:
    def wrap(fn: Callable[..., _V]) -> _PeekCache[_V]:
        return _PeekCache(fn, maxsize)

    return wrap


class ExtBSubsetNotReady(Exception):
    """``cached_only=True`` found a font coverage table or subset it would have
    to compute (fontTools work that does not belong on the GUI thread)."""


def _cache_lookup(cache: _PeekCache[_V], key: tuple[Any, ...], what: str, cached_only: bool) -> _V:
    """``cache(*key)``, or with ``cached_only`` the cached value alone
    (``ExtBSubsetNotReady`` on a miss: the GUI thread never computes)."""
    if not cached_only:
        return cache(*key)
    hit = cache.peek(*key)
    if hit is None:
        raise ExtBSubsetNotReady(f"{what} is not cached")
    return hit


@dataclass(frozen=True)
class ExtBFont:
    """One installed Ext-B font face."""

    path: Path
    font_number: int
    key: str  # short label used in the subset's font name


@dataclass(frozen=True)
class ExtBResources:
    """What an htmlbox insert needs to draw the Ext-B characters of a markup."""

    html: str  # the markup with Ext-B runs wrapped in their own spans
    css: str  # the @font-face rules for the subset fonts
    members: tuple[tuple[str, bytes], ...]  # (archive member name, font program)


def is_ext_b(ch: str) -> bool:
    """True for one character in U+20000..U+3FFFF."""
    if not isinstance(ch, str) or len(ch) != 1:
        raise TypeError(f"is_ext_b needs one character, got {ch!r}")
    return EXT_B_FIRST <= ord(ch) <= EXT_B_LAST


def _fonts_dir() -> Path:
    root = os.environ.get("WINDIR") or os.environ.get("SystemRoot") or "C:\\Windows"
    return Path(root) / "Fonts"


def _per_user_fonts_dir() -> Path | None:
    """Where Windows 10 1809+ puts a font installed without admin rights
    (double-click > Install): ``%LOCALAPPDATA%\\Microsoft\\Windows\\Fonts``
    (F13-ENV-2).  ``None`` when ``LOCALAPPDATA`` is unset."""
    root = os.environ.get("LOCALAPPDATA")
    if not root:
        return None
    return Path(root) / "Microsoft" / "Windows" / "Fonts"


def _font_dirs() -> tuple[Path, ...]:
    """Every folder an installed font can live in, system-wide first (a
    system copy wins over a per-user copy of the same file)."""
    per_user = _per_user_fonts_dir()
    return (_fonts_dir(),) if per_user is None else (_fonts_dir(), per_user)


def _on_windows() -> bool:
    return sys.platform == "win32"


def find_ext_b_fonts() -> tuple[ExtBFont, ...]:
    """The installed candidate Ext-B fonts, in preference order (empty off
    Windows or when neither file exists).  Looks in the system Fonts folder and
    then the per-user one, so a no-admin install counts (F13-ENV-2)."""
    if not _on_windows():
        return ()
    found: list[ExtBFont] = []
    for name, index, key in _CANDIDATES:  # one entry per candidate: the first folder with it
        for fonts_dir in _font_dirs():
            if (fonts_dir / name).is_file():
                found.append(ExtBFont(fonts_dir / name, index, key))
                break
    return tuple(found)


def _stamp(font: ExtBFont) -> tuple[int, int] | None:
    try:
        st = font.path.stat()
    except OSError:
        return None
    return int(st.st_size), int(st.st_mtime_ns)


def fonttools_import_error() -> str | None:
    """``None`` when every fontTools module the Ext-B path needs imports, else
    ``"<ExceptionType>: <message>"``.  Uncached on purpose: a failure must not
    outlive the cause (the import system answers a repeat in microseconds)."""
    try:
        # import_module, not ``from fontTools import subset``: the latter finds
        # an already-bound package attribute without consulting sys.modules.
        for name in ("fontTools.ttLib", "fontTools.subset"):
            importlib.import_module(name)
    except ImportError as exc:  # ModuleNotFoundError included
        return f"{type(exc).__name__}: {exc}"
    return None


@functools.lru_cache(maxsize=8)
def _log_component_missing(detail: str) -> None:
    """One ERROR per distinct failure (the lookups run per code point)."""
    logger.error(
        "CJK Ext-B rendering disabled, fontTools unavailable (broken install): %s", detail
    )


def _fonttools_ready() -> bool:
    detail = fonttools_import_error()
    if detail is None:
        return True
    _log_component_missing(detail)
    return False


def ext_b_component_missing() -> bool:
    """True when an Ext-B font IS installed but fontTools cannot be imported, so
    every Ext-B character would be misreported as "the font has no glyph".
    With no font installed the install-the-fonts advice comes first."""
    return bool(find_ext_b_fonts()) and fonttools_import_error() is not None


@_peek_cache(maxsize=8)
def _coverage_cached(path: str, font_number: int, stamp: tuple[int, int]) -> frozenset[int]:
    try:
        from fontTools.ttLib import TTFont

        font = TTFont(path, fontNumber=font_number, lazy=True)
        try:
            cmap = font.getBestCmap() or {}
        finally:
            font.close()
    except Exception:
        logger.warning("CJK Ext-B font unreadable, not used: %s", path, exc_info=True)
        return frozenset()
    return frozenset(cp for cp in cmap if EXT_B_FIRST <= cp <= EXT_B_LAST)


def _coverage(font: ExtBFont, *, cached_only: bool = False) -> frozenset[int]:
    """The Ext-B code points ``font`` has a glyph for.  ``cached_only``: from the
    cache alone, ``ExtBSubsetNotReady`` on a miss.  A font whose file is gone has
    no coverage, cached or not (no raise)."""
    stamp = _stamp(font)
    if stamp is None or (not cached_only and not _fonttools_ready()):
        return frozenset()  # a broken install is never cached as "no coverage"
    key = (str(font.path), font.font_number, stamp)
    return _cache_lookup(_coverage_cached, key, f"coverage of {font.path}", cached_only)


def _coverage_table(
    fonts: tuple[ExtBFont, ...], *, cached_only: bool = False
) -> dict[ExtBFont, frozenset[int]]:
    """``{font: its Ext-B coverage}`` in preference order (``_coverage`` once per font)."""
    return {font: _coverage(font, cached_only=cached_only) for font in fonts}


def _first_font_with(cp: int, coverage: dict[ExtBFont, frozenset[int]]) -> ExtBFont | None:
    """The first font of a ``_coverage_table`` (preference order) that has ``cp``."""
    return next((font for font, cps in coverage.items() if cp in cps), None)


def font_for_codepoint(cp: int) -> ExtBFont | None:
    """The first installed candidate font that has a glyph for ``cp``."""
    return _first_font_with(cp, _coverage_table(find_ext_b_fonts()))


def uncovered_ext_b(text: str) -> list[str]:
    """``U+XXXXX`` labels (first-seen order, no repeats) of the Ext-B
    characters of ``text`` that no installed Ext-B font draws."""
    wanted = [cp for cp in dict.fromkeys(map(ord, text or "")) if EXT_B_FIRST <= cp <= EXT_B_LAST]
    if not wanted:
        return []  # plain text touches no font (and logs nothing: F13-ENV-3)
    coverage = _coverage_table(find_ext_b_fonts())  # one lookup per text, not per character
    return [f"U+{cp:04X}" for cp in wanted if _first_font_with(cp, coverage) is None]


def ext_b_refusal_reason(text: str) -> str | None:
    """Why the Ext-B characters of ``text`` cannot be drawn (the clause the
    rebuild refusal carries), or ``None`` when every one has a font."""
    labels = ", ".join(uncovered_ext_b(text))
    if not labels:
        return None
    if not find_ext_b_fonts():
        return f"{MISSING_FONT_HINT}: {labels}"
    import_error = fonttools_import_error()  # a font is installed: ``ext_b_component_missing``
    if import_error is not None:
        return f"{COMPONENT_MISSING_HINT} [{import_error}]: {labels}"
    return (
        "the installed CJK Ext-B fonts (SimSun-ExtB simsunb.ttf / MingLiU-ExtB "
        f"mingliub.ttc) have no glyph for {labels}"
    )


def ext_b_install_would_help() -> bool:
    """True when the user can fix an undrawable Ext-B character by installing
    the system Ext-B fonts: on Windows with neither candidate installed.  With a
    font installed that simply lacks the glyph (Ext-G and later), or off Windows
    where no font is ever looked up, installing changes nothing, so the dialog
    must not ask for it (F12-DLG-4)."""
    return _on_windows() and not find_ext_b_fonts()


def _subset_name(font: ExtBFont, codepoints: tuple[int, ...]) -> str:
    digest = hashlib.sha1(
        (font.key + ":" + ",".join(f"{cp:X}" for cp in codepoints)).encode("ascii")
    ).hexdigest()[:8]
    name = f"{FONT_NAME_PREFIX}{font.key}-{digest}"
    assert len(name) <= _MAX_FONT_NAME, name
    return name


@_peek_cache(maxsize=64)
def _subset_cached(
    path: str,
    font_number: int,
    stamp: tuple[int, int],
    codepoints: tuple[int, ...],
    ps_name: str,
) -> bytes:
    from fontTools import subset
    from fontTools.ttLib import TTFont

    options = subset.Options()
    options.hinting = False
    options.layout_features = []
    options.notdef_outline = True
    options.name_IDs = ["*"]
    options.drop_tables = list(options.drop_tables) + ["meta"]
    font = TTFont(path, fontNumber=font_number, lazy=True)
    try:
        subsetter = subset.Subsetter(options)
        subsetter.populate(unicodes=codepoints)
        subsetter.subset(font)
        name_table = font["name"]
        for record in name_table.names:
            if record.nameID == 6:
                record.string = ps_name
        name_table.setName(ps_name, 6, 3, 1, 0x409)
        buffer = io.BytesIO()
        font.save(buffer)
        return buffer.getvalue()
    finally:
        font.close()


def _wrap_text_node(text: str, families: dict[int, str]) -> str:
    def wrap(match: re.Match[str]) -> str:
        out: list[str] = []
        for family, chars in itertools.groupby(match.group(0), key=lambda ch: families.get(ord(ch))):
            chunk = "".join(chars)
            if family is None:
                out.append(chunk)  # no font has it: htmlbox draws .notdef
            else:
                out.append(f'<span style="font-family: {family};">{chunk}</span>')
        return "".join(out)

    return _EXT_B_RUN.sub(wrap, text)


def ext_b_htmlbox_resources(html: str, *, cached_only: bool = False) -> ExtBResources | None:
    """The markup, ``@font-face`` rules and subset fonts that let htmlbox draw
    the Ext-B characters in ``html``'s text nodes, or ``None`` when there is
    nothing to wrap (no Ext-B character, or no installed font has any of
    them).  Characters no installed font has are left as they are.

    ``cached_only=True`` never computes: a font coverage table or subset that is
    not already cached raises ``ExtBSubsetNotReady`` (the GUI thread's way to ask;
    ``warm_ext_b_subsets`` fills the caches on a worker)."""
    if not isinstance(html, str):
        raise TypeError(f"ext_b_htmlbox_resources needs str markup, got {type(html).__name__}")
    if not _EXT_B_RUN.search(html):
        return None
    parts = _TAG_SPLIT.split(html)  # text nodes at the even indexes, tags at the odd
    wanted = sorted({ord(ch) for part in parts[::2] for run in _EXT_B_RUN.findall(part) for ch in run})
    if not wanted:
        return None
    fonts = find_ext_b_fonts()
    coverage = _coverage_table(fonts, cached_only=cached_only)
    # Each code point goes to the first font (preference order) that has it.
    per_font: dict[ExtBFont, list[int]] = {font: [] for font in fonts}
    for cp in wanted:
        font = _first_font_with(cp, coverage)
        if font is not None:
            per_font[font].append(cp)
    families: dict[int, str] = {}
    members: list[tuple[str, bytes]] = []
    rules: list[str] = []
    for font, assigned in per_font.items():
        codepoints = tuple(assigned)
        stamp = _stamp(font)
        if not codepoints or stamp is None:
            continue
        name = _subset_name(font, codepoints)
        key = (str(font.path), font.font_number, stamp, codepoints, name)
        try:
            data = _cache_lookup(_subset_cached, key, f"subset {name}", cached_only)
        except ExtBSubsetNotReady:
            raise
        except ImportError:
            _log_component_missing(fonttools_import_error() or "ImportError")
            continue
        except Exception:
            logger.warning("CJK Ext-B subset of %s failed", font.path, exc_info=True)
            continue
        member = f"{name}.ttf"
        members.append((member, data))
        rules.append(f'@font-face {{ font-family: "{name}"; src: url({member}); }}')
        families.update((cp, name) for cp in codepoints)
    if not members:
        return None
    wrapped = "".join(
        _wrap_text_node(part, families) if index % 2 == 0 else part
        for index, part in enumerate(parts)
    )
    return ExtBResources(html=wrapped, css="\n".join(rules), members=tuple(members))


def warm_ext_b_subsets(html: str) -> None:
    """Compute (and cache) every font coverage table and subset ``html`` needs, so
    a following ``cached_only=True`` call succeeds.  This is the slow part
    (0.12-0.25 s); call it from a worker thread, never from the GUI thread.  Thread
    safe; a failing subset is logged, as in ``ext_b_htmlbox_resources``."""
    ext_b_htmlbox_resources(html)


def htmlbox_args_with_ext_b(
    html: str, kwargs: dict[str, Any], *, cached_only: bool = False
) -> tuple[str, dict[str, Any]]:
    """``(html, kwargs)`` ready for ``page.insert_htmlbox(rect, html, **kwargs)``.

    Ext-B runs of ``html`` are wrapped in their own spans, the subset
    ``@font-face`` rules are put in front of ``kwargs["css"]`` and the subset
    font programs are added to an in-memory ``fitz.Archive`` (merged with a
    caller-supplied ``kwargs["archive"]``).  ``kwargs`` is never mutated; with
    nothing to wrap the markup is returned unchanged with a plain copy.
    ``TypeError`` for non-``str`` markup.

    ``cached_only=True`` is for the GUI thread: it never runs fontTools and
    raises ``ExtBSubsetNotReady`` when the Ext-B subsets ``html`` needs are not
    cached yet (markup without Ext-B characters is never "not ready").
    """
    out = dict(kwargs)
    resources = ext_b_htmlbox_resources(html, cached_only=cached_only)
    if resources is None:
        return html, out
    import fitz

    out["css"] = resources.css + "\n" + (out.get("css") or "")
    archive = fitz.Archive()
    for member, data in resources.members:
        archive.add(data, member)
    if out.get("archive") is not None:
        archive.add(out["archive"])
    out["archive"] = archive
    return resources.html, out
