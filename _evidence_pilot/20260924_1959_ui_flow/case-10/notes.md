# case-10 UI flow notes

- expected_signature: `trm_reflected`
- ui_preview: `blocked` reason=`no_source_match`
- ui_apply: `blocked` engine_reason=`no_source_match` result=`EditTextResult.REJECTED_STRICT`
- ui_undo/redo: `skipped` / `skipped`
- direct_prepare_context: `{'prepared': False, 'reason': 'trm_reflected', 'detail': 'combined text/transform matrix has negative orientation (reflection)'}`
- overall: `ui_blocked` accepted_for_code=False

Drive path: offscreen PDFView/PDFController (same as GUI signals).