# Pilot methods + evidence plan (written BEFORE edits)
Timezone note: package folder stamped 20260924_1431 Asia/Taipei (UTC+8).

## Source verification
- HVAC SHA-256: 9da93de982145c46af0d34a978b4bbaa1167f0937327dedb44ecad4d50fca0a2 (matches brief)
- ECC SHA-256: 0f75dd10ed77214c5cf159d40f909cd402231761886cb0ed3821368ac0ab1853
  (brief omitted one hex digit after 159; actual computed hash recorded)
- Isolated copies under candidates/; originals untouched.

## Case selection (explicit case field in repo evidence)
Source of case numbers: scripts/experiment_hvac_font_edits.py CASES + output/pdf/manual-font-study/results.json field "case".
Docs: docs/experiments/2026-09-21-hvac-font-edits.md table numbering 1-10.

| signature | chosen case_id | why representative |
|---|---|---|
| mc_malformed_pairing | 1 | First of six HVAC page_index=4 rejects; PMingLiU Type0, digit-only change |
| verification_failed | 7 | First scratch fingerprint reject; MicrosoftJhengHeiRegular date digit |
| trm_reflected | 10 | Sole HVAC reflected-TRM reject; ArialMT mirrored Buffer Tank |

Out of true-text scope (classify only, not piloted): CHB + Taoyuan vector drawings.

## Per-case hypotheses (max 3) + falsification

### case_id=1 / mc_malformed_pairing
H1: Show sits inside BMC/EMC wrapper that is unclosed or crosses q/Q -> FALSIFY: dump wrapper stack/verdict for seq=11; expect mc:malformed_pairing.
H2: Same-page admissible shows prove gate is local not page-global -> FALSIFY: count admissible vs malformed shows on page_index=4.
H3: Historical lossless splice (CID replace + optional TJ compensate) preserves font/Tm/neighbors -> FALSIFY: structure + render halo + save/reopen on isolated copy; fail if arbitrary scale/font swap.

### case_id=7 / verification_failed
H1: prepare fails because scratch page fingerprint != live plan fingerprint -> FALSIFY: capture engine prepare reason/detail; expect fingerprint phrase.
H2: Drift is numeric spelling (float/int) not content change -> FALSIFY: compare fingerprint inputs live vs after tobytes/open if APIs expose them; else mark insufficient_evidence.
H3: Standalone splice+saveIncr still yields no-jump text on isolated copy despite engine reject -> FALSIFY: same checks as case 1.

### case_id=10 / trm_reflected
H1: Combined TRM has negative determinant (intentional mirror) -> FALSIFY: compute det(Tm) and record visual direction.
H2: TieredCommitEngine max_tier=1 refuses with trm_reflected before apply -> FALSIFY: prepare() reason code.
H3: Preserving original Tm via splice still passes render/save-reopen -> FALSIFY: structure+image+reopen; reject if Tm rewritten to positive orientation.

## Proposed edit methods (ordered)
M1: Engine-only prepare/commit probe (product path) — expect reject; records reproducible_engine.
M2: Replay+CID encode_strict + StreamReplacement splice on isolated copy (experiment path; NOT product code change).
M3: If M2 width changes, TJ trailing compensation K=(adv_new-adv_old)*1000/Tf — never scale glyphs to old bbox.

## Evidence plan
For each case after attempts:
- structure notes, object diffs, render-diff notes, save-reopen notes
- failed methods / unproven limits
- suggested product-layer changes + regression tests
Stop rule: after 3 attempts with no new evidence -> blocked/insufficient_evidence.

## Acceptance gate for accepted_for_code
Only if ALL seven criteria in the brief hold in THIS run. UI marked unverified for engine-only pilot.
