# case-7 UI flow notes

- expected_signature: `verification_failed`
- ui_preview: `pass` reason=`None`
- ui_apply: `blocked` engine_reason=`verification_failed` result=`EditTextResult.REJECTED_STRICT`
- ui_undo/redo: `skipped` / `skipped`
- direct_prepare_context: `{'prepared': False, 'reason': 'verification_failed', 'detail': 'candidate failed to apply on scratch: page fingerprint changed since the plan was prepared'}`
- overall: `ui_blocked` accepted_for_code=False

Drive path: offscreen PDFView/PDFController (same as GUI signals).