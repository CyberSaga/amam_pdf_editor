# Suggested product-layer changes (cand-hvac-trebuchet-m5)

- Primary variable: latin_specialty_trebuchet_cid (font face/family vs prior PMingLiU/Arial/ECC-Kai).
- Font under test: TrebuchetMS.
- Lineage: candidate_discovered from 20260924_1908_font_search; has_explicit_case_id=false.
- Keep fail-closed; do not weaken prepare gates globally from this experiment splice.
- Experiment splice success is NOT product acceptance while prepare still rejects / UI unverified.
