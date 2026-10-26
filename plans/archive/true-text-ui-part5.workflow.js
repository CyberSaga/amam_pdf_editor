export const meta = {
  name: 'true-text-ui-part5',
  description: 'True-text UI part 5: owner decisions, pending-maintenance blocker, save guard, small defects, review, visual acceptance, docs',
  whenToUse: 'Only after the owner says 開始 for part 5; see plans/true-text-ui-part5.md',
  phases: [
    { title: 'Analyze', detail: 'Stage 0 read-only design (deep-reasoner)' },
    { title: 'Stage A', detail: 'IME, F5, Ctrl+S, legacy consent (Sonnet, red-first)' },
    { title: 'Stage B', detail: 'pending_page_maintenance blocker (Sonnet)' },
    { title: 'Stage C', detail: 'step 13 save guard, save/save_as UI, undo after renumber (Sonnet)' },
    { title: 'Stage D', detail: 'defects 4-7 (Sonnet spec, Haiku mechanical)' },
    { title: 'Review', detail: 'plan-code-reviewer + adversarial probes (Opus)' },
    { title: 'Stage E', detail: 'step 15 visual acceptance crops (Sonnet renders, Opus inspects)' },
    { title: 'Stage F', detail: 'step 16 docs (Haiku PITFALLS, Sonnet ARCHITECTURE, Opus final review)' },
  ],
}

// ---------------------------------------------------------------- args
// args is passed verbatim as a JSON value (never a string). Assert its shape
// first: a stringified args object is the known failure mode.
const A = typeof args === 'string' ? JSON.parse(args) : args
if (typeof A !== 'object' || A === null) throw new Error('args must be an object: {stage, authorization?, decisions?}')
const STAGE = A.stage
if (!['analyze', 'implement', 'finish'].includes(STAGE)) throw new Error('args.stage must be analyze | implement | finish')
const AUTH = typeof A.authorization === 'string' ? A.authorization.trim() : ''
if (STAGE !== 'analyze' && !AUTH) throw new Error('args.authorization must hold the owner\'s verbatim start sentence for implement/finish')
const DEC = A.decisions || {}
if (STAGE === 'implement' && !(DEC.q1 && DEC.q2 && DEC.q3 && DEC.q4)) throw new Error('args.decisions needs q1..q4 (owner answers, verbatim)')

// ---------------------------------------------------------------- shared text
const PLAN = 'plans/true-text-ui-part5.md'
const MOTHER = 'plans/Integrate_proven_PDF_editing_methods_into_the_official_editor.md'
const PLAN_AUTH = 'plan how to build part 5 to fulfill goal: cover every edge cases; orchestrate opus, sonnet, haiku in advance'

const RULES = `RULES (hard; violating any one means the stage is rejected):
- Never run taskkill / pkill / Stop-Process or kill any process. One pytest at a time, always \`.venv\\Scripts\\python.exe -m pytest ... -v -o faulthandler_timeout=300\` with output redirected to a file, never bare pytest.
- Owner rule 2026-10-06 (verbatim): 「子 agent 一律用 -v -o faulthandler_timeout=300 跑測試，並把輸出寫進檔案。若確認是真的卡住，授權 10 分鐘後用 TaskStop 停掉它」. You may TaskStop only a pytest task YOU started that is confirmed hung (output file not growing and ~0 CPU for 10+ minutes); then report the hung node id and rerun the rest in smaller chunks.
- Test only on COPIES of PDFs (tmp_path); never modify test_files/ or _evidence_pilot/ originals.
- Red first: write the test, run it, paste the failing output into ${MOTHER} section 6, then implement and paste the green run.
- Do not edit docs/PITFALLS.md, docs/ARCHITECTURE.md or TODOS.md (that is Stage F only).
- No git commit / push / PR. No machine-specific paths or hostnames in any tracked file.
- Dispatch sub-agents one at a time if you use any; no parallel bursts.
- Read ${PLAN} first (small); grep the mother plan ${MOTHER} by heading instead of bulk-reading it.
- Every shell that runs test_scripts/test_text_commit_ui_real_corpus.py must first set the env var PDF_EDITOR_PDFTOPPM=${A.pdftoppm ? JSON.stringify(A.pdftoppm) : '(not provided: report second_renderer as environment-blocked, not as a product failure)'} (this machine's PATH does not have it). Never write that path into any file. The full umbrella module takes several minutes: give the command a 600000 ms timeout or run it in the background and wait; a timeout is not a failure.
- Known environment-only failures on this machine, NOT caused by your stage: test_scripts/test_security_packaging.py (the venv has no setuptools). Do not fix or chase it.
Owner authorization (verbatim, planning): "${PLAN_AUTH}"
${AUTH ? `Owner authorization (verbatim, implementation): "${AUTH}"` : 'Implementation NOT yet authorized: this run is read-only analysis.'}
`

const DONE_GATE = `Stage done-gate (report each with the exact command and the summary line):
- \`ruff check .\` clean; \`.venv\\Scripts\\python.exe -m mypy model/ utils/\` clean; \`lint-imports\` 4 kept 0 broken.
- Umbrella under shipped defaults: \`.venv\\Scripts\\python.exe -m pytest test_scripts/test_text_commit_ui_real_corpus.py\` (112/112 phases; the IME offscreen red is expected ONLY until Stage A1 lands).
- The red run and the green run of every new test are pasted into ${MOTHER} section 6 under a dated heading for this stage.
- List every file changed, every test added, and anything you found but did NOT fix (with file:line).`

const STAGE_REPORT = {
  type: 'object',
  properties: {
    status: { type: 'string', enum: ['done', 'blocked', 'partial'] },
    red_tests: { type: 'array', items: { type: 'string' } },
    green_tests: { type: 'array', items: { type: 'string' } },
    files_changed: { type: 'array', items: { type: 'string' } },
    gate: { type: 'object', properties: { ruff: { type: 'string' }, mypy: { type: 'string' }, lint_imports: { type: 'string' }, umbrella: { type: 'string' } } },
    found_not_fixed: { type: 'array', items: { type: 'string' } },
    notes: { type: 'string' },
    // Stage D part 1 only: the mechanical edit list handed to fast-worker.
    spec: { type: 'array', items: { type: 'object', properties: { file: { type: 'string' }, line: { type: 'integer' }, edit: { type: 'string' } }, required: ['file', 'line', 'edit'] } },
  },
  required: ['status', 'red_tests', 'green_tests', 'files_changed', 'found_not_fixed', 'notes'],
}
const SPEC_REPORT = { ...STAGE_REPORT, required: [...STAGE_REPORT.required, 'spec'] }

const DESIGN_REPORT = {
  type: 'object',
  properties: {
    defect1_options: { type: 'array', items: { type: 'object', properties: { name: { type: 'string' }, mechanism: { type: 'string' }, risks: { type: 'string' }, evidence: { type: 'string' } }, required: ['name', 'mechanism', 'risks', 'evidence'] } },
    defect1_recommendation: { type: 'string' },
    ime_logic_design: { type: 'string' },
    ime_display_hypothesis: { type: 'string' },
    fullscreen_vs_zoom_with_token: { type: 'string' },
    edge_matrix: { type: 'array', items: { type: 'object', properties: { path: { type: 'string' }, input_state: { type: 'string' }, expected: { type: 'string' }, covered_by: { type: 'string' }, gap: { type: 'boolean' } }, required: ['path', 'input_state', 'expected', 'gap'] } },
    defect12_classification: { type: 'string' },
    unverified: { type: 'array', items: { type: 'string' } },
  },
  required: ['defect1_options', 'defect1_recommendation', 'ime_logic_design', 'ime_display_hypothesis', 'fullscreen_vs_zoom_with_token', 'edge_matrix', 'defect12_classification', 'unverified'],
}

const REVIEW_REPORT = {
  type: 'object',
  properties: {
    verdict: { type: 'string', enum: ['ship', 'ship-with-fixes', 'do-not-ship'] },
    blocking: { type: 'array', items: { type: 'string' } },
    non_blocking: { type: 'array', items: { type: 'string' } },
    plan_conformance: { type: 'array', items: { type: 'string' } },
    unverified: { type: 'array', items: { type: 'string' } },
  },
  required: ['verdict', 'blocking', 'non_blocking', 'plan_conformance', 'unverified'],
}

// Serial by design (CLAUDE.md: one sub-agent at a time). Each stage awaits the previous one.
const results = {}

// ---------------------------------------------------------------- analyze
if (STAGE === 'analyze') {
  phase('Analyze')
  results.design = await agent(`${RULES}
You are read-only. Produce the Stage 0 design report described in ${PLAN} section 5 "Stage 0".
Ground every claim in file:line. Facts already established (verify, do not re-derive):
- Gate reads model.pending_edits at model/pdf_text_edit.py:1802 and :1893; preview freezes the flag at session open (model/text_commit/preview.py:54, :298);
  model/pdf_model.py:3701 _maybe_garbage_collect clears only on save or edit_count % 5; docs/ARCHITECTURE.md:1006 states why the gate exists.
- F5: controller/pdf_controller.py:1247 enter_fullscreen runs _cancel_search, snapshot, set_mode("browse") BEFORE view.cancel_interaction_for_fullscreen (view/pdf_view.py:1073) fires MODE_SWITCH.
- Finalize policy sets: view/text_editing.py:231-262; has_unapplied_input at :2536; InlineTextEditor at :340 has no inputMethodEvent; grep of view/ for WA_InputMethodEnabled|ItemAcceptsInputMethod|inputMethodQuery is empty.
- Legacy consent exemption: controller/pdf_controller.py:3015 (the only site).
Deliver: for defect 1 at least two concrete options with mechanism, risks (especially whether page-local clean_contents changes Tier 0 splice/fingerprint behaviour on the 14 fixtures and Office BDC/EMC structure) and a recommendation;
the IME logic design (offscreen-testable) and the display defect: discriminate between hypothesis A (preedit events never reach the proxy-embedded QTextEdit; note QTextEdit sets WA_InputMethodEnabled itself and QGraphicsProxyWidget sets ItemAcceptsInputMethod on setWidget, so the empty grep is weak evidence) and hypothesis B (the editor is PreviewBackedInlineTextEditor at view/text_editing.py:854 and the plan preview / overlay is built from toPlainText(), which excludes the preedit, so the composed text is never drawn) — the fixes differ completely; what zoom actually does with a valid token (so F5 can match it);
the edge matrix (finalize reason x input state {empty, unverified, refused, token, preedit} with the covering test or gap=true); and a classification of defect 12 (test-complexed-layout no_source_match) WITHOUT inventing a case_id.`,
    { label: 'stage0:design', phase: 'Analyze', agentType: 'deep-reasoner', schema: DESIGN_REPORT })

  // Second independent leg (the owner waived Codex for now): risk-first lens, never shown the first result.
  results.design_risk = await agent(`${RULES}
You are read-only and you are an INDEPENDENT second analyst; another analyst works on the same question and you will not see their answer.
Produce the Stage 0 design report described in ${PLAN} section 5 "Stage 0" with a RISK-FIRST lens. Ground every claim in file:line.
Starting points (verify each, do not trust): model/pdf_text_edit.py:1802 and :1893 read model.pending_edits; model/text_commit/preview.py:54 and :298 freeze the flag at session open; model/pdf_model.py:3701 _maybe_garbage_collect; docs/ARCHITECTURE.md:1006; controller/pdf_controller.py:1247 enter_fullscreen and :3015 legacy consent exemption; view/pdf_view.py:1073; view/text_editing.py:231-262, :340, :854, :2536.
Defect 1: enumerate the options yourself. For EACH option, state concretely what changes for the 14 real fixtures' Tier 0 splice and content-stream fingerprint (byte identity of the stream the engine fingerprints), what happens to Office BDC/EMC marked-content structure, what happens to undo/redo snapshots, and whether a save is still needed. Recommend the option with the smallest blast radius and say what test would prove it safe.
IME: discriminate hypothesis A (preedit never reaches the proxy-embedded QTextEdit; note QTextEdit sets WA_InputMethodEnabled itself and QGraphicsProxyWidget sets ItemAcceptsInputMethod on setWidget, so an empty grep is weak evidence) from hypothesis B (PreviewBackedInlineTextEditor at view/text_editing.py:854 and the plan preview/overlay are built from toPlainText(), which excludes preedit). Say which is offscreen-testable with QInputMethodEvent and which is not.
F5 vs zoom with a valid token: read the zoom/rescale tests in test_scripts/test_text_commit_finalize_policy.py and quote the assertion that pins zoom behaviour.
Edge matrix: every finalize reason x input state {empty, unverified, refused, token, preedit}, covering test or gap=true. Defect 12 (test-complexed-layout no_source_match): classify WITHOUT inventing a case_id.`,
    { label: 'stage0:design-risk', phase: 'Analyze', agentType: 'deep-reasoner', schema: DESIGN_REPORT })
  return results
}

// ---------------------------------------------------------------- implement
if (STAGE === 'implement') {
  const decisions = `Owner decisions (verbatim, from the Stage 0 Q&A):
- Q1 Ctrl+S semantics: ${DEC.q1}
- Q2 legacy exemption scope: ${DEC.q2}
- Q3 defect 1 fix: ${DEC.q3}
- Q4 F5 with a valid token: ${DEC.q4}`
  // Stage 0 synthesis (main loop merges the two deep-reasoner reports and passes the result here).
  const DES = A.design || {}
  const design = `Stage 0 design (synthesized from two independent Opus analyses; treat as the spec, verify file:line before editing):
- IME logic design: ${DES.ime_logic || '(none)'}
- IME display: ${DES.ime_display || '(none)'}
- F5 vs zoom with a valid token: ${DES.fullscreen || '(none)'}
- Edge-matrix GAPS (each one MUST get a red test in the stage that owns it, or be reported in found_not_fixed with the reason): ${JSON.stringify(DES.gaps || [])}`

  phase('Stage A')
  results.a = await agent(`${RULES}
${decisions}
${design}
Implement Stage A from ${PLAN} section 5 (A1 IME logic, A2 F5, A3 Ctrl+S + defect 3 wording, A4 legacy consent), red-first, in that order.
A1: if the IME display cause above is offscreen-testable (e.g. the overlay/preview text excludes the preedit), it is part of A1: drive it with QInputMethodEvent red-first; only a cause that truly needs a real IME goes to the owner's Stage E check.
A1: keep test_scripts/test_text_commit_ui_real_corpus.py::test_ui_apply_during_an_ime_preedit_never_commits_the_text_without_it as the gate; add the preedit cases listed in the plan to test_scripts/test_text_commit_finalize_policy.py (reuse its launch fixture).
A2: add a new TextEditFinalizeReason in _KEEP_EDITOR_REASONS; make finalize the FIRST statement of controller.enter_fullscreen and return on REFUSED; re-run test_scripts/test_multi_tab_plan.py in full afterwards.
A3: test _save and _save_as separately for token / refused / preview-in-flight; notice text must match the editor's real state.
A4: remove the engine=="legacy" exemption at controller/pdf_controller.py:3015 per Q2; assert zero model calls on refusal.
${DONE_GATE}`, { label: 'stageA:decisions', phase: 'Stage A', model: 'sonnet', schema: STAGE_REPORT })
  if (!results.a || results.a.status === 'blocked') return results

  phase('Stage B')
  results.b = await agent(`${RULES}
${decisions}
${design}
Implement Stage B from ${PLAN} section 5 exactly as Q3 decides, red-first. Red tests: add-textbox then true-text edit on the same page -> COMMITTED; accepted rebuild then another line -> COMMITTED; undo the add then edit -> COMMITTED; an editor already open when the flag clears obtains a token.
Add one umbrella phase "add-or-rebuild then edit same page" over all 14 cases in test_scripts/test_text_commit_ui_real_corpus.py and run the whole module under shipped defaults.
If the wording 頁面仍在整理中，請稍後再試 survives anywhere, it must become true (say what actually clears it).
${DONE_GATE}`, { label: 'stageB:blocker', phase: 'Stage B', model: 'sonnet', schema: STAGE_REPORT })
  if (!results.b || results.b.status === 'blocked') return results

  phase('Stage C')
  results.c = await agent(`${RULES}
${decisions}
${design}
Implement Stage C (step 13) from ${PLAN} section 5, red-first: protected-page guard in model/tools/manager.py:132 and model/tools/watermark_tool.py:110 prepare_doc_for_save (extend test_scripts/test_text_commit_maintenance.py, do not duplicate its 5 tests);
UI save (incremental) and save_as (full) each with semantic reopen compare; undo after a full save renumbers xrefs (Tier 0 reversal keyed by page, not xref).
${DONE_GATE}`, { label: 'stageC:step13', phase: 'Stage C', model: 'sonnet', schema: STAGE_REPORT })
  if (!results.c || results.c.status === 'blocked') return results

  phase('Stage D')
  results.d_spec = await agent(`${RULES}
${design}
Stage D part 1 (Sonnet): also pick up any edge-matrix gap above that Stages A-C reported as not covered (see their found_not_fixed: ${JSON.stringify([results.a, results.b, results.c].map(r => r && r.found_not_fixed))}). Write the RED tests and a fully mechanical spec for defects 7 (sig_add_textbox size int->float, test with 10.5), 5 (Ctrl+wheel duplicate toast: same reason+text shown once while the editor is kept) and 6 (consent dialog and degrade toast must route tier0:... codes through view/text_edit_reasons.py).
Run the reds, paste them into ${MOTHER} section 6. Return the spec in the structured \`spec\` field as an exact list of {file, line, edit} a mechanical worker can apply without decisions. Do NOT implement.
${DONE_GATE}`, { label: 'stageD:spec', phase: 'Stage D', model: 'sonnet', schema: SPEC_REPORT })
  if (!results.d_spec || results.d_spec.status === 'blocked') return results
  results.d_impl = await agent(`${RULES}
Stage D part 2 (mechanical): apply EXACTLY this spec, then run the red tests named below until green and ruff check the touched files. Stop and report if anything in the spec is ambiguous.
RED TESTS: ${JSON.stringify(results.d_spec.red_tests)}
SPEC:
${JSON.stringify(results.d_spec.spec, null, 2)}`, { label: 'stageD:impl', phase: 'Stage D', agentType: 'fast-worker', schema: STAGE_REPORT })

  phase('Review')
  results.review = await agent(`${RULES}
Review the whole uncommitted diff against ${PLAN} section 1 (completion criteria) and the Stage reports below. Run /code-review high. Then run adversarial probes under SHIPPED defaults (no TEXT_COMMIT_* env), real QTest input, spying _apply_redact_insert, add_textbox, the consent dialog and the CSS renderer — the part-4 method recorded in ${MOTHER} under "2026-10-02 VERIFY part 4".
Classify each finding blocking / non-blocking with file:line and a reproduction. One sub-agent at a time if you delegate.
Stage reports: ${JSON.stringify({ a: results.a, b: results.b, c: results.c, d: results.d_impl })}`,
    { label: 'review:V1', phase: 'Review', agentType: 'plan-code-reviewer', schema: REVIEW_REPORT })
  return results
}

// ---------------------------------------------------------------- finish
if (STAGE === 'finish') {
  phase('Stage E')
  results.crops = await agent(`${RULES}
Stage E (step 15): on COPIES, for each of the 14 cases (ids from _evidence_pilot and test_scripts/test_text_commit_ui_real_corpus.py; never invent one) render 6x crops of the target region before and after the UI edit, plus a 2x full-page diff outside the target (must be 0), with MuPDF and with Poppler via PDF_EDITOR_PDFTOPPM.
Write images and a table (case, crop paths, non-target diff, Poppler status) into the session scratchpad; return the table as text with relative file names only.
Do not change product code or tests.`, { label: 'stageE:crops', phase: 'Stage E', model: 'sonnet' })

  results.visual = await agent(`${RULES}
Inspect the crops listed below with Read (image files) and compare each with the matching _evidence_pilot output. Report per case: font identical / position identical / non-target diff 0 — or the exact visible difference. Mark anything you could not open as unverified.
${results.crops}`, { label: 'stageE:inspect', phase: 'Stage E', agentType: 'deep-reasoner' })

  phase('Stage F')
  const STAGE_F_RULES = RULES.replace('Do not edit docs/PITFALLS.md, docs/ARCHITECTURE.md or TODOS.md (that is Stage F only).', 'This IS Stage F: docs edits are in scope.')
  // The 35 candidates in the mother plan are compressed one-liners; expanding each into
  // Area/Symptom/Cause/Fix/File is judgment (Sonnet). Inserting the drafted text is mechanical (Haiku).
  results.pitfall_draft = await agent(`${STAGE_F_RULES}
Draft, do not insert: expand the 35 pitfall candidates listed in ${MOTHER} under "步驟 16 的 pitfall 候選彙整", plus these part-5 candidates: ${JSON.stringify(A.extra_pitfalls || [])}, into full entries in docs/PITFALLS.md's existing format (Area / Symptom / Cause / Fix / File), one per candidate, grounded in the code (file:line). Return the entries as text ready to paste, plus the heading under which each belongs. Do not edit any file.`,
    { label: 'stageF:pitfall-draft', phase: 'Stage F', model: 'sonnet' })
  results.pitfalls = await agent(`${STAGE_F_RULES}
Mechanical: insert the entries below into docs/PITFALLS.md under the headings they name, verbatim, then run \`python scripts/build_pitfalls_index.py\` and \`python .codegraph/indexer.py\`. Report the entry titles added. Do not rewrite or reorder anything else.
ENTRIES:
${results.pitfall_draft}`,
    { label: 'stageF:pitfalls', phase: 'Stage F', agentType: 'fast-worker' })

  results.docs = await agent(`${RULES.replace('Do not edit docs/PITFALLS.md, docs/ARCHITECTURE.md or TODOS.md (that is Stage F only).', 'This IS Stage F: docs edits are in scope.')}
Update docs/ARCHITECTURE.md (7-arg sig_add_textbox, the three finalize reason sets, _plan_preview_applies chokepoint, shipped defaults, the new fullscreen reason and IME preedit handling), docs/FEATURES.md:65, docs/架構.txt:117 and TODOS.md to match the code.
Part-5 doc obligations from the V1 review and fix-ups (each must land or be reported as not done): ${JSON.stringify(A.extra_docs || [])}
TODOS.md items to add (pre-existing defects found in part 5, not fixed; each with file:line and a one-line repro): ${JSON.stringify(A.extra_todos || [])}
Then run the full suite in batches (one pytest at a time) and report totals. Append the Stage E/F log to ${MOTHER} section 6 and ${PLAN} section 10.`,
    { label: 'stageF:docs', phase: 'Stage F', model: 'sonnet', schema: STAGE_REPORT })

  results.final = await agent(`${RULES}
Final review: judge the whole diff against ${PLAN} section 1 completion criteria 1-7 and report verdict, outstanding obligations (including the owner's real-IME acceptance, which no offscreen test can replace), and anything claimed-but-absent.`,
    { label: 'final:review', phase: 'Stage F', agentType: 'plan-code-reviewer', schema: REVIEW_REPORT })
  return results
}
