"""Accelerated scanner F (design plan 4.2 "F after S0", card B4): numpy over whole token arrays.

F equals scanner G on every column.  Strings, hex strings, dictionaries, arrays and comments are masked out of the
bytes first (a string, hex string, dictionary or array becomes one marker byte plus blanks, a comment becomes blanks), so
the tokeniser sees operands in G's order; every word that is not a known operator is a generic operator, as in G.
Not admitted: inline images (BI), the words true, false and null, braces, a string, hex string or container that
crosses a stream start, a byte 1-6 in the data, and any construct G would refuse.  The caller then runs G on
the WHOLE page (_NotAdmitted), so refusals keep G's class, code and first error.  A cancel or a callback error
is never turned into a fallback.

Stages: (1) chunked tokenising on byte classes (forced token breaks at stream starts; a chunk ends at its last
operator); numbers of at most 15 characters are read as an exact mantissa over a power of ten (one correctly
rounded division, then float32), longer ones with G's own checks; (2) per-operator arrays; (3) scopes by
(q depth, position), the CTM by level (plain loop when one scope holds more than 64 cm), sticky state
(width, gs) by level; (4) paths, primitives, chords and boxes in numpy, the arithmetic and its order are G's.
"""

from __future__ import annotations

import array
import hashlib
import math
import re
from collections.abc import Callable, Sequence

import numpy as np

from model.pdf_content_ops import affine_concat
from model.vector_paths import scan as S

_CHUNK = 1 << 20
_MAX_STALL = 64 << 20  # a chunk with no operator that grew this far is not a page F admits
_QUICK = re.compile(rb"[\x01-\x06%()<>\[\]{}]")  # one pass: any byte the mask stage has to look at
_MARK_RE = re.compile(rb"[\x01-\x06]")
_WS_RE = re.compile(rb"[\x00\t\n\x0c\r ]")
_SPECIAL = re.compile(
    rb"%[^\r\n]*+"
    rb"|(\([^()\\]*+(?:\\[\s\S][^()\\]*+)*+\))"
    rb"|(\()"
    rb"|(<<)"
    rb"|(<[^<>]*+>)"
    rb"|(<)"
    rb"|(\[)"
    rb"|([\]{}()>])"
)
_K_STR_DATA, _K_STR, _K_NUMARR, _K_ARR_DATA, _K_ARR, _K_DICT = 1, 2, 3, 4, 5, 6  # marker bytes

_WS = np.zeros(256, np.bool_)
_WS[[0, 9, 10, 12, 13, 32]] = True
_NUMSTART = np.zeros(256, np.bool_)
for _c in b"0123456789+-.":
    _NUMSTART[_c] = True
_MARK = np.zeros(256, np.bool_)
_MARK[1:7] = True
_BRK = _MARK.copy()  # bytes that start a token of their own: a name, a mask marker
_BRK[0x2F] = True

_OPS = [b"q", b"Q", b"cm", b"m", b"l", b"c", b"v", b"y", b"re", b"h", b"w", b"J", b"j", b"M", b"i", b"g", b"G", b"rg", b"RG", b"k", b"K",
        b"gs", b"ri", b"S", b"s", b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*", b"n",
        b"d", b"cs", b"CS", b"sc", b"SC", b"scn", b"SCN", b"W", b"W*", b"BT", b"ET", b"Tr", b"Tj", b"TJ", b"'", b'"',
        b"BDC", b"BMC", b"EMC", b"Do", b"BI"]
Q_, QQ_, CM_, M_, L_, C_, V_, Y_, RE_, H_, W_ = range(11)  # W_ is the line width w, not the clip operator
G_, GU_, RG_, RGU_, K_, KU_ = 15, 16, 17, 18, 19, 20
GS_, RI_, PAINT0, N_ = 21, 22, 23, 32
(D_, CS_, CSU_, SC_, SCU_, SCN_, SCNU_, CLIP_, CLIPS_, BT_, ET_, TR_, TJ_, TJA_, QT_, DQT_, BDC_, BMC_, EMC_, DO_, BI_) = range(33, 54)
OTHER_ = 54  # any other word: a generic operator (G does not interpret it)
NCODE = OTHER_ + 1
_ARITY = np.zeros(NCODE, np.int64)
_ARITY[:23] = [0, 0, 6, 2, 2, 6, 4, 4, 4, 0, 1, 1, 1, 1, 1, 1, 1, 3, 3, 4, 4, 1, 1]
_ARITY[[TR_]] = 1
# operand classes: how the operands of an operator are checked
(C_NUMS, C_NAME1, C_VARNUM, C_SCN, C_STR1, C_ARR1, C_DQ, C_DASH, C_BDC, C_ANY) = range(10)
_CLS = np.full(NCODE, C_NUMS, np.int64)
_CLS[[GS_, RI_, CS_, CSU_, DO_, BMC_]] = C_NAME1
_CLS[[SC_, SCU_]] = C_VARNUM
_CLS[[SCN_, SCNU_]] = C_SCN
_CLS[[TJ_, QT_]] = C_STR1
_CLS[TJA_] = C_ARR1
_CLS[DQT_] = C_DQ
_CLS[D_] = C_DASH
_CLS[BDC_] = C_BDC
_CLS[OTHER_] = C_ANY
_NONPATH = np.ones(NCODE, np.bool_)  # an operator between a path's construction and its paint that makes the record impure
_NONPATH[M_ : H_ + 1] = False
_NONPATH[PAINT0 : N_ + 1] = False
_NONPATH[[CLIP_, CLIPS_]] = False
_NONINERT = np.zeros(NCODE, np.bool_)  # operators outside G's inert allowlist (q and Q are allowed)
_NONINERT[[N_, CLIP_, CLIPS_, BT_, ET_, TR_, TJ_, TJA_, QT_, DQT_, BDC_, BMC_, EMC_, DO_, OTHER_]] = True
_IS_PAINT = np.zeros(NCODE, np.bool_)
_IS_PAINT[PAINT0 : N_ + 1] = True
_CLOSE_PAINT = np.zeros(NCODE, np.bool_)
_CLOSE_PAINT[[24, 30, 31]] = True
_NEEDS_NONNUM = np.isin(_CLS, [C_NAME1, C_STR1, C_ARR1, C_DQ, C_DASH, C_BDC])  # a class that cannot be satisfied by numbers alone
_NUMONLY = np.isin(_CLS, [C_NUMS, C_VARNUM])  # a class that takes numbers and nothing else
_EXACT = _CLS == C_NUMS
_RES_OPS = {GS_: b"gs", CS_: b"cs", CSU_: b"CS", SCN_: b"scn", SCNU_: b"SCN"}  # operators whose name goes to the block resources
_NAMED = np.zeros(NCODE, np.bool_)  # operators whose name operand is read later
_NAMED[[GS_, CS_, CSU_, SCN_, SCNU_, BDC_]] = True


def _key(op: bytes) -> int:
    return op[0] | ((op[1] << 8) if len(op) > 1 else 0) | ((op[2] << 16) if len(op) > 2 else 0) | (min(len(op), 4) << 24)


_KEYS = np.array(sorted(_key(o) for o in _OPS), np.int32)
_KEY_ID = np.array([next(i for i, o in enumerate(_OPS) if _key(o) == k) for k in _KEYS], np.int64)
_OPLEN = np.array([len(o) for o in _OPS] + [0], np.int32)
_POW10I = np.array([10**i for i in range(17)], np.int64)
_POW10F = np.array([10.0**i for i in range(17)], np.float64)
_F32C = array.array("f", [0.0])
_LIM = float(S._MUPDF_REAL_LIMIT)


class _NotAdmitted(Exception):
    """F does not answer this page; G runs on the whole of it."""


# ----------------------------------------------------------------------------- numbers


def _g_number(w: bytes) -> float:
    """G's own reading of one number token longer than 15 characters (both of G's paths)."""
    if len(w) <= 20:
        if S._NUM.fullmatch(w) is None:
            raise _NotAdmitted
        _F32C[0] = float(w)
        v = _F32C[0]
        if (v >= _LIM or v <= -_LIM) and b"." in w:
            raise _NotAdmitted
        return v
    try:
        return S._number(w)
    except S._Bad:
        raise _NotAdmitted from None


def _parse_numbers(b: np.ndarray, st: np.ndarray, ln: np.ndarray) -> np.ndarray:
    out = np.empty(len(st), np.float64)
    short = ln <= 15
    for length in np.unique(ln[short]):
        length = int(length)
        idx = np.flatnonzero(ln == length)
        cols = b[st[idx][:, None] + np.arange(length)]
        isd = (cols >= 48) & (cols <= 57)
        isdot = cols == 46
        c0 = cols[:, 0]
        ok = isd | isdot
        ok[:, 0] |= (c0 == 43) | (c0 == 45)
        if not ok.all():
            raise _NotAdmitted
        nd = isd.sum(1)
        ndot = isdot.sum(1)
        if (nd < 1).any() or (ndot > 1).any():
            raise _NotAdmitted
        d = np.where(isd, cols - 48, 0).astype(np.int64)
        right = np.cumsum(isd[:, ::-1], axis=1)[:, ::-1] - isd  # digits at columns to the right
        mant = (d * _POW10I[right]).sum(1)
        dotcol = isdot.argmax(1)
        fd = np.where(ndot == 1, (isd & (np.arange(length)[None, :] > dotcol[:, None])).sum(1), 0)
        v = mant / _POW10F[fd]
        v = np.where(c0 == 45, -v, v)
        v = v.astype(np.float32).astype(np.float64)
        if ((ndot == 1) & (np.abs(v) >= _LIM)).any():
            raise _NotAdmitted
        out[idx] = v
    for i in np.flatnonzero(~short):
        s0 = int(st[i])
        out[i] = _g_number(bytes(b[s0 : s0 + int(ln[i])]))
    return out


# ----------------------------------------------------------------------------- stage 1 and 2: tokens -> operators


class _Ops:
    def __init__(self) -> None:
        self.code: list[np.ndarray] = []
        self.ts: list[np.ndarray] = []
        self.of: list[np.ndarray] = []
        self.ol: list[np.ndarray] = []
        self.vstart: list[np.ndarray] = []
        self.vals: list[np.ndarray] = []
        self.name_op: list[np.ndarray] = []
        self.name_s: list[np.ndarray] = []
        self.name_e: list[np.ndarray] = []
        self.data: list[np.ndarray] = []
        self.nops = 0
        self.nvals = 0


def _chunk(arr: np.ndarray, lo: int, hi: int, sstarts: np.ndarray, ops: _Ops, final: bool) -> int | None:
    """Tokenise arr[lo:hi]; append the operators found; the offset after the last operator, or None
    (no operator in the chunk; every number in it has been validated)."""
    b = arr[lo:hi]
    nb = hi - lo
    ws = _WS[b]
    tok = ~ws
    brk = _BRK[b]
    prev_tok = np.empty(nb, np.bool_)
    prev_tok[0] = False
    prev_tok[1:] = tok[:-1]
    start = tok & (~prev_tok | brk)
    nxt = np.empty(nb, np.bool_)
    nxt[-1] = True
    nxt[:-1] = ws[1:] | brk[1:]
    end = tok & nxt
    sb = sstarts[(sstarts > lo) & (sstarts < hi)] - lo
    if len(sb):
        start[sb] |= tok[sb]
        end[sb - 1] |= tok[sb - 1]
    st = np.flatnonzero(start)
    en = np.flatnonzero(end) + 1
    ln = en - st
    fb = b[st]
    is_mark = _MARK[fb]
    is_name = fb == 0x2F
    is_num = _NUMSTART[fb]
    is_word = ~(is_name | is_num | is_mark)
    wi = np.flatnonzero(is_word)
    if len(wi) == 0:
        if len(st) > S.MAX_OPERANDS:  # operands with no operator: G refuses at the 4097th
            raise _NotAdmitted
        if len(st):
            nums = np.flatnonzero(is_num)
            if len(nums):
                _parse_numbers(b, st[nums], ln[nums])
        return None
    wst = st[wi]
    lw = ln[wi]
    lw32 = lw.astype(np.int32)
    b1 = b[np.minimum(wst + 1, nb - 1)].astype(np.int32)
    b1[lw32 < 2] = 0
    key = fb[wi].astype(np.int32) | (b1 << 8) | (np.minimum(lw32, 4) << 24)
    big3 = np.flatnonzero(lw32 == 3)  # three-letter words are rare: their third byte joins the key
    if len(big3):
        key[big3] |= b[wst[big3] + 2].astype(np.int32) << 16
    pos = np.minimum(np.searchsorted(_KEYS, key), len(_KEYS) - 1)
    hit = _KEYS[pos] == key
    code = np.where(hit, _KEY_ID[pos], OTHER_)
    if (code == BI_).any():
        raise _NotAdmitted  # an inline image stops G's scan; F leaves it to G
    long4 = np.flatnonzero(lw >= 4)
    if len(long4):
        for wlen, word in ((4, b"true"), (4, b"null"), (5, b"false")):  # operands of their own kind in G
            sel = long4[lw[long4] == wlen]
            if len(sel):
                cols = b[wst[sel][:, None] + np.arange(wlen)]
                if (cols == np.frombuffer(word, np.uint8)).all(axis=1).any():
                    raise _NotAdmitted
    last = int(wi[-1])
    ntok = last + 1
    num_mask = is_num[:ntok]
    nums = np.flatnonzero(num_mask)
    vals = _parse_numbers(b, st[nums], ln[nums]) if len(nums) else np.empty(0, np.float64)
    cn = np.cumsum(num_mask)  # numbers up to and including token i
    prev = np.concatenate(([-1], wi[:-1]))
    nops = wi - prev - 1
    if (nops > S.MAX_OPERANDS).any():
        raise _NotAdmitted
    pc = np.maximum(prev, 0)
    nnum = cn[wi] - np.where(prev >= 0, cn[pc], 0)
    first_tok = prev + 1
    lt = np.maximum(wi - 1, 0)  # the last operand token
    nonnum = nops - nnum  # names and masked operands
    bad = np.where(nonnum == 0, _NEEDS_NONNUM[code], _NUMONLY[code])  # no non-number operand: only a class that needs one is wrong; else only a number class is
    bad |= (nnum != _ARITY[code]) & _EXACT[code]
    data = np.zeros(len(wi), np.bool_)
    nname = np.zeros(len(wi), np.int64)
    sel = np.flatnonzero(nonnum > 0)  # the operators with a name or a masked operand: the rest were judged by their numbers
    if len(sel):
        fbt = fb[:ntok]
        npos = np.flatnonzero(is_name[:ntok])
        ps, ws_ = prev[sel], wi[sel]
        nn = np.searchsorted(npos, ws_) - np.searchsorted(npos, ps)  # names between the previous operator and this one
        nname[sel] = nn
        nm = nonnum[sel] - nn
        cl = _CLS[code[sel]]
        ltk = lt[sel]
        ftk = np.minimum(first_tok[sel], ntok - 1)
        bsel = np.zeros(len(sel), np.bool_)
        bsel |= (cl == C_NAME1) & ((nn != 1) | (nops[sel] != 1))
        bsel |= (cl == C_SCN) & ((nn > 1) | (nm != 0) | ((nn == 1) & ~is_name[ltk]))  # a name is the last operand
        kc = {}
        for k in range(1, 7):
            kp = np.flatnonzero(fbt == k)
            kc[k] = (np.searchsorted(kp, ws_) - np.searchsorted(kp, ps)) if len(kp) else np.zeros(len(sel), np.int64)
        nstr = kc[_K_STR_DATA] + kc[_K_STR]
        narr = kc[_K_NUMARR] + kc[_K_ARR_DATA] + kc[_K_ARR]
        data[sel] = (kc[_K_STR_DATA] + kc[_K_ARR_DATA]) > 0
        nsel = nops[sel]
        bsel |= (cl == C_STR1) & ((nstr != 1) | (nsel != 1))
        bsel |= (cl == C_ARR1) & ((narr != 1) | (nsel != 1))
        bsel |= (cl == C_DQ) & ((nnum[sel] != 2) | (nstr != 1) | (nsel != 3) | ~((fbt[ltk] == _K_STR_DATA) | (fbt[ltk] == _K_STR)))
        bsel |= (cl == C_DASH) & ((nnum[sel] != 1) | (kc[_K_NUMARR] != 1) | (nsel != 2) | (fbt[ftk] != _K_NUMARR))
        two_names = (nn == 2) & (nsel == 2)
        name_dict = (nn == 1) & (kc[_K_DICT] == 1) & (nsel == 2) & is_name[ftk]
        bsel |= (cl == C_BDC) & ~(two_names | name_dict)
        bsel &= cl != C_ANY
        bad[sel] = bsel | (bad[sel] & ((cl == C_NUMS) | (cl == C_VARNUM)))
    if bad.any():
        raise _NotAdmitted
    trs = np.flatnonzero(code == TR_)
    if len(trs):
        tv = vals[np.where(prev[trs] >= 0, cn[pc[trs]], 0)]
        if not ((tv == np.floor(tv)) & (tv >= 0) & (tv <= 7)).all():
            raise _NotAdmitted
    has = nops > 0
    of = np.where(has, st[np.minimum(first_tok, ntok - 1)] + lo, -1)
    ol = np.where(has, en[np.maximum(wi - 1, 0)] + lo, -1)
    vstart = ops.nvals + np.where(prev >= 0, cn[pc], 0)
    ops.code.append(code.astype(np.uint8))
    ops.ts.append((wst + lo).astype(np.int32))
    ops.of.append(of.astype(np.int32))
    ops.ol.append(ol.astype(np.int32))
    ops.vstart.append(vstart.astype(np.int32))
    ops.vals.append(vals.astype(np.float32))  # every operand is float32-exact already
    ops.data.append(data)
    ni = np.flatnonzero(_NAMED[code] & (nname >= 1))
    if len(ni):
        nt = np.where(_CLS[code[ni]] == C_SCN, lt[ni], first_tok[ni])
        ops.name_op.append(ni + ops.nops)
        ops.name_s.append(st[nt] + lo)
        ops.name_e.append(en[nt] + lo)
    ops.nops += len(wi)
    ops.nvals += len(vals)
    return int(en[wi[-1]]) + lo


def _lex(data: bytes, sstarts: np.ndarray, cancel, progress) -> _Ops:
    n = len(data)
    arr = np.frombuffer(data, np.uint8)
    ops = _Ops()
    lo = 0
    size = _CHUNK
    total = n
    while lo < n:
        if cancel is not None and cancel():
            raise S.VectorScanCancelled()
        hi = min(lo + size, n)
        if hi < n:
            m = _WS_RE.search(data, hi)
            hi = m.start() if m else n
        nxt = _chunk(arr, lo, hi, sstarts, ops, hi >= n)
        if nxt is None:
            if hi >= n:
                break
            size *= 2
            if size > _MAX_STALL:
                raise _NotAdmitted
            continue
        size = _CHUNK
        lo = nxt
        if progress is not None:
            progress(min(lo, total), total)
    return ops


# ----------------------------------------------------------------------------- masks


def _walk(data: bytes, pos: int, opener: int) -> tuple[int, bool, bool]:
    """G's _container on the joined bytes: (offset after the closer, every element a number, a string with data inside).
    Anything G would refuse (or that runs off the data) raises _NotAdmitted."""
    stack = [opener]  # 0x5B or 0x3C
    cn = [0]
    numeric = True
    has_data = False
    count = 0
    match = S._TOKEN.match
    g_word, g_name, g_str, g_cmt, g_end = S._G_WORD, S._G_NAME, S._G_STR, S._G_CMT, S._G_END
    g_hex, g_nest, g_dict, g_br, g_stray = S._G_HEX, S._G_NEST, S._G_DICT, S._G_BR, S._G_STRAY
    num_start, num = S._NUM_START, S._NUM
    while True:
        m = match(data, pos)
        if m is None:
            raise _NotAdmitted
        gi = m.lastindex
        element = False  # (is a number, is a name)
        is_num = is_name = False
        if gi == g_word or gi == g_name or gi == g_str:
            s, e = m.span(gi)
            if gi == g_word:
                is_num = data[s] in num_start and num.fullmatch(data, s, e) is not None
            else:
                is_name = gi == g_name
                if gi == g_str and e - s > 2:
                    has_data = True
            element = True
            pos = m.end()
        elif gi == g_cmt:
            pos = m.end()
        elif gi == g_end:
            raise _NotAdmitted
        elif gi == g_hex:
            s, e = m.span(gi)
            if S._HEX_OK.fullmatch(data, s, e) is None:
                raise _NotAdmitted
            if data[s + 1 : e - 1].strip(S._WS_BYTES):
                has_data = True
            element = True
            pos = e
        elif gi == g_nest:
            s = m.start(g_nest)
            end = S._skip_string(data, s)
            if end is None:
                raise _NotAdmitted
            if end - s > 2:
                has_data = True
            element = True
            pos = end
        elif gi == g_dict:
            element = True
            pos = m.end()
        elif gi == g_br:
            s = m.start(g_br)
            pos = s + 1
            ch = data[s]
            if ch == 0x5B:
                element = True
            elif ch == 0x5D and stack[-1] == 0x5B:
                stack.pop()
                cn.pop()
                if not stack:
                    return pos, numeric, has_data
            else:
                raise _NotAdmitted
        elif gi == g_stray:
            s = m.start(g_stray)
            if data[s] == 0x3E and data[s + 1 : s + 2] == b">" and stack[-1] == 0x3C:
                if cn[-1] & 1:
                    raise _NotAdmitted
                stack.pop()
                cn.pop()
                pos = s + 2
                if not stack:
                    return pos, numeric, has_data
            else:
                raise _NotAdmitted
        else:
            raise _NotAdmitted
        if element:
            count += 1
            top = stack[-1]
            if top == 0x5B:
                if len(stack) == 1 and not is_num:
                    numeric = False
            else:
                n = cn[-1] + 1
                cn[-1] = n
                if n & 1 and not is_name:
                    raise _NotAdmitted
            if gi == g_dict:
                stack.append(0x3C)
                cn.append(0)
            elif gi == g_br:
                stack.append(0x5B)
                cn.append(0)
        if len(stack) > S.MAX_NEST or count > S.MAX_ARRAY_ELEMENTS:
            raise _NotAdmitted


def _mask(data: bytes, sstarts: np.ndarray) -> bytes:
    """data with every comment blanked and every string, hex string, dictionary and array turned into one marker byte
    followed by blanks (offsets unchanged).  Raises _NotAdmitted for anything G would refuse and for a span that
    crosses a stream start (G lexes streams one by one)."""
    if _MARK_RE.search(data) is not None:
        raise _NotAdmitted  # the marker bytes are ours
    buf = bytearray(data)
    search = _SPECIAL.search
    pos = 0
    sp_s: list[int] = []
    sp_e: list[int] = []
    while True:
        m = search(data, pos)
        if m is None:
            break
        gi = m.lastindex
        s, e = m.span()
        kind = 0
        if gi is None:  # a comment
            buf[s:e] = b" " * (e - s)
            pos = e
            continue
        if gi == 1:
            kind = _K_STR_DATA if e - s > 2 else _K_STR
        elif gi == 2:
            end = S._skip_string(data, s)
            if end is None:
                raise _NotAdmitted
            e = end
            kind = _K_STR_DATA if e - s > 2 else _K_STR
        elif gi == 4:
            if S._HEX_OK.fullmatch(data, s, e) is None:
                raise _NotAdmitted
            kind = _K_STR_DATA if data[s + 1 : e - 1].strip(S._WS_BYTES) else _K_STR
        elif gi == 3 or gi == 6:
            e, numeric, has_data = _walk(data, e, 0x3C if gi == 3 else 0x5B)
            kind = _K_DICT if gi == 3 else (_K_NUMARR if numeric else (_K_ARR_DATA if has_data else _K_ARR))
        else:  # a lone <, or a stray ) > ] { }
            raise _NotAdmitted
        buf[s] = kind
        buf[s + 1 : e] = b" " * (e - s - 1)
        sp_s.append(s)
        sp_e.append(e)
        pos = e
    if sp_s:
        a = np.array(sp_s, np.int64)
        z = np.array(sp_e, np.int64)
        if (np.searchsorted(sstarts, z, side="left") > np.searchsorted(sstarts, a, side="right")).any():
            raise _NotAdmitted  # a stream starts inside a string, hex string, dictionary or array
    return bytes(buf)


# ----------------------------------------------------------------------------- keyed lookups


class _Keyed:
    """Events (scope, position); query finds the last event strictly before a position in the same scope."""

    def __init__(self, scope: np.ndarray, pos: np.ndarray, n: int) -> None:
        self.m = n + 1
        key = (scope.astype(np.int64) + 1) * self.m + pos
        self.order = np.argsort(key, kind="stable")
        self.keys = key[self.order]

    def query(self, scope: np.ndarray, pos: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        if len(self.keys) == 0:
            return np.zeros(len(scope), np.bool_), np.zeros(len(scope), np.int64)
        key = (scope.astype(np.int64) + 1) * self.m + pos
        i = np.searchsorted(self.keys, key, side="left") - 1
        j = np.maximum(i, 0)
        ok = (i >= 0) & (self.keys[j] // self.m == scope + 1)
        return ok, self.order[j]


def _concat(f: np.ndarray, t: np.ndarray) -> np.ndarray:
    """affine_concat(f, t) row-wise, the same operations in the same order."""
    a, b, c, d, e, g = f.T
    a2, b2, c2, d2, e2, f2 = t.T
    return np.stack([a * a2 + b * c2, a * b2 + b * d2, c * a2 + d * c2, c * b2 + d * d2, e * a2 + g * c2 + e2, e * b2 + g * d2 + f2], axis=1)


_IDENT = np.array([1.0, 0.0, 0.0, 1.0, 0.0, 0.0])



# ----------------------------------------------------------------------------- the scan


def scan_fast(
    data: tuple[bytes, ...],
    frame: S.Frame,
    cancel: Callable[[], bool] | None,
    progress: Callable[[int, int], None] | None,
) -> S.VectorIndex | None:
    """The index of data as G would build it, or None when F does not admit the page."""
    try:
        return _scan(data, frame, cancel, progress)
    except _NotAdmitted:
        return None


def _scan(streams: tuple[bytes, ...], frame: S.Frame, cancel, progress) -> S.VectorIndex:
    if cancel is not None and cancel():
        raise S.VectorScanCancelled()
    joined = streams[0] if len(streams) == 1 else b"".join(streams)
    total = len(joined)
    starts: list[int] = []
    base = 0
    for s in streams:
        starts.append(base)
        base += len(s)
    sstarts = np.array(starts, np.int64)
    masked = _mask(joined, sstarts) if _QUICK.search(joined) is not None else joined
    ops = _lex(masked, sstarts, cancel, progress)
    del masked
    if cancel is not None and cancel():
        raise S.VectorScanCancelled()
    index = _build(streams, joined, frame, sstarts, ops, cancel)
    if progress is not None:
        progress(total, total)
    return index


def _cat(parts: list[np.ndarray], dtype) -> np.ndarray:
    out = np.concatenate(parts) if parts else np.empty(0, dtype)
    parts.clear()  # the per-chunk pieces are not kept beside the whole
    return out


def _ctm_levels(n, nq, qpos, sdepth, q_parent, cm_ops, cm_scope, cm_level, m6, maxlevel, keyed_cm):
    """CTM after every cm (level by level) and the initial CTM of every q scope; temporaries die here."""
    ncm = len(cm_ops)
    ctm_after = np.empty((ncm, 6))
    init = np.empty((nq, 6))
    for level in range(maxlevel + 1):
        if level >= 1:
            qs = np.flatnonzero(sdepth == level)
            par = q_parent[qs]
            ok, ev = keyed_cm.query(par, qpos[qs])
            parent_init = np.where((par >= 0)[:, None], init[np.maximum(par, 0)], _IDENT)
            init[qs] = np.where(ok[:, None], ctm_after[ev] if ncm else parent_init, parent_init)
        ci = np.flatnonzero(cm_level == level)
        if len(ci) == 0:
            continue
        sc = cm_scope[ci]
        o = np.lexsort((cm_ops[ci], sc))
        ci, sc = ci[o], sc[o]
        newgrp = np.concatenate(([True], sc[1:] != sc[:-1]))
        gstart = np.maximum.accumulate(np.where(newgrp, np.arange(len(ci)), 0))
        rank = np.arange(len(ci)) - gstart
        initv = np.where((sc >= 0)[:, None], init[np.maximum(sc, 0)] if nq else _IDENT, _IDENT)
        if level == 0 or int(rank.max()) > 64:
            last = _IDENT
            for t in range(len(ci)):
                prev = tuple(initv[t]) if rank[t] == 0 else last
                last = affine_concat(tuple(m6[ci[t]]), prev)
                ctm_after[ci[t]] = last
        else:
            byrank = np.argsort(rank, kind="stable")
            counts = np.bincount(rank)
            at = 0
            for r in range(len(counts)):
                sel = byrank[at : at + counts[r]]
                at += counts[r]
                prevm = initv[sel] if r == 0 else ctm_after[ci[sel - 1]]
                ctm_after[ci[sel]] = _concat(m6[ci[sel]], prevm)
    return ctm_after, init


def _build(streams, joined, frame, sstarts, ops: _Ops, cancel) -> S.VectorIndex:
    fr = np.array(frame, np.float64)
    lim = S._F32_MAX
    code = _cat(ops.code, np.uint8)
    ts = _cat(ops.ts, np.int32)
    of = _cat(ops.of, np.int32)
    ol = _cat(ops.ol, np.int32)
    vstart = _cat(ops.vstart, np.int32)
    vals = _cat(ops.vals, np.float32)
    odata = _cat(ops.data, np.bool_)
    nop = _cat(ops.name_op, np.int64)
    nsx = _cat(ops.name_s, np.int64)
    nex = _cat(ops.name_e, np.int64)
    n = len(code)
    hist = np.bincount(code, minlength=NCODE)  # which operators the page uses: a feature it does not use costs nothing
    digests = tuple(hashlib.sha256(s).digest() for s in streams)
    stream_table = np.zeros(len(streams), dtype=S._STREAM_DT)
    for k, s in enumerate(streams):
        stream_table[k] = (-1, int(sstarts[k]), len(s), b"")
    if n == 0:
        return _finish_empty(frame, digests, stream_table, len(joined))

    def stream_of(off: np.ndarray) -> np.ndarray:
        return np.searchsorted(sstarts, off, side="right") - 1

    # ------------------------------------------------------------------ scopes
    isq = code == Q_
    isQ = code == QQ_
    depth = np.cumsum(isq.astype(np.int32) - isQ.astype(np.int32), dtype=np.int32)
    if depth.min() < 0:
        raise _NotAdmitted  # Q below depth 0
    qpos = np.flatnonzero(isq)
    nq = len(qpos)
    sdepth = depth[qpos].astype(np.int64)
    stride = n + 1
    qkey = sdepth * stride + qpos
    qorder = np.argsort(qkey, kind="stable")
    qsorted = qkey[qorder]

    def scope_at(pos: np.ndarray, d: np.ndarray) -> np.ndarray:
        if nq == 0:
            return np.full(len(pos), -1, np.int64)
        i = np.searchsorted(qsorted, d * stride + pos, side="left") - 1
        j = np.maximum(i, 0)
        ok = (i >= 0) & (qsorted[j] // stride == d) & (d >= 1)
        return np.where(ok, qorder[j], -1)

    allpos = np.arange(n, dtype=np.int32)
    scope = np.empty(n, np.int32)
    for a in range(0, n, 1 << 20):  # blocks: the int64 temporaries stay small
        b = min(n, a + (1 << 20))
        scope[a:b] = scope_at(allpos[a:b].astype(np.int64), depth[a:b].astype(np.int64) + isQ[a:b])  # a Q closes the scope of its own opener
    scope[isq] = np.searchsorted(qpos, allpos[isq])  # a q opens its own scope (ordinal)
    del depth
    q_parent = scope_at(qpos, sdepth - 1) if nq else np.empty(0, np.int64)
    maxlevel = int(sdepth.max()) if nq else 0

    # ------------------------------------------------------------------ CTM by level
    cm_ops = np.flatnonzero(code == CM_)
    ncm = len(cm_ops)
    cm_scope = scope[cm_ops]
    cm_level = np.where(cm_scope >= 0, sdepth[np.maximum(cm_scope, 0)] if nq else 0, 0)
    m6 = vals[vstart[cm_ops][:, None] + np.arange(6)].astype(np.float64) if ncm else np.empty((0, 6))
    keyed_cm = _Keyed(cm_scope, cm_ops, n)
    ctm_after, init = _ctm_levels(n, nq, qpos, sdepth, q_parent, cm_ops, cm_scope, cm_level, m6, maxlevel, keyed_cm)
    if ncm:
        if not ((ctm_after >= -lim) & (ctm_after <= lim)).all():
            raise _NotAdmitted
        tot_cm = _concat(ctm_after, np.broadcast_to(fr, (ncm, 6)))
        if not ((tot_cm >= -lim) & (tot_cm <= lim)).all():
            raise _NotAdmitted
        del tot_cm
    del m6, cm_level

    def ctm_at(scope_arr: np.ndarray, pos: np.ndarray) -> np.ndarray:
        ok, ev = keyed_cm.query(scope_arr, pos)
        base_m = np.where((scope_arr >= 0)[:, None], init[np.maximum(scope_arr, 0)] if nq else _IDENT, _IDENT)
        return np.where(ok[:, None], ctm_after[ev] if ncm else base_m, base_m)

    def sticky(setter_pos: np.ndarray, setter_val: np.ndarray, qscope: np.ndarray, qpos_: np.ndarray, default: float) -> np.ndarray:
        keyed = _Keyed(scope[setter_pos], setter_pos, n)
        sinit = np.empty(nq)
        for level in range(1, maxlevel + 1):
            qs = np.flatnonzero(sdepth == level)
            par = q_parent[qs]
            ok, ev = keyed.query(par, qpos[qs])
            pinit = np.where(par >= 0, sinit[np.maximum(par, 0)], default)
            sinit[qs] = np.where(ok, setter_val[ev] if len(setter_val) else pinit, pinit)
        ok, ev = keyed.query(qscope, qpos_)
        qi = np.where(qscope >= 0, sinit[np.maximum(qscope, 0)] if nq else default, default)
        return np.where(ok, setter_val[ev] if len(setter_val) else qi, qi)

    # ------------------------------------------------------------------ paints, groups, constructs
    is_paint = (code >= PAINT0) & (code <= N_)
    pp = np.flatnonzero(is_paint)
    K = len(pp)
    if K > S.MAX_PAINTS:
        raise _NotAdmitted
    is_cons = (code >= M_) & (code <= H_)
    cp = np.flatnonzero(is_cons)
    cg = np.searchsorted(pp, cp, side="left")
    has_real = np.zeros(K + 1, np.bool_)
    has_real[cg] = True
    pq = pp[_CLOSE_PAINT[code[pp]]]
    pq_g = np.searchsorted(pp, pq, side="left")
    keep = has_real[pq_g]
    pq, pq_g = pq[keep], pq_g[keep]
    ev_pos = np.concatenate((cp, pq)).astype(np.int32)
    ev_g = np.concatenate((cg, pq_g)).astype(np.int32)
    ev_pseudo = np.concatenate((np.zeros(len(cp), np.bool_), np.ones(len(pq), np.bool_)))
    o = np.argsort(ev_pos, kind="stable")
    ev_pos, ev_g, ev_pseudo = ev_pos[o], ev_g[o], ev_pseudo[o]
    del cp, cg, pq, pq_g, o, keep
    E = len(ev_pos)
    et_all = np.where(ev_pseudo, H_, code[ev_pos]).astype(np.uint8) if E else np.empty(0, np.uint8)
    first = np.concatenate(([True], ev_g[1:] != ev_g[:-1])) if E else np.empty(0, np.bool_)
    gids = np.flatnonzero(has_real[:K])
    npath = len(gids)
    pid_of_group = np.full(K + 1, -1, np.int32)
    pid_of_group[gids] = np.arange(npath, dtype=np.int32)
    paint_pos = pp[gids]
    group_first_ev = np.full(K + 1, -1, np.int64)
    if E:
        first_ev = np.flatnonzero(first)
        group_first_ev[ev_g[first_ev]] = first_ev
        del first_ev
    fev = group_first_ev[gids]
    del group_first_ev
    fop = ev_pos[fev]
    p_start = np.where(of[fop] >= 0, of[fop], ts[fop])
    p_stream = stream_of(p_start)
    pscope = scope[paint_pos]
    ctm_p = ctm_at(pscope, paint_pos)
    tot_p = _concat(ctm_p, np.broadcast_to(fr, (npath, 6))) if npath else np.empty((0, 6))
    cum_np = np.cumsum(_NONPATH[code], dtype=np.int32)
    impure = (cum_np[paint_pos] - cum_np[fop]) > 0
    del cum_np, fev
    w_pos = np.flatnonzero(code == W_)
    g_pos = np.flatnonzero(code == GS_)
    set_pos = np.concatenate((w_pos, g_pos))
    set_val = np.concatenate((vals[vstart[w_pos]].astype(np.float64), np.full(len(g_pos), np.nan)))
    width_p = sticky(set_pos, set_val, pscope, paint_pos, 1.0)
    j_pos = np.flatnonzero(code == 11)  # J: 0 butt, 1 round, 2 square; a gs makes it unknown (nan), never guessed round
    cap_p = sticky(
        np.concatenate((j_pos, g_pos)),
        np.concatenate((vals[vstart[j_pos]].astype(np.float64), np.full(len(g_pos), np.nan))),
        pscope,
        paint_pos,
        0.0,
    )
    gs_p = sticky(g_pos, np.ones(len(g_pos)), pscope, paint_pos, 0.0) > 0
    del set_pos, set_val, w_pos, g_pos

    # ---- state G keeps beside the graphics state: clip, text, marked content, colour spaces
    if hist[CLIP_] + hist[CLIPS_]:
        xw_pos = np.flatnonzero((code == CLIP_) | (code == CLIPS_))
        has_w_g = np.diff(np.concatenate(([0], np.searchsorted(xw_pos, pp)))) > 0  # a W or W* between the previous paint and this one
    else:
        has_w_g = np.zeros(K, np.bool_)
    clip_ev = [pp[has_w_g]]  # the clip takes effect after that paint, with or without a path
    tr_pos = np.flatnonzero(code == TR_) if hist[TR_] else np.empty(0, np.int64)
    tr_val = vals[vstart[tr_pos]].astype(np.float64)
    shows = hist[TJ_] + hist[TJA_] + hist[QT_] + hist[DQT_]
    show = np.flatnonzero(((code == TJ_) | (code == TJA_) | (code == QT_) | (code == DQT_)) & odata) if shows and hist[ET_] else np.empty(0, np.int64)
    qual = show[sticky(tr_pos, tr_val, scope[show], show, 0.0) >= 4] if len(show) else show
    ets = np.flatnonzero(code == ET_) if len(show) else np.empty(0, np.int64)
    if len(ets) and len(qual):  # an ET joins the clip when text with data was shown under a clip mode since the last Q or ET
        resets = np.sort(np.concatenate((ets, np.flatnonzero(isQ))))
        ri = np.searchsorted(resets, ets, side="left") - 1
        rp = np.where(ri >= 0, resets[np.maximum(ri, 0)], -1)
        clip_ev.append(ets[(np.searchsorted(qual, ets, side="left") - np.searchsorted(qual, rp, side="right")) > 0])
    clip_pos = np.concatenate(clip_ev)
    clipped_p = sticky(clip_pos, np.ones(len(clip_pos)), pscope, paint_pos, 0.0) > 0 if len(clip_pos) else np.zeros(npath, np.bool_)
    del clip_ev, clip_pos, show, qual, ets, tr_pos, tr_val
    btet = np.flatnonzero((code == BT_) | (code == ET_)) if hist[BT_] else np.empty(0, np.int64)
    if len(btet):
        ii = np.searchsorted(btet, paint_pos, side="left") - 1
        in_text_p = (ii >= 0) & (code[btet[np.maximum(ii, 0)]] == BT_)
    else:
        in_text_p = np.zeros(npath, np.bool_)
    del btet
    name_at = {int(o): (int(s), int(e)) for o, s, e in zip(nop.tolist(), nsx.tolist(), nex.tolist(), strict=True)}
    mc_open = (code == BDC_) | (code == BMC_) if hist[BDC_] + hist[BMC_] + hist[EMC_] else np.zeros(n, np.bool_)
    mcp = np.flatnonzero(mc_open | (code == EMC_)) if hist[BDC_] + hist[BMC_] + hist[EMC_] else np.empty(0, np.int64)
    oc_p = np.zeros(npath, np.bool_)
    if len(mcp):
        isopen = mc_open[mcp]
        depth_mc = np.cumsum(np.where(isopen, 1, -1))
        if depth_mc.min() < 0:
            raise _NotAdmitted  # EMC below marked-content depth 0
        level = np.where(isopen, depth_mc, depth_mc + 1)
        order = np.lexsort((np.arange(len(mcp)), level))
        lv, op_ = level[order], isopen[order]
        pair = np.flatnonzero(op_[:-1] & ~op_[1:] & (lv[:-1] == lv[1:]))
        closer = np.full(len(mcp), -1, np.int64)
        closer[order[pair]] = order[pair + 1]
        is_oc = np.zeros(len(mcp), np.bool_)
        for i in np.flatnonzero(code[mcp] == BDC_).tolist():
            s_, e_ = name_at[int(mcp[i])]
            raw = joined[s_:e_]
            is_oc[i] = (raw if b"#" not in raw else S._decode_name(raw)) == b"/OC"
        oi = np.flatnonzero(is_oc)
        ci_ = closer[oi]
        ev_p = np.concatenate((mcp[oi], mcp[ci_[ci_ >= 0]]))
        ev_d = np.concatenate((np.ones(len(oi), np.int64), -np.ones(int((ci_ >= 0).sum()), np.int64)))
        o_ = np.argsort(ev_p, kind="stable")
        ev_p, csum = ev_p[o_], np.cumsum(ev_d[o_])

        def oc_before(pos: np.ndarray) -> np.ndarray:
            if len(ev_p) == 0:
                return np.zeros(len(pos), np.bool_)
            i = np.searchsorted(ev_p, pos, side="left") - 1
            return (i >= 0) & (csum[np.maximum(i, 0)] > 0)

        oc_p = oc_before(paint_pos) | oc_before(fop)
    fill_pos: list[np.ndarray] = []
    fill_val: list[np.ndarray] = []
    stroke_pos: list[np.ndarray] = []
    stroke_val: list[np.ndarray] = []
    used = hist[CS_] + hist[CSU_] + hist[SCN_] + hist[SCNU_] > 0  # no colour-space operator: g, rg, k and the others only ever clear a flag that is clear
    if used:
        fill_pos.append(np.flatnonzero((code == G_) | (code == RG_) | (code == K_)))
        fill_val.append(np.zeros(len(fill_pos[0])))
        stroke_pos.append(np.flatnonzero((code == GU_) | (code == RGU_) | (code == KU_)))
        stroke_val.append(np.zeros(len(stroke_pos[0])))
    for cs_code, scn_code, pos_l, val_l in ((CS_, SCN_, fill_pos, fill_val), (CSU_, SCNU_, stroke_pos, stroke_val)):
        cp_ = np.flatnonzero(code == cs_code) if hist[cs_code] else np.empty(0, np.int64)
        if len(cp_):
            pos_l.append(cp_)
            nd = [float(S._decode_name(joined[name_at[int(o)][0] : name_at[int(o)][1]]) not in S._DEVICE_SPACES) for o in cp_.tolist()]
            val_l.append(np.array(nd, np.float64))
        sp_ = np.flatnonzero(code == scn_code) if hist[scn_code] else np.empty(0, np.int64)
        sp_ = sp_[np.isin(sp_, nop)] if len(sp_) else sp_
        if len(sp_):
            pos_l.append(sp_)
            val_l.append(np.ones(len(sp_)))
    csf_p = sticky(np.concatenate(fill_pos), np.concatenate(fill_val), pscope, paint_pos, 0.0) > 0 if fill_pos else np.zeros(npath, np.bool_)
    css_p = sticky(np.concatenate(stroke_pos), np.concatenate(stroke_val), pscope, paint_pos, 0.0) > 0 if stroke_pos else np.zeros(npath, np.bool_)
    anchored = gs_p | csf_p | css_p
    del fill_pos, fill_val, stroke_pos, stroke_val, csf_p, css_p

    seg_chunks: list[np.ndarray | None] = []
    cub_chunks: list[np.ndarray | None] = []
    seg_count = np.zeros(npath, np.int64)
    prim_count = np.zeros(npath, np.int64)
    bx0 = np.full(npath, np.inf)
    by0 = np.full(npath, np.inf)
    bx1 = np.full(npath, -np.inf)
    by1 = np.full(npath, -np.inf)
    pt0x = np.zeros(npath)
    pt0y = np.zeros(npath)
    state = [0, 0]  # rows so far, chord rows so far
    dot_acc: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []  # (path, x, y) of every closed zero-length subpath
    cap = S.MAX_CHORD_ROWS

    def fold(pid: np.ndarray, xs: np.ndarray, ys: np.ndarray) -> None:
        if len(pid):
            np.minimum.at(bx0, pid, xs)
            np.maximum.at(bx1, pid, xs)
            np.minimum.at(by0, pid, ys)
            np.maximum.at(by1, pid, ys)

    def batch(e0: int, e1: int) -> None:
        """Events e0..e1 (whole groups): primitives, page-space geometry, chords and boxes of their paths."""
        sl = slice(e0, e1)
        bg, bpos, bps, et, bfirst = ev_g[sl], ev_pos[sl], ev_pseudo[sl], et_all[sl], first[sl]
        Eb = e1 - e0
        rows = np.arange(Eb)
        gstart = np.maximum.accumulate(np.where(bfirst, rows, 0))
        V = np.zeros((Eb, 6))
        ar = np.where(bps, 0, _ARITY[code[bpos]])
        for j in range(6):
            sel = ar > j
            V[sel, j] = vals[vstart[bpos[sel]] + j]
        is_mre = (et == M_) | (et == RE_)
        sub_src = np.maximum.accumulate(np.where(is_mre, rows, -1))
        sub_ok = sub_src >= gstart
        si = np.maximum(sub_src, 0)
        subx, suby = V[si, 0], V[si, 1]
        nonh = (et != H_).astype(np.int64)
        cnh = np.cumsum(nonh)
        cv_after = (cnh - (cnh[gstart] - nonh[gstart])) > 0
        ish = et == H_
        curx = np.where(et == C_, V[:, 4], np.where((et == V_) | (et == Y_), V[:, 2], V[:, 0]))
        cury = np.where(et == C_, V[:, 5], np.where((et == V_) | (et == Y_), V[:, 3], V[:, 1]))
        # h moves the current point to the subpath start only when the two differ in value (G keeps the point it has: -0.0 vs 0.0)
        lnh = np.maximum.accumulate(np.where(~ish, rows, -1))  # the last event before an h that is not an h
        pvx, pvy = curx[np.maximum(lnh, 0)], cury[np.maximum(lnh, 0)]
        moves = sub_ok & (lnh >= gstart) & ((pvx != subx) | (pvy != suby))
        curx = np.where(ish, np.where(moves, subx, pvx), curx)
        cury = np.where(ish, np.where(moves, suby, pvy), cury)
        prev_ok = np.zeros(Eb, np.bool_)
        prevx = np.zeros(Eb)
        prevy = np.zeros(Eb)
        if Eb > 1:
            prev_ok[1:] = (~bfirst[1:]) & cv_after[:-1]
            prevx[1:] = curx[:-1]
            prevy[1:] = cury[:-1]
        need = (et == L_) | (et == C_) | (et == V_) | (et == Y_)
        if (need & ~prev_ok).any():
            raise _NotAdmitted
        cnt_mre = np.cumsum(is_mre.astype(np.int64))
        sp = np.maximum(cnt_mre - (cnt_mre[gstart] - is_mre[gstart]) - 1, 0)
        csg = np.cumsum(need.astype(np.int64))
        h_valid = ish & sub_ok & prev_ok
        differs = (prevx != subx) | (prevy != suby)
        close_line = h_valid & differs
        segs_before = np.zeros(Eb, np.int64)
        if Eb > 1:
            segs_before[1:] = csg[:-1]
        segs_between = segs_before - csg[si]
        sub_has_seg = (et[si] == RE_) | (segs_between > 0)
        dot = h_valid & ~differs & ~sub_has_seg
        nprim = np.where(et == RE_, 4, np.where(need, 1, np.where(close_line, 1, 0))).astype(np.int32)
        P = int(nprim.sum())
        prim_e = np.repeat(rows.astype(np.int32), nprim)
        pstart = np.cumsum(nprim, dtype=np.int32) - nprim
        prim_k = np.arange(P, dtype=np.int32) - np.repeat(pstart, nprim)
        pe_t = et[prim_e]
        is_cub = (pe_t == C_) | (pe_t == V_) | (pe_t == Y_)
        lx0 = np.zeros(P)
        ly0 = np.zeros(P)
        lx1 = np.zeros(P)
        ly1 = np.zeros(P)
        m_l = pe_t == L_
        lx0[m_l], ly0[m_l], lx1[m_l], ly1[m_l] = prevx[prim_e[m_l]], prevy[prim_e[m_l]], V[prim_e[m_l], 0], V[prim_e[m_l], 1]
        m_h = pe_t == H_
        lx0[m_h], ly0[m_h], lx1[m_h], ly1[m_h] = prevx[prim_e[m_h]], prevy[prim_e[m_h]], subx[prim_e[m_h]], suby[prim_e[m_h]]
        m_r = pe_t == RE_
        if m_r.any():
            re_e = prim_e[m_r]
            rk = prim_k[m_r]
            x, y, w, h = V[re_e, 0], V[re_e, 1], V[re_e, 2], V[re_e, 3]
            cx = np.stack([x, x + w, x + w, x], axis=1)
            cy = np.stack([y, y, y + h, y + h], axis=1)
            ar_ = np.arange(len(rk))
            lx0[m_r], ly0[m_r] = cx[ar_, rk], cy[ar_, rk]
            lx1[m_r], ly1[m_r] = cx[ar_, (rk + 1) % 4], cy[ar_, (rk + 1) % 4]
        cub_e = prim_e[is_cub]
        ncub = len(cub_e)
        cpts = np.zeros((ncub, 8))
        if ncub:
            t_ = et[cub_e]
            cpts[:, 0], cpts[:, 1] = prevx[cub_e], prevy[cub_e]
            c_m, v_m, y_m = t_ == C_, t_ == V_, t_ == Y_
            Vc = V[cub_e]
            cpts[c_m, 2:8] = Vc[c_m, 0:6]
            cpts[v_m, 2], cpts[v_m, 3] = prevx[cub_e][v_m], prevy[cub_e][v_m]
            cpts[v_m, 4:8] = Vc[v_m, 0:4]
            cpts[y_m, 2:4] = Vc[y_m, 0:2]
            cpts[y_m, 4:6] = Vc[y_m, 2:4]
            cpts[y_m, 6:8] = Vc[y_m, 2:4]
        ppath = pid_of_group[bg[prim_e]].astype(np.int64) if P else np.zeros(0, np.int64)
        live = ppath >= 0
        lin = live & ~is_cub
        lsel = np.flatnonzero(lin)
        lp = ppath[lsel]
        tl = tot_p[lp] if npath else np.zeros((0, 6))
        X0 = lx0[lsel] * tl[:, 0] + ly0[lsel] * tl[:, 2] + tl[:, 4]
        Y0 = lx0[lsel] * tl[:, 1] + ly0[lsel] * tl[:, 3] + tl[:, 5]
        X1 = lx1[lsel] * tl[:, 0] + ly1[lsel] * tl[:, 2] + tl[:, 4]
        Y1 = lx1[lsel] * tl[:, 1] + ly1[lsel] * tl[:, 3] + tl[:, 5]
        for arrv in (X0, Y0, X1, Y1):
            if not ((arrv >= -lim) & (arrv <= lim)).all():
                raise _NotAdmitted
        cub_live = live[is_cub]
        cpath = ppath[is_cub]
        ct6 = tot_p[np.maximum(cpath, 0)] if npath and ncub else np.zeros((ncub, 6))
        cpage = np.empty((ncub, 8))
        for k in range(4):
            cpage[:, 2 * k] = cpts[:, 2 * k] * ct6[:, 0] + cpts[:, 2 * k + 1] * ct6[:, 2] + ct6[:, 4]
            cpage[:, 2 * k + 1] = cpts[:, 2 * k] * ct6[:, 1] + cpts[:, 2 * k + 1] * ct6[:, 3] + ct6[:, 5]
        if ncub and not ((cpage[cub_live] >= -lim) & (cpage[cub_live] <= lim)).all():
            raise _NotAdmitted
        dot_ev = np.flatnonzero(dot)
        dpath = pid_of_group[bg[dot_ev]].astype(np.int64) if len(dot_ev) else np.empty(0, np.int64)
        dl = dpath >= 0
        dot_ev, dpath = dot_ev[dl], dpath[dl]
        dt6 = tot_p[dpath] if len(dot_ev) else np.zeros((0, 6))
        dx = subx[dot_ev] * dt6[:, 0] + suby[dot_ev] * dt6[:, 2] + dt6[:, 4]
        dy = subx[dot_ev] * dt6[:, 1] + suby[dot_ev] * dt6[:, 3] + dt6[:, 5]
        if len(dot_ev) and not ((dx >= -lim) & (dx <= lim) & (dy >= -lim) & (dy <= lim)).all():
            raise _NotAdmitted
        cub_idx = np.flatnonzero(is_cub)
        chord_verts: list[np.ndarray | None] = []
        cl = cpage.tolist()
        counts = np.ones(ncub, np.int64)
        for i in range(ncub):
            if not cub_live[i]:
                chord_verts.append(None)
                continue
            pr = cl[i]
            d1 = math.hypot(pr[0] - 2 * pr[2] + pr[4], pr[1] - 2 * pr[3] + pr[5])
            d2 = math.hypot(pr[2] - 2 * pr[4] + pr[6], pr[3] - 2 * pr[5] + pr[7])
            arg = 0.75 * max(d1, d2) / S.CHORD_EPSILON
            remaining = cap - state[1]
            if remaining < 1 or arg > float(remaining) ** 2:
                raise _NotAdmitted
            count = max(1, math.ceil(math.sqrt(arg)))
            if count > remaining:
                raise _NotAdmitted
            state[1] += count
            counts[i] = count
            p = np.array(pr, dtype=np.float64).reshape(4, 2)
            verts = np.empty((count + 1, 2), dtype=np.float64)
            verts[0], verts[count] = p[0], p[3]
            if count > 1:
                t = np.arange(1, count, dtype=np.float64) / count
                u = 1.0 - t
                verts[1:count] = (u * u * u)[:, None] * p[0] + (3 * u * u * t)[:, None] * p[1] + (3 * u * t * t)[:, None] * p[2] + (t * t * t)[:, None] * p[3]
            chord_verts.append(verts)
        cub_rows = np.ones(P, np.int64)
        cub_rows[cub_idx] = counts
        nrows = np.where(live, cub_rows, 0)
        row_start = np.cumsum(nrows) - nrows
        nloc = int(nrows.sum())
        if state[0] + nloc + int((~live).sum()) >= S.MAX_SEGMENT_ROWS:  # rows so far plus the primitives of a path that never paints (G counts both before each construct)
            raise _NotAdmitted
        base = state[0]
        segs = np.zeros(nloc, dtype=S._SEG_DT)
        r0 = row_start[lsel]
        segs["x0"][r0], segs["y0"][r0], segs["x1"][r0], segs["y1"][r0] = X0, Y0, X1, Y1
        segs["path"][r0] = lp
        prim_sp = sp[prim_e] if P else np.empty(0, np.int64)
        segs["subpath"][r0] = prim_sp[lsel]
        cubs = np.zeros(int(cub_live.sum()), dtype=S._CUBIC_DT)
        ci_out = 0
        for i in range(ncub):
            v = chord_verts[i]
            if v is None:
                continue
            pi = cub_idx[i]
            a0 = int(row_start[pi])
            cnt = len(v) - 1
            segs["x0"][a0 : a0 + cnt], segs["y0"][a0 : a0 + cnt] = v[:-1, 0], v[:-1, 1]
            segs["x1"][a0 : a0 + cnt], segs["y1"][a0 : a0 + cnt] = v[1:, 0], v[1:, 1]
            segs["path"][a0 : a0 + cnt] = ppath[pi]
            segs["from_cubic"][a0 : a0 + cnt] = True
            segs["subpath"][a0 : a0 + cnt] = prim_sp[pi]
            cubs["pts"][ci_out] = cl[i]
            cubs["path"][ci_out] = ppath[pi]
            cubs["seg_start"][ci_out] = base + a0
            cubs["seg_count"][ci_out] = cnt
            ci_out += 1
        seg_chunks.append(segs)
        cub_chunks.append(cubs)
        state[0] += nloc
        if npath:
            seg_count[:] += np.bincount(ppath[live], weights=nrows[live], minlength=npath).astype(np.int64)
            prim_count[:] += np.bincount(ppath[live], minlength=npath)
        fold(lp, X0, Y0)
        fold(lp, X1, Y1)
        live_c = np.flatnonzero(cub_live)
        for k in range(4):
            fold(cpath[live_c], cpage[live_c, 2 * k], cpage[live_c, 2 * k + 1])
        fold(dpath, dx, dy)
        if len(dpath):
            dot_acc.append((dpath.copy(), dx.copy(), dy.copy()))
        mre = np.flatnonzero(is_mre & (pid_of_group[bg] >= 0))
        if len(mre):
            pid_m = pid_of_group[bg[mre]].astype(np.int64)
            upid, fi = np.unique(pid_m, return_index=True)
            pt0x[upid] = V[mre[fi], 0]
            pt0y[upid] = V[mre[fi], 1]

    step = 250_000
    e0 = 0
    while e0 < E:
        e1 = min(E, e0 + step)
        if e1 < E:
            nxt = np.flatnonzero(first[e1:])
            e1 = e1 + int(nxt[0]) if len(nxt) else E
        batch(e0, e1)
        if cancel is not None and cancel():
            raise S.VectorScanCancelled()
        e0 = e1
    ev_pos = ev_g = ev_pseudo = et_all = first = None  # type: ignore[assignment]  # the batches are done: free the event arrays
    vals = vstart = None  # type: ignore[assignment]
    total_rows = state[0]
    segments = np.zeros(total_rows, dtype=S._SEG_DT)
    at = 0
    for i, c in enumerate(seg_chunks):
        assert c is not None
        segments[at : at + len(c)] = c
        at += len(c)
        seg_chunks[i] = None
    cubics = np.concatenate([c for c in cub_chunks if c is not None]) if cub_chunks else np.zeros(0, dtype=S._CUBIC_DT)
    cub_chunks.clear()
    seg_start = np.cumsum(seg_count) - seg_count
    degenerate = prim_count == 0
    if degenerate.any():
        degx = pt0x * tot_p[:, 0] + pt0y * tot_p[:, 2] + tot_p[:, 4]
        degy = pt0x * tot_p[:, 1] + pt0y * tot_p[:, 3] + tot_p[:, 5]
        if not ((degx[degenerate] >= -lim) & (degx[degenerate] <= lim) & (degy[degenerate] >= -lim) & (degy[degenerate] <= lim)).all():
            raise _NotAdmitted
        bx0[degenerate] = bx1[degenerate] = degx[degenerate]
        by0[degenerate] = by1[degenerate] = degy[degenerate]
    det = ctm_p[:, 0] * ctm_p[:, 3] - ctm_p[:, 1] * ctm_p[:, 2] if npath else np.empty(0)
    singular = ~(np.abs(det) > S._SINGULAR_DET)
    paint_code = code[paint_pos].astype(np.int64) - 22
    spans = p_stream != stream_of(ts[paint_pos])
    flags = np.zeros(npath, np.int64)
    flags |= np.where(impure | in_text_p, S._FL_IMPURE, 0)
    flags |= np.where(has_w_g[gids], S._FL_SETS_CLIP, 0)
    flags |= np.where(clipped_p, S._FL_CLIPPED, 0)
    flags |= np.where(oc_p, S._FL_IN_OC, 0)
    flags |= np.where(spans, S._FL_SPANS_STREAMS, 0)
    flags |= np.where(singular, S._FL_CTM_SINGULAR, 0)
    flags |= np.where(anchored, S._FL_PAGE_ANCHORED, 0)
    flags |= np.where(degenerate, S._FL_DEGENERATE, 0)
    blockers = S._FL_IMPURE | S._FL_SETS_CLIP | S._FL_SPANS_STREAMS | S._FL_IN_OC | S._FL_CTM_SINGULAR
    flags |= np.where((paint_code != 10) & ((flags & blockers) == 0), S._FL_EDITABLE, 0)
    sigma = np.empty(npath)
    for c0 in range(0, npath, 1 << 16):  # math.hypot is G's call; chunks keep the Python float lists small
        sub = tot_p[c0 : c0 + (1 << 16)]
        a_l, b_l, c_l, d_l = (sub[:, i].tolist() for i in range(4))
        sigma[c0 : c0 + len(sub)] = [math.hypot((a + d) / 2, (b - c) / 2) + math.hypot((a - d) / 2, (b + c) / 2) for a, b, c, d in zip(a_l, b_l, c_l, d_l, strict=True)]
    width = np.abs(width_p) * sigma
    if (width > lim).any():
        raise _NotAdmitted
    struct = np.flatnonzero(isq | isQ)
    pair = np.flatnonzero((code[struct[:-1]] == Q_) & (code[struct[1:]] == QQ_)) if len(struct) > 1 else np.empty(0, np.int64)
    bq = struct[pair]
    bQ = struct[pair + 1]
    nb = len(pair)
    blk_of_scope = np.full(nq, -1, np.int32)
    bscope = np.searchsorted(qpos, bq)
    blk_of_scope[bscope] = np.arange(nb)
    ob = np.where((scope >= 0) & ~(isq | isQ), blk_of_scope[np.maximum(scope, 0)] if nq else -1, -1)
    pb = ob[paint_pos]
    cum_c = np.cumsum(is_cons, dtype=np.int32)
    lastp = np.maximum.accumulate(np.where(is_paint, allpos, -1))

    def open_before(pos: np.ndarray) -> np.ndarray:
        before = pos - 1
        c_now = np.where(before >= 0, cum_c[np.maximum(before, 0)], 0)
        lp = np.where(before >= 0, lastp[np.maximum(before, 0)], -1)
        c_then = np.where(lp >= 0, cum_c[np.maximum(lp, 0)], 0)
        return (c_now - c_then) > 0

    paint_ob = ob[pp]
    nblk_paints = np.bincount(paint_ob[paint_ob >= 0], minlength=nb)
    if hist[_NONINERT].any():
        has_ni = np.bincount(ob[_NONINERT[code] & (ob >= 0)], minlength=nb) > 0  # an operator outside G's inert allowlist
    else:
        has_ni = np.zeros(nb, np.bool_)
    cmb = ob[cm_ops]
    cm_in = cmb >= 0
    n_cm = np.bincount(cmb[cm_in], minlength=nb)
    cm_same = stream_of(of[cm_ops]) == stream_of(ts[cm_ops]) if ncm else np.empty(0, np.bool_)
    bad_cm = np.bincount(cmb[cm_in & ~cm_same], minlength=nb) > 0
    cm_s = np.full(nb, -1, np.int64)
    cm_e = np.full(nb, -1, np.int64)
    if cm_in.any():
        ub, fi = np.unique(cmb[cm_in], return_index=True)
        srcs = np.flatnonzero(cm_in)[fi]
        same_first = cm_same[srcs]
        cm_s[ub] = np.where(same_first, of[cm_ops[srcs]], -1)
        cm_e[ub] = np.where(same_first, ol[cm_ops[srcs]], -1)
    if nb and npath:
        inblk = pb >= 0
        after = np.zeros(npath, np.bool_)
        after[inblk] = p_start[inblk] > ts[bq[pb[inblk]]]
        recs_after = np.bincount(pb[inblk & after], minlength=nb)
    else:
        recs_after = np.zeros(nb, np.int64)
    open_q = open_before(bq)
    open_Q = open_before(bQ)
    inert = ~has_ni & ~bad_cm & ~open_q & ~open_Q & (nblk_paints >= 1) & (recs_after == nblk_paints) & (stream_of(ts[bq]) == stream_of(ts[bQ]))
    blocks = np.zeros(nb, dtype=S._BLOCK_DT)
    if nb:
        blocks["q_start"] = ts[bq]
        blocks["q_end"] = ts[bQ] + _OPLEN[code[bQ]]
        blocks["n_paints"] = nblk_paints
        blocks["inert"] = inert
        blocks["n_cm"] = n_cm
        blocks["cm_operand_start"] = cm_s
        blocks["cm_operand_end"] = cm_e
    res: dict[int, list[tuple[bytes, bytes]]] = {}
    if nb and len(nop):
        for o_, s_, e_ in zip(nop.tolist(), nsx.tolist(), nex.tolist(), strict=True):
            rop = _RES_OPS.get(int(code[o_]))
            if rop is not None and ob[o_] >= 0:
                res.setdefault(int(ob[o_]), []).append((rop, S._decode_name(joined[s_:e_])))
    paths = np.zeros(npath, dtype=S._PATH_DT)
    if npath:
        paths["path_start"] = p_start
        paths["paint_end"] = ts[paint_pos] + _OPLEN[code[paint_pos]]
        paths["block"] = pb
        paths["paint"] = paint_code
        paths["flags"] = flags
        bb = np.stack([bx0, by0, bx1, by1], axis=1).astype(np.float32)
        fmax = np.float32(lim)
        lo_, hi_ = -fmax, fmax
        bb[:, 0:2] = np.nextafter(bb[:, 0:2], lo_)
        bb[:, 2:4] = np.nextafter(bb[:, 2:4], hi_)
        paths["bbox"] = bb
        w32 = width.astype(np.float32)
        below = w32.astype(np.float64) < width
        w32[below] = np.minimum(np.nextafter(w32[below], hi_), fmax)
        paths["line_width"] = w32
        paths["ctm"] = ctm_p
        paths["seg_start"] = seg_start
        paths["seg_count"] = seg_count
    dots = np.zeros(0, dtype=S._DOT_DT)
    if dot_acc and npath:
        dp = np.concatenate([a_[0] for a_ in dot_acc])
        ddx = np.concatenate([a_[1] for a_ in dot_acc])
        ddy = np.concatenate([a_[2] for a_ in dot_acc])
        stroke = np.isin(paint_code, (1, 2, 6, 7, 8, 9))
        keep = (cap_p[dp] == 1.0) & (prim_count[dp] > 0) & stroke[dp]  # a lone "m h" paints nothing
        order = np.argsort(dp[keep], kind="stable")
        dp, ddx, ddy = dp[keep][order], ddx[keep][order], ddy[keep][order]
        dots = np.zeros(len(dp), dtype=S._DOT_DT)
        dots["path"], dots["x"], dots["y"] = dp, ddx, ddy
        dots["subpath"] = np.arange(len(dp)) - np.searchsorted(dp, dp, side="left")
    nbytes = int(paths.nbytes + cubics.nbytes + segments.nbytes + blocks.nbytes + stream_table.nbytes + dots.nbytes)
    return S.VectorIndex(paths, cubics, segments, blocks, stream_table, len(joined), False, frame, digests, nbytes, tuple(tuple(res.get(i, ())) for i in range(nb)), "F", True, dots)


def _finish_empty(frame, digests, stream_table, total: int) -> S.VectorIndex:
    paths = np.zeros(0, dtype=S._PATH_DT)
    cubics = np.zeros(0, dtype=S._CUBIC_DT)
    segments = np.zeros(0, dtype=S._SEG_DT)
    blocks = np.zeros(0, dtype=S._BLOCK_DT)
    nbytes = int(paths.nbytes + cubics.nbytes + segments.nbytes + blocks.nbytes + stream_table.nbytes)
    return S.VectorIndex(paths, cubics, segments, blocks, stream_table, total, False, frame, digests, nbytes, (), "F", True)


def run(streams: Sequence[bytes], frame: S.Frame, cancel, progress) -> S.VectorIndex | None:
    return scan_fast(tuple(streams), frame, cancel, progress)
