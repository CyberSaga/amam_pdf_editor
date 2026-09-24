# Pilot methods + evidence plan (written BEFORE edits)
Timezone note: package folder stamped 20260924_1453 Asia/Taipei (UTC+8).

## Source verification
- HVAC SHA-256: 9da93de982145c46af0d34a978b4bbaa1167f0937327dedb44ecad4d50fca0a2 (matches verified brief)
- ECC SHA-256: 0f75dd10ed77214c5cf159d40f909cd402231761886cb0ed3821368ac0ab1853 (not edited this batch)
- Isolated copy: candidates/HVAC-source-copy.pdf; originals untouched; product source untouched.

## Second trm_reflected search (mandatory)
Searched repo results/docs/evidence for explicit case_id with engine reason `trm_reflected`:
- `output/pdf/manual-font-study/results.json` edits: ONLY case 10
- `scripts/experiment_hvac_font_edits.py` CASES + docs/experiments/2026-09-21-hvac-font-edits.md: only case 10
- ECC cad-font-study results.json: no `trm_reflected`
- Prior inventory: "trm_reflected only" for HVAC case 10

**Result: no second explicit trm_reflected case_id exists. Do NOT invent one.**
Therefore:
- (a) status `blocked` / `insufficient_evidence` for "next trm_reflected sibling"
- (b) deepen case 10 with ONE new primary variable (shorter replacement; preserve Tm/det)

## Case selection (this batch)

| slot | case_id | signature | page_index | seq | primary variable (ONE; differs from prior sibling) |
|---|---|---|---:|---:|---|
| mc next | 2 | mc_malformed_pairing | 4 | 16 | CJK ideograph swap 圖→表 (title noun), vs case1 digit-only (1)→(4) on different seq |
| vf next | 8 | verification_failed | 5 | 58 | non-zero TJ advance compensation + A版→B版 CJK suffix, vs case7 date digit kern≈0 |
| trm deepen | 10 (deepen) | trm_reflected | 6 | 5 | shorter replacement "Buffer Tank"→"Tank Buf" while preserving negative-det Tm (vs prior same-length "Tank Buffer") |
| trm sibling | N/A | — | — | — | blocked/insufficient_evidence: no second explicit case_id |

## Per-case hypotheses (max 3) + falsification

### case_id=2 / mc_malformed_pairing
H1: Same MC wrapper reject on seq=16 despite different show/text → FALSIFY: prepare reason==mc_malformed_pairing with wrapper detail.
H2: Primary variable (圖→表) still encode_strict + glyph_gate clean on PMingLiU → FALSIFY: encode_strict returns CIDs; glyph_gate None.
H3: CID splice preserves font/Tm/neighbors; crop changes; outside halo 0 → FALSIFY: structure+render+save_reopen.

### case_id=8 / verification_failed
H1: Scratch fingerprint reject still fires on seq=58 → FALSIFY: prepare reason==verification_failed + fingerprint phrase.
H2: Advance delta requires TJ trailing compensation (kern≠0) for A版→B版 → FALSIFY: measure kern; expect |kern|>>0 (historical ≈-79).
H3: Splice+TJ compensate+saveIncr still no-jump despite engine reject → FALSIFY: structure+render+save_reopen.

### case_id=10 deepen / trm_reflected (NOT a new trm case_id)
H1: prepare still refuses trm_reflected for shorter replacement → FALSIFY: live reason unchanged.
H2: Negative det(Tm) preserved after shorter splice (no orientation flip) → FALSIFY: det_tm before==after (<0).
H3: Shorter replacement needs TJ compensation; structure/render/save_reopen still pass → FALSIFY: kern record + checks.

### next trm_reflected sibling
No explicit case_id in inventory/results → status blocked/insufficient_evidence (search evidence only).

## Proposed edit methods (ordered; unchanged)
M1: TieredCommitEngine prepare max_tier=1 probe — expect reject; record reason.
M2: replay + CID encode_strict + stream splice on isolated copy.
M3: TJ trailing compensation if advance delta — never scale glyphs to old bbox.

## Evidence plan
Per case: structure/object/render/save-reopen notes; failed methods; suggested product/regression; unproven limits; candidates PDFs only under candidates/.
Stop rule: 3 attempts / same signature without NEW evidence → blocked/insufficient_evidence.

## Acceptance gate
accepted_for_code only if ALL 7 brief criteria hold. This engine-only pilot expects none (UI unverified; prepare still rejects).