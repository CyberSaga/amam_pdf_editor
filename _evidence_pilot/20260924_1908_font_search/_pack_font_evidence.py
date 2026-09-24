# -*- coding: utf-8 -*-
import json
from pathlib import Path

ROOT = Path(r"")
OUT = ROOT / "_evidence_pilot" / "20260924_1908_font_search"
STAMP = "20260924_1908"

raw = json.loads((OUT / "raw_inventory.json").read_text(encoding="utf-8"))
fps = json.loads((OUT / "FINGERPRINTS.json").read_text(encoding="utf-8"))

vector_pdfs = []
for rec in raw["pdfs"]:
    if rec["text_class"] == "vector_outline":
        vector_pdfs.append({
            "path": rec["path"],
            "sha256": rec["sha256"],
            "name": rec["name"],
            "font_resources": [],
            "note": "vector/outline lettering only — NOT true-text pilotable",
        })

candidates = []

def add_cand(**kw):
    kw.setdefault("case_id", None)
    kw.setdefault("has_explicit_case_id", False)
    kw.setdefault("status", "candidate_discovered")
    candidates.append(kw)

ecc_jh = fps.get("[ECC_DWG]", {}).get("MicrosoftJhengHeiRegular", [])
add_cand(
    rank=1,
    font_name="MicrosoftJhengHeiRegular",
    source_pdf="test_files/[ECC_DWG].pdf",
    sha256="0f75dd10ed77214c5cf159d40f909cd402231761886cb0ed3821368ac0ab1853",
    page_index=0,
    seq_samples=[x["seq"] for x in ecc_jh[:5]],
    sample_original_text=[x["original_text"] for x in ecc_jh[:5]],
    text_class="true_text",
    Subtype="Type0/CIDFontType2",
    Encoding="Identity-H",
    embedded=True,
    ToUnicode=True,
    approx_show_count=30,
    suggested_primary_variable="ecc_jhenghei_plan_label_edit_no_prior_case",
    risk_notes=["CAD_plan_labels", "nested_geometry_nearby", "no_documented_TEXT_CASES_on_ECC"],
    notes="ECC F1; HVAC JhengHei already piloted (case7) but ECC face/context undocumented",
)

hvac_sim = fps.get("HVAC", {}).get("SimSun", [])
add_cand(
    rank=2,
    font_name="SimSun",
    source_pdf="test_files/[HVAC_DWG_PDF]",
    sha256="9da93de982145c46af0d34a978b4bbaa1167f0937327dedb44ecad4d50fca0a2",
    page_index=hvac_sim[0]["page_index"] if hvac_sim else 6,
    seq_samples=[x["seq"] for x in hvac_sim[:5]],
    sample_original_text=[x["original_text"] for x in hvac_sim[:5]],
    text_class="true_text",
    Subtype="CIDFontType2",
    Encoding="Identity-H",
    embedded=True,
    ToUnicode=True,
    approx_show_count=15,
    suggested_primary_variable="cjk_song_simsun_cad_labels",
    risk_notes=["reflected_or_rotated_Tm_dir_(0,1)", "short_labels", "CAD_floor_tags"],
    notes="HVAC pages 6–11; no numbered CASES entry",
)

hvac_kai = fps.get("HVAC", {}).get("DFKaiShu-SB-Estd-BF", [])
add_cand(
    rank=3,
    font_name="DFKaiShu-SB-Estd-BF",
    source_pdf="test_files/[HVAC_DWG_PDF]",
    sha256="9da93de982145c46af0d34a978b4bbaa1167f0937327dedb44ecad4d50fca0a2",
    page_index=hvac_kai[0]["page_index"] if hvac_kai else 0,
    seq_samples=[x["seq"] for x in hvac_kai[:5]],
    sample_original_text=[x["original_text"] for x in hvac_kai[:5]],
    text_class="true_text",
    Subtype="CIDFontType2",
    Encoding="Identity-H",
    embedded=True,
    ToUnicode=True,
    approx_show_count=112,
    suggested_primary_variable="hvac_kai_cover_block_vs_ecc_titleblock",
    risk_notes=["same_family_as_ECC_pilots_but_different_PDF_layout", "rotated_Tm_on_some_pages", "no_HVAC_case_id"],
    notes="Family piloted on ECC only; HVAC Kai shows lack explicit case_id — do not invent",
)

hvac_treb = fps.get("HVAC", {}).get("TrebuchetMS", [])
add_cand(
    rank=4,
    font_name="TrebuchetMS",
    source_pdf="test_files/[HVAC_DWG_PDF]",
    sha256="9da93de982145c46af0d34a978b4bbaa1167f0937327dedb44ecad4d50fca0a2",
    page_index=hvac_treb[0]["page_index"] if hvac_treb else 3,
    seq_samples=[x["seq"] for x in hvac_treb[:5]],
    sample_original_text=[x["original_text"] for x in hvac_treb[:5]],
    text_class="true_text",
    Subtype="CIDFontType2",
    Encoding="Identity-H",
    embedded=True,
    ToUnicode=True,
    approx_show_count=9,
    suggested_primary_variable="latin_specialty_trebuchet_cid_identity_h",
    risk_notes=["repeated_identical_string_across_pages", "dir_(0,1)_rotated"],
    notes="Latin specialty (not Arial/Helvetica/Times); no CASES entry",
)

hvac_yh = fps.get("HVAC", {}).get("MicrosoftYaHei-Bold", [])
add_cand(
    rank=5,
    font_name="MicrosoftYaHei-Bold",
    source_pdf="test_files/[HVAC_DWG_PDF]",
    sha256="9da93de982145c46af0d34a978b4bbaa1167f0937327dedb44ecad4d50fca0a2",
    page_index=hvac_yh[0]["page_index"] if hvac_yh else 3,
    seq_samples=[x["seq"] for x in hvac_yh[:3]],
    sample_original_text=[x["original_text"] for x in hvac_yh[:3]],
    text_class="true_text",
    Subtype="CIDFontType2",
    Encoding="Identity-H",
    embedded=True,
    ToUnicode=True,
    approx_show_count=1,
    suggested_primary_variable="cjk_yahei_bold_beyond_jhenghei",
    risk_notes=["only_1_show_in_first_12_pages", "large_Tf~37", "dir_(0,1)"],
    notes="Hei variant beyond JhengHei; sparse",
)

hvac_jhb = fps.get("HVAC", {}).get("MicrosoftJhengHeiBold", [])
add_cand(
    rank=6,
    font_name="MicrosoftJhengHeiBold",
    source_pdf="test_files/[HVAC_DWG_PDF]",
    sha256="9da93de982145c46af0d34a978b4bbaa1167f0937327dedb44ecad4d50fca0a2",
    page_index=0,
    seq_samples=[x["seq"] for x in hvac_jhb],
    sample_original_text=[x["original_text"] for x in hvac_jhb],
    text_class="true_text",
    Subtype="Type0",
    Encoding="Identity-H",
    embedded=True,
    ToUnicode=True,
    approx_show_count=2,
    suggested_primary_variable="jhenghei_bold_weight_variant",
    risk_notes=["only_2_shows_on_cover", "weight_variant_of_piloted_regular"],
)

rep = fps.get("01_報告", {}).get("DFKaiShu-SB-Estd-BF", [])
add_cand(
    rank=7,
    font_name="DFKaiShu-SB-Estd-BF",
    source_pdf="test_files/01_報告書.pdf",
    sha256="880a637fe94734411fda89043e7abbe060b938b7a6dd09c04292bca19f8b320f",
    page_index=rep[0]["page_index"] if rep else 0,
    seq_samples=[x["seq"] for x in rep[:5]],
    sample_original_text=[x["original_text"] for x in rep[:5]],
    text_class="true_text",
    Subtype="Type0",
    Encoding="Identity-H",
    embedded=True,
    ToUnicode=True,
    approx_show_count=2265,
    suggested_primary_variable="office_report_kai_long_runs",
    risk_notes=["long_paragraph_runs", "multi_page_23", "no_documented_case_id", "column_layout_possible"],
    notes="Dominant face; no TEXT_CASES / case_id",
)

add_cand(
    rank=8,
    font_name="Europa-Regular / Canela / IvyPresto / ACaslonPro",
    source_pdf="test_files/Awareness.pdf",
    sha256="2cdee708c3a8ff01b3e7e7ebad500323a879f3a9d82ac369fcf6b87094564347",
    page_index=0,
    seq_samples=[],
    sample_original_text=[
        "STANFORD RAISES ALCOHOL INTOLERANCE AWARENESS",
        "HEALTH",
        "WELLNESS",
        "By Charlene Dizon",
    ],
    text_class="true_text",
    Subtype="Type1",
    Encoding="WinAnsiEncoding",
    embedded=True,
    ToUnicode=True,
    approx_show_count=29,
    suggested_primary_variable="specialty_latin_type1_cff",
    risk_notes=[
        "project_shows()_returns_0_stream_replay_gap",
        "Type1_CFF_WinAnsi",
        "rotated_dir_on_some_Europa_spans",
        "no_CJK",
    ],
    notes="Specialty Latin; MuPDF texttrace sees text but text_commit shows() empty",
)

add_cand(
    rank=9,
    font_name="Consolas (+ many Type3 unnamed CJK)",
    source_pdf="test_files/test-complexed-layout.pdf",
    sha256="faefb744200aad617504802b72fd20c7525bab203f849f22a38af07f127bedf3",
    page_index=0,
    seq_samples=[629, 630, 632],
    sample_original_text=["            cursor", ":", "'pointer'"],
    text_class="true_text",
    Subtype="Type0/CIDFontType2 + Type3",
    Encoding="Identity-H / custom Type3",
    embedded=True,
    approx_show_count=1518,
    suggested_primary_variable="consolas_mono_and_type3_cjk",
    risk_notes=["100+_Type3_faces_per_glyph_bucket", "Type3_not_standard_CID", "screenshot_UI_PDF"],
)

gothic = fps.get("test-hierarchy-bookmarks", {}).get("MS-Gothic", [])
add_cand(
    rank=10,
    font_name="MS-Gothic",
    source_pdf="test_files/test-hierarchy-bookmarks.pdf",
    sha256="f93ba509283b805c629a48d2adc0b3a3a21412b8437fde1de28a5ae773fa5a78",
    page_index=1,
    seq_samples=[x["seq"] for x in gothic],
    sample_original_text=[x["original_text"] for x in gothic],
    text_class="true_text",
    Subtype="Type0/CIDFontType2",
    Encoding="Identity-H",
    embedded=True,
    ToUnicode=True,
    approx_show_count=4,
    suggested_primary_variable="cjk_gothic_hei_jp_variant",
    risk_notes=["only_4_single_char_shows", "Hei/Gothic_beyond_JhengHei"],
)

add_cand(
    rank=11,
    font_name="Aptos",
    source_pdf="test_files/test-vertical-texts.pdf",
    sha256="3b0480373461cefa9329c2bccc92c45a83e043b027bedd1a22269aedc2123832",
    page_index=0,
    seq_samples=[0, 1, 2],
    sample_original_text=["wh", "en ", "I"],
    text_class="true_text",
    Subtype="TrueType",
    Encoding="WinAnsiEncoding",
    embedded=True,
    ToUnicode=False,
    approx_show_count=28,
    suggested_primary_variable="vertical_writing_dir_matrix",
    risk_notes=["dir_near_(0,1)_vertical_layout", "WinAnsi_no_ToUnicode", "synthetic_fixture"],
)

add_cand(
    rank=12,
    font_name='2,Bold (custom embedded CID) / 1 (TrueType)',
    source_pdf="test_files/test-colored-background.pdf",
    sha256="00640a01cecf0bfdf58bf72d6cbd20957ef98dcfc87b32f7f8b9e4a42eb36dba",
    page_index=0,
    seq_samples=[0, 1],
    sample_original_text=["Revit", "前置作業操作流程"],
    text_class="true_text",
    Subtype="Type0 + TrueType",
    Encoding="Identity-H / WinAnsi",
    embedded=True,
    approx_show_count=103,
    suggested_primary_variable="custom_named_embedded_cid",
    risk_notes=["nonstandard_BaseFont_names", "CJK_in_2,Bold"],
)

add_cand(
    rank=13,
    font_name="SymbolMT",
    source_pdf="test_files/test-large-file.pdf",
    sha256="a385b8615355690a1279e27a246eb374e3b47564af82bb3ecd96907ddb9fc3cd",
    page_index=1,
    seq_samples=[],
    sample_original_text=["\\uf0d3"],
    text_class="true_text",
    Subtype="Type0/CIDFontType2",
    Encoding="Identity-H",
    embedded=True,
    approx_show_count=1,
    suggested_primary_variable="symbol_encoding_as_text",
    risk_notes=["single_show", "symbol_not_prose", "large_402page_file"],
)

known_ref = [
    {"font_name": "PMingLiU", "where": "HVAC", "has_explicit_case_id": True, "notes": "HVAC cases 1/2/..."},
    {"font_name": "ArialMT", "where": "HVAC", "has_explicit_case_id": True, "notes": "HVAC Latin cases"},
    {"font_name": "MicrosoftJhengHeiRegular", "where": "HVAC", "has_explicit_case_id": True, "notes": "HVAC case7"},
    {"font_name": "DFKaiShu-SB-Estd-BF", "where": "ECC", "has_explicit_case_id": True, "notes": "ecc-1/2/3/(4)"},
]

gaps = [
    {
        "issue": "CHB and [AIRPORT_CODE] have font_resources=[] — all lettering is vector outlines",
        "impact": "cannot pilot as true-text success",
    },
    {
        "issue": "Awareness specialty Latin is extractable via MuPDF texttrace but project shows() returns 0",
        "impact": "current text_commit stream path may not see Type1 magazine text",
    },
    {
        "issue": "test-complexed-layout CJK is mostly Type3 (one face per glyph bucket)",
        "impact": "hard to pilot as normal CID true-text; classify carefully",
    },
    {
        "issue": "HVAC MicrosoftYaHei-Bold only 1 show in first 12 pages",
        "impact": "sparse fingerprint; may need deeper page scan if piloted",
    },
    {
        "issue": "01_報告 DFKaiShu dominant but no documented case_id",
        "impact": "candidate_discovered only; do not invent ids",
    },
    {
        "issue": "ECC MicrosoftJhengHeiRegular has shows but no TEXT_CASES edit seq",
        "impact": "best new ECC variable beyond Kai",
    },
]

nondefault = {
    "stamp": STAMP,
    "timezone": "Asia/Taipei",
    "search_only": True,
    "no_pdf_mutations": True,
    "no_case_ids_invented": True,
    "already_covered_do_not_rediscover": known_ref,
    "ranked_candidates_for_future_pilots": candidates,
    "vector_only_pdfs": vector_pdfs,
    "vector_only_fonts": [],
    "gaps": gaps,
    "verapdf_note": {
        "corpus_pdf_count": raw["verapdf_light"]["corpus_pdf_count"],
        "light_scanned": raw["verapdf_light"]["scanned"],
        "unique_font_names": len(raw["verapdf_light"]["unique_fonts"]),
        "role": "fixture/corpus only — not primary CAD pilots",
    },
}

(OUT / "NONDEFAULT_CANDIDATES.json").write_text(
    json.dumps(nondefault, ensure_ascii=False, indent=2), encoding="utf-8"
)

# FONT_INVENTORY_FULL.md
lines = []
lines.append(f"# FONT_INVENTORY_FULL — {STAMP} (Asia/Taipei)")
lines.append("")
lines.append("Search-only inventory. **No PDF mutations. No product source changes. No case_ids invented.**")
lines.append("")
lines.append("## Scope")
lines.append(
    f"- Deep-scanned PDFs: **{len(raw['pdfs'])}** (`test_files/*.pdf` + `sample-files-main` + `Test-PDF-Files-master`)"
)
lines.append(
    f"- veraPDF corpus: **{raw['verapdf_light']['corpus_pdf_count']}** total; light font-name scan **{raw['verapdf_light']['scanned']}** files"
)
lines.append(
    "- Method: PyMuPDF `get_fonts(full=True)` + `get_texttrace()` for actual shows; xref parse for Subtype/Encoding/ToUnicode/embedded"
)
lines.append("- Stream seq fingerprints via project `shows()` where available (see FINGERPRINTS.json)")
lines.append("")
lines.append("## Known already (not rediscovered as new)")
lines.append("- HVAC: PMingLiU, ArialMT, MicrosoftJhengHeiRegular — piloted")
lines.append("- ECC: DFKaiShu-SB-Estd-BF — piloted ecc-1/2/3")
lines.append("- ECC MicrosoftJhengHeiRegular — present, **no** documented edit seq → listed as candidate")
lines.append("- CHB + [AIRPORT_CODE] — vector only")
lines.append("- 01_報告 DFKaiShu — present, **no** case_id → listed as candidate")
lines.append("")
lines.append("## Vector-only PDFs (NOT true-text pilotable)")
for v in vector_pdfs:
    lines.append(f"- `{v['name']}` sha256=`{v['sha256']}` — font_resources empty; outline lettering")
lines.append("")
lines.append("## Per-PDF inventory (deep scan)")
lines.append("")

for rec in raw["pdfs"]:
    lines.append(f"### {rec['name']}")
    lines.append(f"- path: `{rec['path']}`")
    lines.append(f"- sha256: `{rec['sha256']}`")
    lines.append(
        f"- pages: {rec['page_count']} | text_class: **{rec['text_class']}** | approx_shows: {rec['approx_show_count_total']}"
    )
    if rec.get("error"):
        lines.append(f"- error: `{rec['error']}`")
    shows = rec.get("fonts_from_shows") or {}
    if not shows and rec["text_class"] == "vector_outline":
        lines.append("- fonts_from_shows: _(none — vector outline)_")
        lines.append("")
        continue
    if not shows:
        lines.append("- fonts_from_shows: _(none extractable)_")
        cat = rec.get("font_catalog") or []
        if cat:
            lines.append("- font_catalog only:")
            for c in cat[:20]:
                lines.append(
                    f"  - {c.get('clean_name') or c.get('BaseFont')} sub={c.get('Subtype')} enc={c.get('Encoding')} class={c.get('class')}"
                )
        lines.append("")
        continue
    lines.append("")
    lines.append("| BaseFont (clean) | Subtype | Encoding | emb | TU | shows | class | sample |")
    lines.append("|---|---|---|---|---|---:|---|---|")
    for name, f in sorted(shows.items(), key=lambda x: -x[1].get("approx_show_count", 0)):
        samples = "; ".join((f.get("sample_decoded_strings") or [])[:2]).replace("|", "/")
        if len(samples) > 60:
            samples = samples[:57] + "..."
        lines.append(
            f"| {name} | {f.get('Subtype')} | {f.get('Encoding')} | {f.get('embedded')} | {f.get('ToUnicode')} | {f.get('approx_show_count')} | {f.get('class')} | {samples} |"
        )
    lines.append("")

lines.append("## veraPDF light unique fonts (names only)")
lines.append(
    f"Scanned {raw['verapdf_light']['scanned']} / {raw['verapdf_light']['corpus_pdf_count']}; unique BaseFonts: {len(raw['verapdf_light']['unique_fonts'])}"
)
lines.append("")
lines.append("Specialty/nondefault names seen in corpus sample (truncated):")
spec = [
    u
    for u in raw["verapdf_light"]["unique_fonts"]
    if str(u.get("class", "")).startswith(("nondefault", "specialty", "other"))
]
for u in spec[:40]:
    lines.append(f"- `{u['BaseFont']}` ({u.get('class')}) ex: `{u.get('example')}`")
if len(spec) > 40:
    lines.append(f"- … +{len(spec) - 40} more in raw_inventory.json")
lines.append("")
lines.append("## Cross-check: documented cases")
lines.append(
    "- `scripts/experiment_hvac_font_edits.py` CASES 1–10 → HVAC PMingLiU/Arial/JhengHei (see `output/pdf/manual-font-study/results.json`)"
)
lines.append(
    "- `scripts/experiment_cad_font_edits.py` TEXT_CASES seq 31/38/57/60 → ECC DFKaiShu only"
)
lines.append("- CHB/[AIRPORT_CODE] VECTOR_CASES only")
lines.append(
    "- No FangSong / SimSun / Trebuchet / YaHei / Aptos / Europa case_ids found in docs/scripts/results"
)
lines.append("")
lines.append("Raw dumps: `raw_inventory.json`, `FINGERPRINTS.json`, `NONDEFAULT_CANDIDATES.json`")

(OUT / "FONT_INVENTORY_FULL.md").write_text("\n".join(lines), encoding="utf-8")

parent = {
    "stamp": STAMP,
    "timezone_label": "Asia/Taipei (UTC+8)",
    "mode": "search_only",
    "pdf_mutations": 0,
    "product_source_changes": 0,
    "case_ids_invented": 0,
    "pdfs_deep_scanned": len(raw["pdfs"]),
    "verapdf_corpus_total": raw["verapdf_light"]["corpus_pdf_count"],
    "verapdf_light_scanned": raw["verapdf_light"]["scanned"],
    "true_text_pdfs": sum(1 for r in raw["pdfs"] if r["text_class"] == "true_text"),
    "vector_outline_pdfs": sum(1 for r in raw["pdfs"] if r["text_class"] == "vector_outline"),
    "new_nondefault_fonts_beyond_known": [
        "SimSun",
        "TrebuchetMS",
        "MicrosoftYaHei-Bold",
        "MicrosoftJhengHeiBold",
        "Europa/Canela/IvyPresto/ACaslonPro (Awareness Type1)",
        "Consolas / IBMPlexMono / Type3-CJK (test-complexed-layout)",
        "MS-Gothic",
        "Aptos (incl. vertical fixture)",
        'custom BaseFont "1" / "2,Bold" (test-colored-background)',
        "SymbolMT",
        "RobotoMono",
        "ArialUnicodeMS",
        "NSimSun / KozMinPro / AdobeGothic (veraPDF corpus names)",
    ],
    "top_pilot_candidates": [
        {
            "rank": c["rank"],
            "font_name": c["font_name"],
            "source_pdf": c["source_pdf"],
            "sha256": c["sha256"],
            "page_index": c.get("page_index"),
            "seq_samples": c.get("seq_samples"),
            "sample_original_text": c.get("sample_original_text"),
            "text_class": c["text_class"],
            "has_explicit_case_id": False,
            "suggested_primary_variable": c["suggested_primary_variable"],
            "risk_notes": c["risk_notes"],
        }
        for c in candidates[:5]
    ],
    "gaps": gaps,
    "vector_only": [v["name"] for v in vector_pdfs],
    "evidence_path_user": str(OUT),
    "evidence_path_workspace_mirror": f"/workspace/pdf_editor_evidence/{STAMP}_font_search",
    "accepted_for_code": False,
    "claude_handoff": False,
}
(OUT / "PARENT_SUMMARY.json").write_text(json.dumps(parent, ensure_ascii=False, indent=2), encoding="utf-8")

readme = f"""# {STAMP}_font_search — SEARCH ONLY

This package is an **inventory + candidate list** for future true-text font pilots.

## What this is
- Local PDF font inventory under `test_files/`
- Ranked NON-DEFAULT / specialty font candidates with fingerprints
- Cross-check against existing TEXT_CASES / results.json

## What this is NOT
- **No Claude handoff**
- **No accepted_for_code**
- **No PDF mutations** (originals untouched)
- **No product source changes**
- **No invented case_id** — undocumented faces are `candidate_discovered` with fingerprint fields only

## Files
- `FONT_INVENTORY_FULL.md` — all deep-scanned PDFs
- `NONDEFAULT_CANDIDATES.json` — ranked future pilots + gaps + vector-only
- `PARENT_SUMMARY.json` — compact report for parent agent
- `FINGERPRINTS.json` — page_index/seq/original_text samples via project shows()
- `raw_inventory.json` — machine dump
- `_run_font_inventory.py` — read-only scanner used this round

## Vector-only (not pilotable as true-text)
- [VECTOR_CHB_PDF]
- [AIRPORT_CODE] [AIRPORT_DWG_REV].pdf

Stamp: {STAMP} Asia/Taipei
"""
(OUT / "README.md").write_text(readme, encoding="utf-8")
print("Wrote package to", OUT)
for c in candidates[:5]:
    print(c["rank"], c["font_name"], c["sample_original_text"][:2])
