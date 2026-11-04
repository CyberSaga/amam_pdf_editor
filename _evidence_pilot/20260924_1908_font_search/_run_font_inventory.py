# -*- coding: utf-8 -*-
"""Read-only PDF font inventory for true-text pilot candidates. No PDF mutations."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import traceback
from collections import defaultdict
from pathlib import Path

import fitz

ROOT = Path(r"")
TEST = ROOT / "test_files"
OUT = ROOT / "_evidence_pilot" / "20260924_1908_font_search"
OUT.mkdir(parents=True, exist_ok=True)

# Known covered fonts (normalize strip subset prefix)
KNOWN_COVERED = {
    "PMingLiU", "ArialMT", "MicrosoftJhengHeiRegular",
    "DFKaiShu-SB-Estd-BF", "Arial", "Helvetica", "Times", "Times-Roman",
    "TimesNewRomanPSMT", "Courier", "CourierNew",
}

DEFAULTISH = {
    "helvetica", "helvetica-bold", "helvetica-oblique", "helvetica-boldoblique",
    "times-roman", "times-bold", "times-italic", "times-bolditalic",
    "courier", "courier-bold", "courier-oblique", "courier-boldoblique",
    "symbol", "zapfdingbats",
    "arial", "arialmt", "arial-boldmt", "arial-italicmt", "arial-bolditalicmt",
    "timesnewromanpsmt", "timesnewromanps-boldmt", "timesnewromanps-italicmt",
    "timesnewromanps-bolditalicmt", "couriernewpsmt",
    "pmingliu", "mingliu", "mingliu_hkscs",
    "microsoftjhengheiregular", "microsoftjhenghei", "microsoftjhengheibold",
    "calibri", "calibri-bold", "cambria", "segoeui",
}

SPECIALTY_HINTS = re.compile(
    r"Kai|標楷|FangSong|仿宋|SimSun|宋體|YaHei|雅黑|Hei|黑體|Gothic|"
    r"Trebuchet|Aptos|Consolas|IBMPlex|Europa|Canela|IvyPresto|Caslon|"
    r"Symbol|Zapf|Dingbat|Wingding|Noto|SourceHan|AdobeSong|AdobeHeiti|"
    r"STSong|STHeiti|STKai|STFangsong|DFKai|HYS|"
    r"Type3|CIDFont|Vertical|V\b|Identity-V",
    re.I,
)

SUBSET_RE = re.compile(r"^[A-Z]{6}\+")


def strip_subset(name: str) -> str:
    if not name:
        return name
    return SUBSET_RE.sub("", name)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def classify_font(base: str, subtype: str | None = None) -> str:
    clean = strip_subset(base or "")
    low = clean.lower().replace(" ", "")
    if not clean:
        if subtype and "Type3" in subtype:
            return "specialty_type3"
        return "unknown"
    if SPECIALTY_HINTS.search(clean) or SPECIALTY_HINTS.search(subtype or ""):
        # further refine
        if re.search(r"Kai|標楷|DFKai|STKai", clean, re.I):
            return "nondefault_cjk_kai"
        if re.search(r"FangSong|仿宋|STFang", clean, re.I):
            return "nondefault_cjk_fangsong"
        if re.search(r"YaHei|雅黑", clean, re.I):
            return "nondefault_cjk_yahei"
        if re.search(r"SimSun|宋體|STSong|AdobeSong", clean, re.I):
            return "nondefault_cjk_song"
        if re.search(r"Hei|黑體|Gothic|AdobeHeiti|STHeiti", clean, re.I) and "jhenghei" not in low:
            return "nondefault_cjk_hei_other"
        if re.search(r"Symbol|Zapf|Dingbat|Wingding", clean, re.I):
            return "specialty_symbol"
        if re.search(r"Europa|Canela|IvyPresto|Caslon|Trebuchet|Aptos|Consolas|IBMPlex|Noto", clean, re.I):
            return "specialty_latin"
        if subtype and "Type3" in subtype:
            return "specialty_type3"
        return "specialty_other"
    if low in DEFAULTISH or any(low.startswith(d) for d in DEFAULTISH):
        return "defaultish"
    # CJK-ish names not in default list
    if re.search(r"[\u4e00-\u9fff]|CJK|GB|Big5|CNS|Japan|Korea|Hangul|Mincho|Gothic", clean, re.I):
        return "specialty_cjk_other"
    return "other_named"


def parse_font_dict(doc: fitz.Document, xref: int) -> dict:
    info = {
        "xref": xref,
        "BaseFont": None,
        "Subtype": None,
        "Encoding": None,
        "ToUnicode": False,
        "embedded": False,
        "DescendantFonts": None,
        "WMode": None,
    }
    try:
        raw = doc.xref_object(xref) or ""
    except Exception:
        return info
    def grab(key):
        m = re.search(rf"/{key}\s*/([^\s/\[\]<>]+)", raw)
        return m.group(1) if m else None
    info["BaseFont"] = grab("BaseFont")
    info["Subtype"] = grab("Subtype")
    enc = grab("Encoding")
    if enc:
        info["Encoding"] = enc
    else:
        # Encoding as name ref or dict
        m = re.search(r"/Encoding\s+(\d+)\s+0\s+R", raw)
        if m:
            info["Encoding"] = f"xref:{m.group(1)}"
        elif "/Encoding" in raw:
            info["Encoding"] = "dict"
    info["ToUnicode"] = bool(re.search(r"/ToUnicode\s+\d+\s+0\s+R", raw))
    info["embedded"] = bool(re.search(r"/FontFile[123]?\s+\d+\s+0\s+R", raw))
    m = re.search(r"/DescendantFonts\s*\[\s*(\d+)\s+0\s+R", raw)
    if m:
        info["DescendantFonts"] = int(m.group(1))
        try:
            draw = doc.xref_object(int(m.group(1))) or ""
            if not info["BaseFont"]:
                bm = re.search(r"/BaseFont\s*/([^\s/\[\]<>]+)", draw)
                if bm:
                    info["BaseFont"] = bm.group(1)
            if "/FontFile" in draw:
                info["embedded"] = True
            dm = re.search(r"/Subtype\s*/([^\s/]+)", draw)
            if dm and not info["Subtype"]:
                info["Subtype"] = f"Type0/{dm.group(1)}"
            elif dm:
                info["Subtype"] = f"{info['Subtype']}/{dm.group(1)}" if info["Subtype"] else dm.group(1)
            # CIDSystemInfo / WMode via CMap often Identity-H/V on parent
        except Exception:
            pass
    # WMode from Encoding name
    if info["Encoding"] and "Identity-V" in str(info["Encoding"]):
        info["WMode"] = 1
    elif info["Encoding"] and "Identity-H" in str(info["Encoding"]):
        info["WMode"] = 0
    return info


def inventory_pdf(path: Path, max_pages: int | None = None, max_spans_per_font: int = 8) -> dict:
    rel = str(path.relative_to(ROOT)).replace("\\", "/")
    rec = {
        "path": rel,
        "name": path.name,
        "sha256": None,
        "page_count": 0,
        "error": None,
        "text_class": "unknown",
        "fonts_from_shows": {},
        "font_catalog": [],
        "approx_show_count_total": 0,
        "drawing_count_sample": 0,
        "has_get_text_spans": False,
        "notes": [],
    }
    try:
        rec["sha256"] = sha256_file(path)
    except Exception as e:
        rec["error"] = f"hash:{e}"
        return rec

    try:
        doc = fitz.open(path)
    except Exception as e:
        rec["error"] = f"open:{e}"
        return rec

    try:
        rec["page_count"] = doc.page_count
        # font catalog
        seen_xref = set()
        for i in range(doc.page_count if max_pages is None else min(doc.page_count, max_pages or doc.page_count)):
            page = doc[i]
            try:
                for f in page.get_fonts(full=True):
                    # tuple: (xref, ext, type, basefont, name, encoding, ...)
                    xref = f[0]
                    if xref in seen_xref:
                        continue
                    seen_xref.add(xref)
                    parsed = parse_font_dict(doc, xref)
                    base = parsed["BaseFont"] or (f[3] if len(f) > 3 else None) or (f[4] if len(f) > 4 else None)
                    parsed["BaseFont"] = base
                    if not parsed["Subtype"] and len(f) > 2:
                        parsed["Subtype"] = f[2]
                    if not parsed["Encoding"] and len(f) > 5:
                        parsed["Encoding"] = f[5]
                    # ext non-empty often means embedded
                    if len(f) > 1 and f[1]:
                        parsed["embedded"] = True
                        parsed["ext"] = f[1]
                    parsed["clean_name"] = strip_subset(base or "")
                    parsed["class"] = classify_font(base or "", parsed.get("Subtype"))
                    parsed["catalog_only"] = True
                    rec["font_catalog"].append(parsed)
            except Exception as e:
                rec["notes"].append(f"get_fonts page {i}: {e}")

        # Actual text shows via get_texttrace (per-span font)
        font_stats = defaultdict(lambda: {
            "show_count": 0,
            "sample_strings": [],
            "pages": set(),
            "sizes": set(),
            "dirs": set(),
            "basefont_guess": None,
            "resource_names": set(),
        })
        span_total = 0
        pages_to_scan = range(doc.page_count if max_pages is None else min(doc.page_count, max_pages))
        for i in pages_to_scan:
            page = doc[i]
            try:
                traces = page.get_texttrace()
            except Exception as e:
                rec["notes"].append(f"texttrace page {i}: {e}")
                traces = []
            for tr in traces:
                fontname = tr.get("font") or ""
                text = "".join(chr(c[0]) if c[0] < 0x110000 else "?" for c in tr.get("chars") or [])
                # skip empty
                if not text.strip() and not text:
                    # still count if has chars with codes
                    if not tr.get("chars"):
                        continue
                span_total += 1
                clean = strip_subset(fontname)
                st = font_stats[clean or fontname or "(unnamed)"]
                st["show_count"] += 1
                st["pages"].add(i)
                st["basefont_guess"] = clean or fontname
                if tr.get("size") is not None:
                    try:
                        st["sizes"].add(round(float(tr["size"]), 2))
                    except Exception:
                        pass
                d = tr.get("dir")
                if d is not None:
                    st["dirs"].add(str(tuple(d) if hasattr(d, "__iter__") else d))
                sample = text.replace("\n", " ").strip()
                if sample and len(st["sample_strings"]) < max_spans_per_font:
                    if sample not in st["sample_strings"]:
                        st["sample_strings"].append(sample[:80])

            # drawings sample on first 2 pages
            if i < 2:
                try:
                    rec["drawing_count_sample"] += len(page.get_drawings())
                except Exception:
                    pass

            # also dict spans for resource cross-check
            try:
                d = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
                for b in d.get("blocks") or []:
                    for line in b.get("lines") or []:
                        for span in line.get("spans") or []:
                            rec["has_get_text_spans"] = True
            except Exception:
                pass

        rec["approx_show_count_total"] = span_total

        # Merge catalog info into show fonts
        catalog_by_clean = {}
        for c in rec["font_catalog"]:
            catalog_by_clean[c.get("clean_name") or ""] = c

        shows_out = {}
        for name, st in font_stats.items():
            cat = catalog_by_clean.get(name) or catalog_by_clean.get(strip_subset(name))
            # fuzzy: catalog base may differ slightly
            if not cat:
                for ck, cv in catalog_by_clean.items():
                    if ck and name and (ck in name or name in ck):
                        cat = cv
                        break
            entry = {
                "BaseFont": (cat or {}).get("BaseFont") or st["basefont_guess"],
                "clean_name": name,
                "Subtype": (cat or {}).get("Subtype"),
                "Encoding": (cat or {}).get("Encoding"),
                "ToUnicode": (cat or {}).get("ToUnicode"),
                "embedded": (cat or {}).get("embedded"),
                "WMode": (cat or {}).get("WMode"),
                "approx_show_count": st["show_count"],
                "pages": sorted(st["pages"])[:30],
                "page_count_with_font": len(st["pages"]),
                "sample_sizes": sorted(st["sizes"])[:10],
                "sample_dirs": sorted(st["dirs"])[:6],
                "sample_decoded_strings": st["sample_strings"][:6],
                "class": classify_font(
                    (cat or {}).get("BaseFont") or name,
                    (cat or {}).get("Subtype"),
                ),
                "in_catalog": bool(cat),
            }
            # vertical writing heuristic
            if entry["WMode"] == 1 or any("Identity-V" in str(x) for x in [entry["Encoding"]]):
                entry["vertical_hint"] = True
            if any(d in ("(0, -1)", "(0.0, -1.0)", "(0, -1.0)") for d in st["dirs"]):
                entry["dir_verticalish"] = True
            shows_out[name] = entry

        rec["fonts_from_shows"] = shows_out

        # text_class
        if span_total > 0:
            rec["text_class"] = "true_text"
        elif rec["drawing_count_sample"] > 0 and not rec["font_catalog"]:
            rec["text_class"] = "vector_outline"
        elif not rec["font_catalog"] and span_total == 0:
            # try more pages for drawings if large
            if rec["page_count"] > 0:
                try:
                    d0 = len(doc[0].get_drawings())
                    if d0 > 0:
                        rec["text_class"] = "vector_outline"
                        rec["drawing_count_sample"] = d0
                    else:
                        rec["text_class"] = "unknown_or_empty"
                except Exception:
                    rec["text_class"] = "unknown_or_empty"
            else:
                rec["text_class"] = "empty"
        elif rec["font_catalog"] and span_total == 0:
            rec["text_class"] = "fonts_cataloged_but_no_extractable_shows"
        else:
            rec["text_class"] = "unknown"

        # Mark catalog-only fonts not in shows
        show_names = set(shows_out.keys())
        for c in rec["font_catalog"]:
            cn = c.get("clean_name") or ""
            if cn and cn not in show_names and not any(cn in s or s in cn for s in show_names):
                c["unused_in_extractable_shows"] = True

    except Exception as e:
        rec["error"] = f"scan:{e}"
        rec["notes"].append(traceback.format_exc()[-500:])
    finally:
        doc.close()
    return rec


def list_target_pdfs():
    """Top-level test_files + sample-files + Test-PDF-Files; veraPDF summarized separately."""
    paths = []
    for p in sorted(TEST.glob("*.pdf")):
        paths.append(p)
    for sub in ("sample-files-main", "Test-PDF-Files-master"):
        d = TEST / sub
        if d.is_dir():
            paths.extend(sorted(d.rglob("*.pdf")))
    return paths


def light_verapdf_fonts(limit_files: int = 400):
    """Unique BaseFont names from veraPDF corpus (font-focused paths preferred)."""
    vera = TEST / "veraPDF-corpus-staging"
    if not vera.is_dir():
        return {"error": "missing", "unique_fonts": [], "scanned": 0}
    all_pdfs = list(vera.rglob("*.pdf"))
    # Prefer Fonts path
    preferred = [p for p in all_pdfs if "Font" in str(p)]
    others = [p for p in all_pdfs if p not in preferred]
    ordered = preferred + others
    unique = {}
    scanned = 0
    errors = 0
    for p in ordered[:limit_files]:
        try:
            doc = fitz.open(p)
            for i in range(min(doc.page_count, 2)):
                for f in doc[i].get_fonts(full=True):
                    base = strip_subset(f[3] if len(f) > 3 else "") or (f[4] if len(f) > 4 else "")
                    if not base:
                        continue
                    if base not in unique:
                        unique[base] = {
                            "BaseFont": base,
                            "Subtype": f[2] if len(f) > 2 else None,
                            "Encoding": f[5] if len(f) > 5 else None,
                            "class": classify_font(base, f[2] if len(f) > 2 else None),
                            "example": str(p.relative_to(ROOT)).replace("\\", "/"),
                        }
            doc.close()
            scanned += 1
        except Exception:
            errors += 1
    return {
        "corpus_pdf_count": len(all_pdfs),
        "scanned": scanned,
        "errors": errors,
        "unique_fonts": sorted(unique.values(), key=lambda x: x["BaseFont"]),
        "note": f"light scan first {limit_files} (Fonts-path preferred); font names only",
    }


def load_known_cases():
    known = {
        "hvac_cases": [],
        "ecc_text_cases": [],
        "documented_fonts": set(),
        "sources": [],
    }
    # HVAC
    hvac = ROOT / "scripts" / "experiment_hvac_font_edits.py"
    if hvac.exists():
        known["sources"].append(str(hvac.relative_to(ROOT)))
        # from results
    for results in [
        ROOT / "output" / "pdf" / "manual-font-study" / "results.json",
        ROOT / "output" / "pdf" / "cad-font-study" / "results.json",
    ]:
        if not results.exists():
            continue
        known["sources"].append(str(results.relative_to(ROOT)).replace("\\", "/"))
        data = json.loads(results.read_text(encoding="utf-8"))
        if "edits" in data:
            for e in data["edits"]:
                known["hvac_cases"].append({
                    "case": e.get("case"),
                    "font": e.get("font"),
                    "before": e.get("before"),
                    "page": e.get("page"),
                })
                if e.get("font"):
                    known["documented_fonts"].add(strip_subset(e["font"]))
        if "reports" in data:
            for rep in data["reports"]:
                for e in rep.get("edits") or []:
                    # vector or text
                    if "label" in e and e.get("method", "").startswith("source_vector"):
                        known["ecc_text_cases"].append({"type": "vector", "label": e["label"], "file": rep.get("file")})
                    else:
                        known["ecc_text_cases"].append(e)
    # CAD TEXT_CASES hardcode from script knowledge
    known["ecc_documented_text"] = [
        {"inventory": "ecc-1", "seq": 31, "before": "專案名稱", "font": "DFKaiShu-SB-Estd-BF"},
        {"inventory": "ecc-2", "seq": 38, "before": "平面配置圖", "font": "DFKaiShu-SB-Estd-BF"},
        {"inventory": "ecc-3", "seq": 57, "before": "113.05.03", "font": "DFKaiShu-SB-Estd-BF"},
        {"inventory": "ecc-4", "seq": 60, "before": "[ECC_DWG]", "font": "DFKaiShu-SB-Estd-BF"},
    ]
    for c in known["ecc_documented_text"]:
        known["documented_fonts"].add(c["font"])
    # HVAC cases from script
    known["hvac_documented"] = [
        {"case": 1, "font": "PMingLiU"},
        {"case": 2, "font": "PMingLiU"},
        # from prior evidence - fill from results if present
    ]
    # evidence pilot cases.json
    for cases_path in (ROOT / "_evidence_pilot").rglob("cases.json"):
        try:
            cj = json.loads(cases_path.read_text(encoding="utf-8"))
            known["sources"].append(str(cases_path.relative_to(ROOT)).replace("\\", "/"))
            items = cj if isinstance(cj, list) else cj.get("cases") or cj.get("items") or []
            if isinstance(cj, dict) and not items:
                # maybe dict of cases
                for k, v in cj.items():
                    if isinstance(v, dict) and ("font" in v or "case_id" in v or "before" in v):
                        items.append(v)
            for it in items:
                if not isinstance(it, dict):
                    continue
                f = it.get("font") or it.get("BaseFont")
                if f:
                    known["documented_fonts"].add(strip_subset(f))
        except Exception:
            pass
    known["documented_fonts"] = sorted(known["documented_fonts"])
    return known


def main():
    print("Listing PDFs...", flush=True)
    paths = list_target_pdfs()
    print(f"Deep-scan targets: {len(paths)}", flush=True)

    # Size-based page limits for huge files
    results = []
    for p in paths:
        size = p.stat().st_size
        # skip damaged twin of large if identical-ish — still scan
        max_pages = None
        if size > 30_000_000:
            max_pages = 12  # HVAC / large: sample first 12 pages thoroughly enough
            print(f"LARGE {p.name} ({size}) -> max_pages={max_pages}", flush=True)
        elif size > 5_000_000:
            max_pages = 30
        print(f"Scanning {p.relative_to(ROOT)} ...", flush=True)
        rec = inventory_pdf(p, max_pages=max_pages)
        results.append(rec)
        nfonts = len(rec.get("fonts_from_shows") or {})
        print(f"  class={rec['text_class']} shows={rec['approx_show_count_total']} fonts={nfonts} err={rec.get('error')}", flush=True)

    print("Light veraPDF scan...", flush=True)
    vera = light_verapdf_fonts(500)

    known = load_known_cases()

    raw_path = OUT / "raw_inventory.json"
    raw_path.write_text(json.dumps({
        "stamp": "20260924_1908",
        "pdfs": results,
        "verapdf_light": vera,
        "known_cases": known,
    }, ensure_ascii=False, indent=2, default=list), encoding="utf-8")
    print(f"Wrote {raw_path}", flush=True)

    # Build candidates
    already = {
        "PMingLiU", "ArialMT", "MicrosoftJhengHeiRegular", "DFKaiShu-SB-Estd-BF",
        "Arial", "Helvetica", "Times-Roman", "TimesNewRomanPSMT",
    }
    # also from known documented
    already |= set(known.get("documented_fonts") or [])

    candidates = []
    vector_only_fonts = []  # fonts that only appear where text_class is vector — N/A usually empty
    vector_only_pdfs = []

    for rec in results:
        if rec["text_class"] == "vector_outline":
            vector_only_pdfs.append({
                "path": rec["path"],
                "sha256": rec["sha256"],
                "note": "no extractable true-text shows; drawings present",
                "font_catalog": rec.get("font_catalog") or [],
            })
            continue
        for fname, finfo in (rec.get("fonts_from_shows") or {}).items():
            cls = finfo.get("class") or ""
            clean = finfo.get("clean_name") or strip_subset(finfo.get("BaseFont") or fname)
            is_nondefault = cls.startswith("nondefault") or cls.startswith("specialty") or cls in ("other_named", "specialty_cjk_other")
            # skip pure defaultish unless specialty latin already flagged
            if cls == "defaultish" and clean in already:
                continue
            if not is_nondefault and clean in already:
                continue
            if not is_nondefault and cls == "defaultish":
                continue
            # fingerprint
            samples = finfo.get("sample_decoded_strings") or []
            pages = finfo.get("pages") or []
            has_case = clean in already or clean in (known.get("documented_fonts") or [])
            # HVAC DFKaiShu / SimSun etc.
            risk = []
            if "CAD" in rec["name"].upper() or "HVAC" in rec["name"].upper() or "ECC" in rec["name"].upper():
                risk.append("CAD_titleblock_possible")
            if finfo.get("dir_verticalish") or finfo.get("vertical_hint"):
                risk.append("vertical_or_rotated_tm")
            if finfo.get("approx_show_count", 0) < 3:
                risk.append("few_shows")
            if not finfo.get("ToUnicode") and finfo.get("in_catalog"):
                risk.append("no_ToUnicode_flag")
            if "Type3" in str(finfo.get("Subtype") or ""):
                risk.append("Type3_custom_glyphs")
            # suggested primary variable
            if "kai" in cls:
                primary = "cjk_kai_encoding_widths"
            elif "yahei" in cls or "hei" in cls:
                primary = "cjk_hei_variant_beyond_jhenghei"
            elif "song" in cls or "simsun" in clean.lower():
                primary = "cjk_song_simsun"
            elif "fangsong" in cls:
                primary = "cjk_fangsong"
            elif "latin" in cls:
                primary = "specialty_latin_metrics"
            elif "type3" in cls:
                primary = "type3_glyph_editability"
            elif "symbol" in cls:
                primary = "symbol_encoding"
            elif finfo.get("vertical_hint") or finfo.get("dir_verticalish"):
                primary = "vertical_writing_wmode"
            else:
                primary = "font_roundtrip_fidelity"

            # rank score
            score = 0
            if cls.startswith("nondefault_cjk"):
                score += 50
            if cls.startswith("specialty"):
                score += 30
            if clean not in already:
                score += 20
            if rec["text_class"] == "true_text":
                score += 15
            if samples:
                score += 10
            if finfo.get("approx_show_count", 0) >= 5:
                score += 5
            if has_case:
                score -= 40  # already piloted / documented
            # demote vera-like / password / trivial
            if "sample-files" in rec["path"] or "Test-PDF" in rec["path"]:
                score -= 5
            if "password" in rec["name"].lower() or "corrupted" in rec["name"].lower():
                score -= 20

            candidates.append({
                "status": "candidate_discovered" if not has_case else "known_covered_or_documented",
                "has_explicit_case_id": bool(has_case and clean in {
                    "PMingLiU", "ArialMT", "MicrosoftJhengHeiRegular", "DFKaiShu-SB-Estd-BF"
                }),
                # Note: JhengHei on ECC has no documented edit seq — flag separately
                "font_name": clean,
                "BaseFont": finfo.get("BaseFont"),
                "class": cls,
                "source_pdf": rec["path"],
                "sha256": rec["sha256"],
                "text_class": rec["text_class"],
                "page_index_samples": pages[:5],
                "approx_show_count": finfo.get("approx_show_count"),
                "sample_original_text": samples[:4],
                "Subtype": finfo.get("Subtype"),
                "Encoding": finfo.get("Encoding"),
                "ToUnicode": finfo.get("ToUnicode"),
                "embedded": finfo.get("embedded"),
                "suggested_primary_variable": primary,
                "risk_notes": risk,
                "rank_score": score,
                "case_id": None,  # never invent
            })

    # Special: ECC MicrosoftJhengHeiRegular — present, no documented edit seq
    for c in candidates:
        if c["font_name"] == "MicrosoftJhengHeiRegular" and "ecc-dwg" in c["source_pdf"]:
            c["has_explicit_case_id"] = False
            c["status"] = "candidate_discovered"
            c["notes"] = "ECC JhengHei present; no documented TEXT_CASES edit seq (unlike HVAC case7)"
            c["rank_score"] = c.get("rank_score", 0) + 25
        if c["font_name"] == "DFKaiShu-SB-Estd-BF" and "01_" in c["source_pdf"]:
            c["has_explicit_case_id"] = False
            c["status"] = "candidate_discovered"
            c["notes"] = "01_報告 DFKaiShu present; no documented case_id"
            c["rank_score"] = c.get("rank_score", 0) + 15
        if c["font_name"] in ("SimSun", "TrebuchetMS", "MicrosoftYaHei-Bold") and "hvac-dwg" in c["source_pdf"]:
            c["has_explicit_case_id"] = False
            c["status"] = "candidate_discovered"
            c["notes"] = "HVAC specialty face present; no numbered CASES entry for this font"
            c["rank_score"] = c.get("rank_score", 0) + 20

    # Add veraPDF specialty as low-priority name-only candidates
    for vf in vera.get("unique_fonts") or []:
        if not str(vf.get("class", "")).startswith(("nondefault", "specialty", "other")):
            continue
        clean = strip_subset(vf["BaseFont"])
        if clean in already:
            continue
        # skip if already in candidates
        if any(c["font_name"] == clean for c in candidates):
            continue
        candidates.append({
            "status": "candidate_discovered",
            "has_explicit_case_id": False,
            "font_name": clean,
            "BaseFont": vf["BaseFont"],
            "class": vf.get("class"),
            "source_pdf": vf.get("example"),
            "sha256": None,
            "text_class": "unknown_verapdf_light",
            "page_index_samples": [],
            "approx_show_count": None,
            "sample_original_text": [],
            "Subtype": vf.get("Subtype"),
            "Encoding": vf.get("Encoding"),
            "suggested_primary_variable": "corpus_fixture_only",
            "risk_notes": ["veraPDF_corpus", "sha_not_computed_this_pass"],
            "rank_score": 5,
            "case_id": None,
        })

    candidates.sort(key=lambda x: (-x.get("rank_score", 0), x.get("font_name") or ""))

    # Dedupe key font+pdf
    seen = set()
    deduped = []
    for c in candidates:
        key = (c.get("font_name"), c.get("source_pdf"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(c)

    nondefault_path = OUT / "NONDEFAULT_CANDIDATES.json"
    nondefault_path.write_text(json.dumps({
        "stamp": "20260924_1908",
        "timezone": "Asia/Taipei",
        "search_only": True,
        "no_case_ids_invented": True,
        "already_covered_fonts": sorted(already),
        "candidates": deduped,
        "vector_only_pdfs": vector_only_pdfs,
        "vector_only_fonts_note": "CHB/[AIRPORT_CODE] have empty font resources; lettering is path outlines — not true-text pilotable",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {nondefault_path} ({len(deduped)} candidates)", flush=True)

    # Also dump summary counts for parent
    summary = {
        "stamp": "20260924_1908",
        "pdfs_deep_scanned": len(results),
        "verapdf_corpus_total": vera.get("corpus_pdf_count"),
        "verapdf_light_scanned": vera.get("scanned"),
        "true_text_pdfs": sum(1 for r in results if r["text_class"] == "true_text"),
        "vector_outline_pdfs": sum(1 for r in results if r["text_class"] == "vector_outline"),
        "candidate_count": len(deduped),
        "new_nondefault_fonts": sorted({
            c["font_name"] for c in deduped
            if c["status"] == "candidate_discovered"
            and c["font_name"] not in {
                "PMingLiU", "ArialMT", "MicrosoftJhengHeiRegular", "DFKaiShu-SB-Estd-BF"
            }
        }),
    }
    (OUT / "_scan_meta.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()