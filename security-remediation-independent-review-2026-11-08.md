# 安全修復獨立驗證紀錄

日期：2026-11-08

## 範圍與結論

本紀錄核對 `security-remediation-report-2026-11-07.md` 的已套用修復。檢查對象是基底提交 `6554db9cea672b505e07044cb33fb64b8cbd3f2c` 加上當時尚未提交的工作樹變更；本文件本身的提交不包含那些程式修復，也不能用來重建受測工作樹。

**不能認定報告所列項目都已完全修好。** 多數修復有目前程式及針對性測試支持；F16 的「無法可靠分類時安全拒絕」有具體反例。CF5、CF17 和 CF18 仍有下述限制，不能只憑通過的案例斷言所有情境安全。本次沒有修改修復程式。

## 逐項結果

| 項目 | 結果與證據 |
| --- | --- |
| F1 | 有修復證據。ToUnicode 區塊掃描及未結束區塊、長輸入與正常解析測試通過。 |
| F2 | 有修復證據。Windows Explorer 使用系統位置的絕對路徑；參數、路徑及缺檔測試通過。 |
| F3 | 有修復證據。最佳化影像處理停用 Pillow EPS 的 Ghostscript 路徑；特製輸入和正常影像處理測試通過。 |
| F7 | 有修復證據。密碼欄位預設遮蔽，並可切換顯示；相關測試通過。 |
| F8 | 有修復證據。加密來源的最佳化中間結果使用記憶體，未寫明文中間檔的測試通過；大型檔案的記憶體用量仍是取捨。 |
| F11 | 有修復證據。RC4 來源輸出提升至 AES-256，使用者／擁有者認證及有效權限測試通過；其他 owner 密碼和權限政策仍待評估。 |
| F12 | 有修復證據。FreeText 外觀字串長輸入、倍增時間與正常解析測試通過。 |
| F14 | 有修復證據。字型名稱進入 CSS 前經 `css_font_family` 處理；偽造名稱與正常字型測試通過。 |
| F16 | **尚不能確認完整修復。** 間接和繼承簽章欄位的既有測試通過，但異常 `/Parent` 父鏈存在下述分類缺口。 |
| F24 | 有修復證據。ToUnicode 查找已索引，結果一致性和大量記錄查找測試通過；這不保證所有極端字型均無延遲。 |
| CF8 | 有修復證據。間接參照掃描的數字邊界及長數字測試通過。 |
| CF9 | 有修復證據。數字辨識調整後，既有語意與長輸入測試通過。 |
| CF11 | 有修復證據。縮圖寬高限制、極端窄長頁及正常頁面測試通過；此結論不延伸到其他整頁渲染。 |
| CF6 | 有修復證據。文件控制的對話框文字經安全處理；惡意名稱及正常文字測試通過。 |
| CF5 | **有範圍限制。** 便利貼刪除與重新編號後參照測試通過。簽章舊修訂保留舊位元組；`test_scripts/test_deleted_annotation_not_in_saved_bytes.py` 的 `test_delete_succeeds_when_the_nulling_step_fails` 亦明確接受清除失敗時刪除仍成功、文字可能被追加。 |
| CF17 | **尚不能涵蓋所有異常文件。** 無簽章文件的替換內容清除及正常存檔測試通過，但存檔策略依賴簽章分類，F16 缺口的後果尚待驗證。 |
| CF18 | **整合效果尚不能完全確認。** 兩階段封裝、加密及封裝失敗時的物件編號通知測試通過；本次未重新量測大型語料，也未重跑完整套件。 |

「有修復證據」指上述具體路徑及測試案例得到支持，不表示已證明不存在其他漏洞或副作用。

## F16 反例與限制

`model/text_commit/inspect.py` 的 `_field_ancestors` 遇到循環或超出 xref 範圍的父參照時直接結束走訪。以記憶體建立 PDF、序列化後重新開啟，再呼叫 `document_has_a_signed_signature(doc, require_known=True)`，得到：

| `/Parent` 狀態 | 觀察結果 |
| --- | --- |
| 指向不存在的 `9999 0 R` | `False`，未拋出 `SignatureStateUnknown` |
| 兩個欄位形成循環 | `False`，未拋出 `SignatureStateUnknown` |

這證實這些異常形狀不會一律安全拒絕；測試中的欄位沒有實際簽章值，**尚未證明有效簽章被誤判或受到損害**。後續需先確認政策是否應將這些損壞形狀視為未知，並以最小樣本測試存檔、便利貼刪除、簽章狀態與正常無簽章文件相容性。

## 驗證方式與限制

以專案 `.venv` 的 Python、Qt offscreen、停用 bytecode 與 pytest cache，於同一個 pytest 程序執行下列 20 個測試檔，結果 **941 passed in 9.92s**：

`test_tounicode_block_scan.py`、`test_tounicode_map_index.py`、`test_file_reveal.py`、`test_security_optimizer_ghostscript.py`、`test_optimizer_encrypted_intermediate.py`、`test_optimizer_encryption_floor.py`、`test_freetext_da_parse.py`、`test_font_family_markup_inert.py`、`test_signature_unknown_save.py`、`test_signed_signature_field_type.py`、`test_pdf_lexer_number_linear.py`、`test_reference_scan_linear.py`、`test_thumbnail_render_scale_bounds.py`、`test_message_text_plain.py`、`test_deleted_annotation_not_in_saved_bytes.py`、`test_note_xrefs_survive_renumbering_save.py`、`test_unsigned_save_drops_replaced_content.py`、`test_full_save_object_streams.py`、`test_packed_save_failure_epoch.py`、`test_dialogs_package.py`；均位於 `test_scripts/`。

本次未重跑原報告的 10,900 項完整套件、實體桌面中文介面或大型語料，也沒有檢查所有可能的 PDF。既有 F4、F13、F15、F25 與 OCR 權重限制仍以原報告列示為準；本紀錄不是完整安全稽核。
