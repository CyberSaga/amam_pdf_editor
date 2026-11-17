"""S0-P11: inline images with a VERIFIED boundary. For every `BI` outside a string or comment, prove where the
payload ends (ladder: /L, unfiltered computed length, outermost-filter end: A85 `~>`, AHx `>`, Flate zlib eof,
DCT EOI, RL EOD), then require `EI` after it; compare with the first-whitespace-`EI` heuristic.
Usage: python p11_inline_image_ladder.py <dir-or-pdf> [out.txt]"""
from __future__ import annotations

import re
import sys
import zlib
from collections import Counter
from pathlib import Path

import fitz

WS = b" \t\r\n\x0c\x00"
DELIM = b"()<>[]{}/%"
HOP = re.compile(rb"[(%]|(?<![^\s\[\]<>(){}/%])BI(?=[\s/])")
DTOK = re.compile(rb"\s*(/[^\s/\[\]<>(){}%]*|\[|\]|<<|>>|<[^>]*>|\(|[^\s/\[\]<>(){}%]+)")
HEUR = re.compile(rb"[\s]EI(?=[\s\[\]<>(){}/%]|$)")
PAINT = re.compile(rb"(?<![^\s\]])(?:S|s|f\*?|F|B\*?|b\*?)(?=[\s]|$)")
ABBR = {b"W": b"Width", b"H": b"Height", b"BPC": b"BitsPerComponent", b"CS": b"ColorSpace", b"IM": b"ImageMask",
        b"F": b"Filter", b"L": b"Length", b"DP": b"DecodeParms", b"D": b"Decode", b"I": b"Interpolate"}
COMPS = {b"G": 1, b"DeviceGray": 1, b"RGB": 3, b"DeviceRGB": 3, b"CMYK": 4, b"DeviceCMYK": 4}
FNAME = {b"A85": b"ASCII85Decode", b"AHx": b"ASCIIHexDecode", b"Fl": b"FlateDecode", b"DCT": b"DCTDecode",
         b"RL": b"RunLengthDecode", b"LZW": b"LZWDecode", b"CCF": b"CCITTFaxDecode"}


def skip_string(buf: bytes, i: int) -> int:
    depth = 0
    n = len(buf)
    while i < n:
        c = buf[i]
        if c == 0x5C:
            i += 2
            continue
        if c == 0x28:
            depth += 1
        elif c == 0x29:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return n


def parse_dict(buf: bytes, i: int):
    """Return (dict, payload_start) or None. Values: bytes token, or list for arrays."""
    d: dict[bytes, object] = {}
    key = None
    stack: list[list] = []
    n = len(buf)
    while i < n:
        m = DTOK.match(buf, i)
        if not m:
            return None
        t = m.group(1)
        i = m.end()
        if t == b"(":
            e = skip_string(buf, m.start(1))
            t = buf[m.start(1) : e]
            i = e
        if t == b"ID" and not stack:
            if i < n and buf[i] in WS:
                i += 2 if buf[i : i + 2] == b"\r\n" else 1
            return d, i
        if t in (b"[", b"<<"):
            stack.append([])
            continue
        if t in (b"]", b">>"):
            if not stack:
                return None
            done = stack.pop()
            t = done  # type: ignore[assignment]
        if stack:
            stack[-1].append(t)
        elif key is None:
            if not (isinstance(t, bytes) and t[:1] == b"/"):
                return None
            key = ABBR.get(t[1:], t[1:])
        else:
            d[key] = t
            key = None
    return None


def dct_end(buf: bytes, s: int) -> int | None:
    n = len(buf)
    if buf[s : s + 2] != b"\xff\xd8":
        return None
    i = s + 2
    while i + 1 < n:
        if buf[i] != 0xFF:
            return None
        while i + 1 < n and buf[i + 1] == 0xFF:
            i += 1
        mk = buf[i + 1]
        i += 2
        if mk == 0xD9:
            return i
        if mk == 0x01 or 0xD0 <= mk <= 0xD7:
            continue
        if i + 1 >= n:
            return None
        i += (buf[i] << 8) | buf[i + 1]
        if mk == 0xDA:
            while True:
                j = buf.find(b"\xff", i)
                if j < 0 or j + 1 >= n:
                    return None
                nx = buf[j + 1]
                if nx == 0 or 0xD0 <= nx <= 0xD7:
                    i = j + 2
                    continue
                i = j
                break
    return None


def rl_end(buf: bytes, s: int) -> int | None:
    i, n = s, len(buf)
    while i < n:
        c = buf[i]
        if c == 128:
            return i + 1
        i += c + 2 if c < 128 else 2
    return None


def prove(buf: bytes, d: dict, s: int):
    """Return (step, end) with end None when unprovable."""
    ln = d.get(b"Length")
    if isinstance(ln, bytes) and ln.isdigit():
        return "L", s + int(ln)
    f = d.get(b"Filter")
    if isinstance(f, list):
        f = f[0] if f else None
    if f is None:
        try:
            w, h = int(d[b"Width"]), int(d[b"Height"])  # type: ignore[arg-type]
        except (KeyError, ValueError, TypeError):
            return "nofilter:bad-WH", None
        im = d.get(b"ImageMask") == b"true"
        cs = d.get(b"ColorSpace")
        if im:
            comps, bpc = 1, 1
        else:
            if isinstance(cs, list):
                comps = 1 if cs and cs[0] in (b"/I", b"/Indexed") else None
            elif isinstance(cs, bytes):
                comps = COMPS.get(cs[1:])
            else:
                comps = None
            if comps is None:
                return "nofilter:named-cs", None
            try:
                bpc = int(d[b"BitsPerComponent"])  # type: ignore[arg-type]
            except (KeyError, ValueError, TypeError):
                return "nofilter:no-bpc", None
        return "computed", s + h * ((w * comps * bpc + 7) // 8)
    if not isinstance(f, bytes):
        return "filter:odd", None
    name = FNAME.get(f[1:], f[1:])
    if name == b"ASCII85Decode":
        j = buf.find(b"~>", s)
        return "A85", (j + 2 if j >= 0 else None)
    if name == b"ASCIIHexDecode":
        j = buf.find(b">", s)
        return "AHx", (j + 1 if j >= 0 else None)
    if name == b"FlateDecode":
        z = zlib.decompressobj()
        pos = s
        try:
            while pos < len(buf) and not z.eof:
                z.decompress(buf[pos : pos + 65536])
                pos += 65536
        except zlib.error:
            return "Fl:error", None
        if not z.eof:
            return "Fl:no-eof", None
        return "Fl", min(pos, len(buf)) - len(z.unused_data)
    if name == b"DCTDecode":
        return "DCT", dct_end(buf, s)
    if name == b"RunLengthDecode":
        return "RL", rl_end(buf, s)
    return "refuse:" + name.decode("latin-1"), None


def ei_after(buf: bytes, e: int) -> int | None:
    n = len(buf)
    while e < n and buf[e] in WS:
        e += 1
    if buf[e : e + 2] == b"EI" and (e + 2 >= n or buf[e + 2] in WS + DELIM):
        return e
    return None


def scan_page(buf: bytes):
    """Yield (outcome, heuristic_agrees) per inline image; also report paints after the first BI."""
    out = []
    i, n = 0, len(buf)
    first_end = None
    payload = []
    stopped = False
    while i < n:
        m = HOP.search(buf, i)
        if not m:
            break
        c = buf[m.start()]
        if c == 0x28:
            i = skip_string(buf, m.start())
            continue
        if c == 0x25:
            j = m.start()
            while j < n and buf[j] not in b"\r\n":
                j += 1
            i = j
            continue
        pd = parse_dict(buf, m.end())
        if pd is None:
            out.append(("dict-unparsed", None))
            stopped = True
            break
        d, s = pd
        step, end = prove(buf, d, s)
        hm = HEUR.search(buf, max(s - 1, 0))
        heur_ei = hm.start() + 1 if hm else None
        if end is not None and end <= n:
            ei = ei_after(buf, end)
            if ei is None:
                out.append((step + ":no-EI-at-end", None))
            else:
                out.append((step + ":ok", heur_ei == ei))
        else:
            ei = None
            out.append((step if step.count(":") else step + ":no-end", None))
        use = ei if ei is not None else heur_ei
        if use is None:
            stopped = True
            break
        if first_end is None:
            first_end = use + 2
        payload.append((s, use))
        i = use + 2
    paints_after = 0
    if first_end is not None:
        pos = first_end
        for a, b in payload[1:]:
            paints_after += len(PAINT.findall(buf, pos, a))
            pos = b + 2
        paints_after += len(PAINT.findall(buf, pos))
    return out, paints_after, stopped


def main() -> None:
    root = Path(sys.argv[1])
    files = sorted(root.rglob("*.pdf")) if root.is_dir() else [root]
    outcome = Counter()
    heur = Counter()
    pages_bi = pages_all_ok = pages_paths_after = 0
    paints_after_total = paints_after_unproved = 0
    bad_pages = []
    mism = []
    nfiles = npages = 0
    for fp in files:
        try:
            doc = fitz.open(str(fp))
            count = len(doc)
        except Exception:
            continue
        nfiles += 1
        for pn in range(count):
            try:
                buf = doc[pn].read_contents()
            except Exception:
                continue
            npages += 1
            if not buf or b"BI" not in buf:
                continue
            res, pa, _ = scan_page(buf)
            if not res:
                continue
            pages_bi += 1
            ok = all(r[0].endswith(":ok") for r in res)
            pages_all_ok += ok
            pages_paths_after += pa > 0
            paints_after_total += pa
            for r, agree in res:
                outcome[r] += 1
                if agree is not None:
                    heur["agree" if agree else "DIFFER"] += 1
                    if not agree and len(mism) < 40:
                        mism.append(f"{fp.relative_to(root) if root.is_dir() else fp.name} p{pn + 1} {r}")
            if not ok:
                paints_after_unproved += pa
                first_bad = next(r[0] for r in res if not r[0].endswith(":ok"))
                bad_pages.append(f"{fp.relative_to(root) if root.is_dir() else fp.name} p{pn + 1} images={len(res)} first-bad={first_bad} paints-after-first-BI={pa}")
        doc.close()
    lines = [
        f"files {nfiles}, pages {npages}, pages with a real BI {pages_bi}, of which every image proved+EI {pages_all_ok}",
        f"pages with paint operators after the first BI {pages_paths_after}; paints after first BI total {paints_after_total}, on not-fully-proved pages {paints_after_unproved}",
        "outcomes per image:",
    ]
    lines += [f"  {k:<28} {v}" for k, v in outcome.most_common()]
    lines.append(f"heuristic vs proved EI: {dict(heur)}")
    lines.append("heuristic differs on:")
    lines += ["  " + s for s in mism]
    lines.append(f"pages not fully proved ({len(bad_pages)}):")
    lines += ["  " + s for s in bad_pages[:80]]
    text = "\n".join(lines)
    if len(sys.argv) > 2:
        Path(sys.argv[2]).write_text(text, encoding="utf-8")
    print(text[:6000])


if __name__ == "__main__":
    main()
