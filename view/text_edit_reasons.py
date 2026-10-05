"""Plain Traditional Chinese text for text-edit refusal reason codes.

UI critique step 10 (plan section 3: "預覽拒絕時顯示易懂原因，例如「原字型沒有
這個字」，並提供「改用重建文字…」").  One mapping serves both the inline
editor's refusal state (``view/text_editing.py``) and the Controller's
REJECTED notice, so the two can never say different things.

The codes are the engine's ``RejectReason`` strings plus the few the
Controller itself issues; they are repeated here as literals because the View
may not import ``model.text_commit`` (import-linter ``view-no-model``).  A test
pins that every engine code has text.  The text never contains document
content (P0-C privacy contract: codes in, fixed sentences out).
"""
from __future__ import annotations

MISSING_GLYPH_TEXT = "原字型沒有這個字"

_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        MISSING_GLYPH_TEXT,
        (
            "type0_unicode_unmapped",
            "type0_glyph_missing",
            "type0_gid_zero",
            "type0_gid_beyond_glyph_count",
            "type0_cid_out_of_map_range",
            "encoding_failed",
        ),
    ),
    (
        "原字型缺少這些字的字寬資料，無法確保排版不變",
        ("type0_width_unprovable", "font_widths_incomplete"),
    ),
    ("新文字的寬度和原文不同，原位修改會改變排版", ("advance_mismatch",)),
    ("鏡射文字只能改成寬度相同的內容", ("trm_reflected_advance_change",)),
    ("新文字比原文長，會蓋到旁邊的內容", ("growth_region_not_blank",)),
    ("新文字比原文長，會超出頁面範圍", ("growth_outside_page",)),
    ("變更字型或字級需要重建文字", ("style_override_present",)),
    ("移動文字位置需要重建文字", ("geometry_override_present",)),
    ("把文字移到其他頁面需要重建文字", ("cross_page_move_requires_rebuild",)),
    ("清空文字需要重建文字", ("empty_replacement",)),
    ("一次修改多段文字（段落）需要重建文字", ("multi_span_target",)),
    ("多行文字需要重建文字", ("multiline_replacement",)),
    ("內容沒有變更", ("no_change",)),
    (
        "找不到這段文字在 PDF 中的原始內容",
        (
            "target_unresolved",
            "no_source_match",
            "ambiguous_source_match",
            "evidence_mismatch",
            "target_reconstruction_unverified",
            "undecodable_target",
        ),
    ),
    (
        "原字型的格式不支援原位修改",
        (
            "font_type3",
            "font_unsupported_encoding",
            "font_custom_differences",
            "font_face_unavailable",
            "font_resource_not_proven",
            "type0_encoding_unsupported",
            "type0_descendant_unsupported",
            "type0_font_not_embedded",
            "type0_tounicode_missing",
            "type0_tounicode_unparseable",
            "type0_tounicode_multichar",
            "type0_tounicode_ambiguous",
            "type0_source_bytes_not_reproduced",
            "type0_cidtogid_unreadable",
        ),
    ),
    ("這段文字位於內嵌的圖形物件中，無法原位修改", ("target_in_form_xobject",)),
    (
        "這段文字所在的圖層結構不支援原位修改",
        (
            "mc_wrapper_not_pure_layer",
            "mc_layer_not_default_visible",
            "mc_malformed_pairing",
            "mc_splice_crosses_wrapper_boundary",
        ),
    ),
    (
        "這段文字經過旋轉、傾斜或縮放，不支援原位修改",
        (
            "trm_non_finite",
            "trm_singular",
            "trm_scale_below_floor",
            "trm_reflected",
            "trm_sheared",
            "trm_non_uniform_scale",
            "trm_rotation_not_quarter_turn",
        ),
    ),
    (
        "這段文字的排版方式不支援原位修改",
        (
            "unsupported_text_state",
            "untracked_advance",
            "unsupported_show_operator",
            "not_single_literal_tj",
            "tj_multi_item_array",
            "tj_leading_kern_unproven",
            "tj_kern_in_tier1_range",
            "stroke_bound_unproven",
            "stroke_bound_too_large",
        ),
    ),
    ("頁面內容無法正確解讀，無法原位修改", ("malformed_stream", "tj_item_relex_failed")),
    (
        "這段文字的內容和其他物件共用，無法安全地原位修改",
        ("shared_content_stream", "duplicate_source_painter"),
    ),
    ("頁面內容過大，無法安全地原位修改", ("content_stream_too_large_for_safe_replay",)),
    ("頁面的尺寸設定不支援原位修改", ("page_geometry_unsupported",)),
    ("修改後的檢查未通過，無法確保外觀不變", ("verification_failed",)),
    ("此頁含表單欄位或已簽章，不允許修改", ("signed_or_widget_target",)),
    ("頁面仍在整理中，請稍後再試", ("pending_page_maintenance",)),
    ("預覽已過期，請等待新的預覽", ("preview_stale", "stale_plan")),
    ("這個編輯框屬於另一份文件，未套用到目前的文件", ("document_session_mismatch",)),
    ("無法為這份文件建立預覽（可能已加密）", ("snapshot_unavailable",)),
    ("預覽產生失敗", ("preview_error",)),
)

_REASON_TEXT: dict[str, str] = {
    code: text for text, codes in _GROUPS for code in codes
}

#: Refusals the rebuild action cannot help with (or must not be offered for):
#: nothing to rebuild, another document, an out-of-date preview (wait for the
#: new one), a page the tiered engine hard-refuses, or one still being tidied.
_NOT_REBUILDABLE = frozenset(
    {
        "no_change",
        "document_session_mismatch",
        "preview_stale",
        "stale_plan",
        "signed_or_widget_target",
        "pending_page_maintenance",
    }
)

_GENERIC_TEXT = "無法以原字型保真修改這段文字（代碼：{code}）"


def rejection_reason_text(code: str | None) -> str:
    """Plain text for ``code``; ``""`` for no refusal; an unmapped code gets
    the generic sentence plus the code (never silent)."""
    if not code:
        return ""
    text = _REASON_TEXT.get(str(code))
    if text is not None:
        return text
    return _GENERIC_TEXT.format(code=code)


def rebuild_offered_for(code: str | None) -> bool:
    """Whether "改用重建文字…" may be offered for this refusal."""
    return bool(code) and str(code) not in _NOT_REBUILDABLE


def effective_rejection_reason(
    code: str | None,
    *,
    page_changed: bool,
    position_changed: bool,
    style_changed: bool,
    paragraph_mode: bool = False,
) -> str | None:
    """The refusal the user should see for the editor's current state.

    The plan gate checks ``no_change`` BEFORE the style/geometry overrides
    (order pinned by the structural-gate tests), so a preview of a restyled
    or dragged editor whose text is unchanged reports ``no_change``.  The
    commit side rewrites it the same way (S7); this is the View's twin.  A
    cross-page move is always a rebuild, whatever the preview said.  In
    paragraph mode the preview cannot resolve a multi-line target at all
    (``target_unresolved``); the cause the user can act on is the
    paragraph (the commit side refuses it as ``multi_span_target``).
    """
    if not code:
        return None
    code = str(code)
    if page_changed and code in ("no_change", "geometry_override_present"):
        return "cross_page_move_requires_rebuild"
    if paragraph_mode and code == "target_unresolved":
        return "multi_span_target"
    if code == "no_change":
        if position_changed:
            return "geometry_override_present"
        if style_changed:
            return "style_override_present"
        return None
    return code
