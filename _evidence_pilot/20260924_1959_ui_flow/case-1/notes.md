# case-1 UI flow notes

- expected_signature: `mc_malformed_pairing`
- ui_preview: `blocked` reason=`mc_malformed_pairing`
- ui_apply: `blocked` engine_reason=`mc_malformed_pairing` result=`EditTextResult.REJECTED_STRICT`
- ui_undo/redo: `skipped` / `skipped`
- direct_prepare_context: `{'prepared': False, 'reason': 'mc_malformed_pairing', 'detail': 'wrapper is unclosed or crosses a q/Q boundary'}`
- overall: `ui_blocked` accepted_for_code=False

Drive path: offscreen PDFView/PDFController (same as GUI signals).