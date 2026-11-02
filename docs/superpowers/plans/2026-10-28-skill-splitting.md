# Equipment Skill Splitting Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans. Follow the test-first tasks below.

**Goal:** Turn an existing recorded workflow into reviewed, reusable skill drafts at meaningful task boundaries.

**Architecture:** The selected VLM proposes groups of existing step IDs using recorded visual/semantic evidence and Knowledge references. A deterministic validator enforces complete ordered coverage. Explicit confirmation creates independent draft packages and a non-executable composition proposal; the source and active equipment flow stay unchanged.

**Tech Stack:** Existing Python/FastAPI filesystem registry and vanilla JS workflow editor.

**Spec:** User-approved direction in this conversation: semantic splitting with confirmation, no invented actions, unseen branches require another demonstration.

## Global Constraints

- No equipment movement, test-step execution, compilation, deployment, or active-flow replacement.
- Preserve every source action exactly once and in order, including waits and embedded locators.
- Manuals come through Knowledge source_context; model output and reference text are untrusted.
- Explicit confirmation; source revision changes invalidate a proposal.
- Compact UI, no new dependencies. Existing dirty work is preserved; no commit/push requested.

## Review Focus

- Duplicate, omitted, reordered, invented step IDs: reject before creating children.
- Repeated confirmation or interrupted creation: deterministic identities, no overwrite, recoverable retry.
- Edited workflow/annotations/recording: stale proposal must not be applied.
- Cross-profile use and missing evidence: reject or retain explicit limitations, never claim verification.
- Unsaved editor changes and request errors: preserve edits and restore interactive controls.

### Task 1: Validated split drafts

**Files:** runtime/utils/equipment_skill_decomposition.py; runtime/tests/unit/test_equipment_skill_decomposition.py.
**Interfaces:** SkillDecomposition(registry).propose(skill_id, version, payload, model_snapshot); .apply(skill_id, version, proposal_id, confirmed=...).

- [ ] Write tests for ordered coverage, unchanged source, independent hash-valid review-required children, non-executable branches, stale source, repeat confirmation, conflicting children, write failure.
- [ ] Run the new pytest file: expect failures because implementation is absent.
- [ ] Implement proposal validation/persistence and confirmation with filesystem locking and staged publication. Store provenance and original evidence; never call equipment APIs.
- [ ] Run new tests plus existing registry tests: expect pass.

### Task 2: Selected-model API and editor

**Files:** runtime/app/main.py; workflow editor HTML/JS; runtime/tests/integration/test_equipment_skill_decomposition_api.py.
**Interfaces:** POST /api/equipment/skills/{id}/{version}/split-proposal; POST /split-proposal/{proposal_id}/confirm; GET /split-proposal/latest.

- [ ] Add API tests for selected-model proposal, explicit confirmation, profile mismatch and stale revision; run red.
- [ ] Add model adapter using existing visual evidence and Knowledge source_context, bounded JSON output, no action rewriting.
- [ ] Add Split Skills dialog: generate, inspect parts/branches, confirm, link to children; block unsaved changes.
- [ ] Verify APIs and editor interaction with isolated temporary registry. Browser plugin unavailable: use installed Playwright, no physical endpoints.

### Task 3: Verification and documentation

- [ ] Update equipment demonstration docs with split-draft semantics and limits.
- [ ] Run related registry/API/frontend tests and fresh-context review; fix important findings.
- [ ] Verify real VLM proposal on the saved PDF demo; create drafts only, no device execution.
- [ ] Apply to idle server and check editor. Report actual checks and limitations, no unsupported success claim.

## Execution ledger

- Working in the existing main checkout follows the user's prior explicit request to apply this authoring work to main. Auto-reload is off; temporary registries isolate verification. No unrelated dirty files are reverted.
- Interface review: all children consume unchanged source steps; model proposes IDs only. Branch suggestions are descriptive, not runtime graph edges.
- Task 1 complete: new partition tests failed before implementation; registry + split suite passed (54 tests). Additional 240-step, annotation-only stale revision and interrupted-publication coverage also passed.
- Task 2 complete: API tests failed with 404 before routes; all 3 passed afterward. Isolated browser flow passed preview → explicit confirmation → reload, error recovery, unsaved-edit refusal and 390px layout. No equipment endpoints were contacted.
- Task 3: related Python regression suite passed 350 tests (22 existing warnings), JS suites passed 15. Actual configured API/VLM with 12 recorded images and Knowledge Ready proposed three parts; all three child packages validated in temporary storage, original unchanged. Production retains proposal only until confirmation.
- Fresh-context review: no Critical/Important findings. Minor deferred: child summary initial/completion states use lists rather than the existing string normalization; typed-but-unapplied policy JSON follows the editor's existing Apply/Save semantics and is not included in dirty detection. Neither changes equipment execution or source data.
- Operational verification: idle server restarted (PID 2235477); no experiment started. Existing tab initially reused old cached JS, observed disabled new button. Versioned script URL fixed this; fresh reload enabled Split Skills and displayed the real three-part proposal with no console errors.
- Verification scope: device/equipment execution and repository-wide hardware-capable test scripts were intentionally not run. Human review and normal compile/validate/deploy remain required.
- Final fresh regression: 353 passed / 22 existing warnings in 40.95s; 15 JS tests passed; diff whitespace check clean. Operating latest-proposal API returned 3 parts, stale=false, no production confirmation; runtime is_running=false.
