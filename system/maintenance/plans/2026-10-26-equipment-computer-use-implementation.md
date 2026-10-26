# Equipment Computer Use Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox syntax for tracking. The user requested continuous implementation and verification; do not ask for another planning approval.

**Goal:** Deliver an opt-in screenshot-driven equipment executor with durable receipts, bounded model context, shared profile/Skill/IDE integration and non-actuating verification.

**Architecture:** A portable standard-library contract and worker controller live in the bundled Windows bridge. Linux's existing equipment Skill executor calls the worker through registered bridge tools, asking the pinned multimodal endpoint for one decision at a time. Existing Skill Flow, permissions, result verification and handoffs remain the owners of experiment semantics.

**Tech Stack:** Python, existing FastAPI/HTTPX backend adapters, stdlib Windows HTTP worker, existing vanilla JavaScript UI, pytest/node tests. No new model or desktop-agent dependency.

**Spec:** `system/maintenance/plans/2026-10-26-equipment-computer-use-design.md`.

## Global Constraints

- Existing execution defaults to `skill_flow`; the new mode is `computer_use` and never enabled by migration.
- No hardware actuation, production restart, private-state copy, model service start, merge or push during implementation.
- Preserve deployed Skill hashes, run/cycle/specimen/profile identities, entry gates, current-cycle CSV and clearance checks.
- One mutating action per decision; normal inference includes one latest image, never an unbounded screenshot history.
- Default `max_turns=64`, `request_timeout_s=120`, two format attempts per observation. Existing deadlines remain authoritative.
- Strict JSON decisions reject unknown/extra fields, wrong types, NaN, truncation, duplicate keys and stale observation IDs.
- Physical operations use declared registered programs. Raw GUI actions require declared target permissions, anchors and protected-region checks.
- No implicit endpoint/provider fallback for computer-use screenshots; existing other-agent fallback remains unchanged.
- First supported package is synthetic `computer_use_demo_v1`; actual UTM mapping/deployment is not acceptance for this delivery.
- Existing baseline failures must be named, not hidden or solved by weakening experiment checks.
- Use `apply_patch` for edits, TDD, and local commits with verified identity `JIN <JIN9811@users.noreply.github.com>`.

## Review Focus

- Two profiles selecting the same desktop must not interleave actions or bypass ownership through legacy console routes (Task 2).
- An HTTP timeout or process crash must not create a fresh action ID and repeat a possible physical effect (Tasks 2–3).
- UI reload/settings save must not retarget an active model/worker or erase unrelated profile preferences (Tasks 1, 3–4).
- Stale/resized/masked screenshots and hostile screenshot text must not become action authority (Tasks 1–3).
- A fake `complete`/old CSV or missing postcondition must not advance a Skill or the experiment (Tasks 2–3, 5).

## References and reuse decisions

- UI-TARS Desktop commit `3ac2cb8d946d78d5ff92ad17b318eaafa18c178c`, Apache-2.0:
  [GUIAgent](https://github.com/bytedance/UI-TARS-desktop/blob/3ac2cb8d946d78d5ff92ad17b318eaafa18c178c/multimodal/gui-agent/agent-sdk/src/GUIAgent.ts),
  [ActionParserHelper](https://github.com/bytedance/UI-TARS-desktop/blob/3ac2cb8d946d78d5ff92ad17b318eaafa18c178c/multimodal/gui-agent/action-parser/src/ActionParserHelper.ts).
  Reuse the observe-after-action/operator separation and explicit coordinate transformation ideas. Do not vendor its model-specific permissive text parser, shell tools, or whole TypeScript desktop stack. New Python implementation; no upstream source copied.
- [vLLM structured outputs](https://docs.vllm.ai/en/stable/features/structured_outputs/): use `response_format` JSON Schema where supported and local strict validation regardless of provider.
- The earlier computer-use guide informed the loop; no OpenAI-specific computer-use API dependency is added.

## Shared contracts

The canonical portable module is `runtime/Pyautogui_server_for_window/bridge/computer_use_contract.py`; Linux imports it through the existing namespace package. The worker package ships it beside its server. The legacy installer helper uses the same packaged module when present and advertises the new capability unavailable when it is absent; legacy functionality must still import/run. Do not duplicate new protocol logic into two server copies.

`ComputerUseError(ValueError)` carries `code` and a non-secret message.

`normalize_settings(raw: dict | None) -> dict` returns:
`{execution_mode: skill_flow|computer_use, computer_use: {max_turns: int, request_timeout_s: float, frame_max_age_s: float}}`.
Bounds: turns 1..256, request timeout 1..300 s, frame age 1..600 s; defaults 64/120/150. Booleans are not numbers. Missing input preserves legacy defaults; partial updates are merged by the settings owner before normalization.

`validate_policy(raw: dict) -> dict` accepts schema `ax4lab.equipment_computer_use.policy.v1`:
- `application`: exact nonempty `window_title`;
- `targets`: mapping of target ID to `region` [x,y,width,height] relative to native application window, `actions`, and `anchor` (`region`, lowercase SHA-256 of RGB pixels). Keyboard targets additionally declare allowed keys/chords. Regions are finite nonnegative and nonempty; targets cannot overlap protected regions;
- `protected_regions`: list of window-relative rectangles (may be empty for a non-equipment demo);
- `program_ids`: explicit registered program IDs (may be empty);
- `runtime_value_keys`: allowed text-value keys (may be empty); model text is never directly used as an export destination;
- `postconditions`: nonempty list of image-region/hash checks or registered evidence-check program references. Evidence programs must be declared read-only checks, not replayed mutating programs;
- `mask_regions`: bounded window-relative rectangles, applied before image leaves worker; target/anchor/postcondition overlap is rejected.
Builder may add necessary bounded fields with explicit validation; report the interface addition before a downstream task consumes it.

`parse_decision(text: str, observation_id: str) -> dict`, `decision_json_schema() -> dict` use schema `ax4lab.equipment_computer_use.decision.v1`.
Decision common fields: `schema`, `observation_id`, `kind`, `reason` (max 512 chars).
- `act`: `action` object. Types: `click`, `double_click`, `scroll`, `press`, `hotkey`, `write`, `invoke_program`. GUI actions name a `target_id`; pointer actions use image-pixel `x`,`y`; scroll adds `amount` -10..10, nonzero; press uses `key`, hotkey `keys`; write uses `value_key`; invoke_program uses `program_id`. No arbitrary code, URLs or model text input.
- `wait`: `seconds`, 0..10 inclusive.
- `complete` and `needs_operator`: no action/seconds.
`validate_action(action, policy, observation, runtime_values) -> dict` checks permission and maps image pixels to desktop coordinates with half-open bounds. Identity and permission data are never model supplied.

Observation: `observation_id`, `worker_id`, `session_id`, `captured_at` (UTC ISO), `image_width`, `image_height`, `desktop_rect`, `window_rect`, `window_title`, `window_id`, `image_sha256`, `image_base64` (PNG), `anchor_hashes`. Hashes/dimensions are verified on both sides. Raw images may be held only during capture; no unmasked persisted copy.

Worker protocol capability: `computer_use_v1`; operations `acquire`, `observe`, `act`, `status`, `verify`, `release` over authenticated `/computer-use/<operation>` POST routes. Requests carry host-owned execution/run/cycle/specimen/profile identity; after acquire, lease token. Action has host-issued `action_id`, canonical `payload_sha256`, observation ID and decision action. Returns `ok/status/failure_code`, observation or receipt. Status query must return `not_found`, `in_progress`, `completed`, `failed` or `ambiguous` without dispatch.

### Task 1: Portable decision, permission and settings contracts

**Files:** Create portable `computer_use_contract.py`; create `runtime/utils/equipment_computer_use_settings.py`; create `runtime/tests/unit/test_equipment_computer_use_contract.py` and `test_equipment_computer_use_settings.py`.

**Interfaces:** Produces all pure contract functions above. Settings store exports `load_profile_settings(path: Path, profile_id: str) -> dict` and `save_profile_settings(path, profile_id, patch) -> dict`, preserving unknown existing preference keys and other profiles under the existing `profiles` envelope, with atomic process-safe updates.

- [ ] Write parameterized failing tests for legacy defaults, invalid settings, valid four decision kinds, duplicate/extra/malformed/truncated JSON, NaN/bool coordinates, unknown types and observation mismatches.
- [ ] Write failing policy/coordinate tests: image 960×540 → native [100,50,1920,1080], (480,270) maps to (1060,590); right/bottom exclusive; protected/masked regions and missing anchor/permission reject actions; unknown runtime values are rejected.
- [ ] Run focused tests in the sandbox; confirm failures are due to missing behavior.
- [ ] Implement the portable schema/parser/validators without GUI, network or third-party imports; settings store uses existing envelope and flock/atomic persistence on Linux.
- [ ] Test profile A/B isolation, partial updates and unknown-key preservation; run focused suite, record RED/GREEN and commit.

### Task 2: Authenticated worker protocol and bridge tools

**Files:** Create `runtime/Pyautogui_server_for_window/bridge/computer_use_runtime.py`; modify both existing `windows_pyautogui_bridge_server.py` copies, `runtime/device_bridges/windows_pyautogui/{bridge,tools,module}.py`, worker `release_manifest.json`; add `runtime/tests/unit/test_equipment_computer_use_worker.py` and bridge tests in `test_equipment_pyautogui_bridge.py`.

**Interfaces:** Consumes Task 1 contract. Produces `ComputerUseController(root: Path, adapter, worker_id: str)` and `handle(operation: str, payload: dict, principal: str) -> dict`; `legacy_mutation()` context manager shares ownership/lock. Adapter owns `capture(policy) -> observation`, `execute(validated_action, context) -> receipt`, and `verify(policy, context) -> evidence result`. It must call the existing worker's registered program/evidence paths, never execute model-generated programs. Registered Linux tools: `equipment.pyautogui.computer_use_<operation>` for six operations, all profile-scoped and mutation tools assigned the existing device queue. `WindowsPyAutoGUIBridge.computer_use(operation, payload) -> dict` performs existing live gates and capability negotiation, with no raw-execute fallback.

- [ ] Write failing controller tests using an injected synthetic desktop adapter: acquire/observe/act/verify/release, wrong principal/token, two profiles one desktop, same ID same hash one effect, changed hash rejection.
- [ ] Test concurrent calls, persisted intent before action, fsync/write failure means zero effects, timeout/status reconciliation, restart marks unresolved action ambiguous, expiry cannot steal executing/unresolved desktop, and legacy route exclusion.
- [ ] Implement a bounded controller with a worker-wide mutex plus durable lease/action ledger. Avoid holding a global lock through a long physical program while preventing new inputs. Tokens never appear in public logs. Revalidate current application/window geometry and target anchor immediately before input.
- [ ] Integrate native capture/dispatch and new authenticated HTTP routes. Reuse existing pyautogui/program validation. Apply masks before PNG encoding; reject unavailable window/DPI context instead of guessing. All conflicting existing execution/recording/program mutation routes honor ownership while inactive behavior stays unchanged. Capability unavailable when optional packaged module cannot load.
- [ ] Add client methods and declared registered tools; reject unsupported workers before execution and preserve profile/live-mode/auth guards. Include the new files in the worker release allowlist.
- [ ] Run unit + worker HTTP/client integration tests in sandbox; record source-copy parity and legacy regressions; commit.

### Task 3: Bounded model loop and existing Skill execution integration

**Files:** Create `runtime/agents/equipment/computer_use.py`; modify `runtime/agents/equipment/agent.py`, `runtime/utils/equipment_skill_runtime.py`, `runtime/utils/equipment_skill_workflow.py`, `runtime/backends/{vllm_client,openai_client}.py` only where needed for schema metadata; add `runtime/tests/unit/test_equipment_computer_use_runner.py`, `runtime/tests/integration/test_equipment_computer_use_execution.py`.

**Interfaces:** Consumes Task 1 contracts and Task 2 tools. Produces `async run_computer_use(*, state, ctx, request, package, execution, settings, call_tool, on_progress=None) -> dict` returning the existing equipment raw-result envelope plus `computer_use` metadata. `call_tool(name,payload)` is the existing guarded registered tool pathway. Freeze endpoint, Skill/program/policy hashes and worker selection once; no calls through shared fallback or service-start behavior. Store policy in versioned Skill workflow `computer_use` data so existing integrity hashing covers it; old packages remain valid for legacy mode.

- [ ] Test the real async loop with deterministic fake model/transport boundaries: complete requires real worker verification; failed/missing postconditions fail; one new observation per mutation; image/history bounds stay fixed for 64 turns; stale model results never act.
- [ ] Test typed rejection/no mutation, two-format-attempt ceiling, timeout queries same ID rather than reissuing, cancellation during inference/action, worker error, operator request, active run identity pinning, missing policy, and old worker capability failure.
- [ ] Implement pinned endpoint resolution from the existing endpoint registry and shared backend adapter. Disable automatic service start and cross-provider fallback for this task only. Add bounded JSON-schema metadata support with safe JSON-object fallback only for explicit unsupported-schema response; preserve existing tasks' payloads. Retain transport usage/finish_reason for truncation rejection and audit.
- [ ] Implement durable step artifacts (masked observation, decision, receipt, verification, timing/usage), hash-linked to execution and existing run artifacts. Keep at most two image objects and six recent text receipts in model context; bound metadata lengths. No full run-state dump in prompts.
- [ ] Branch inside `_run_equipment_skill` only after existing deployed package/profile/run checks, select mode from frozen profile settings, and feed results through existing verification/Skill lifecycle/flow. Capture settings once for the enclosing flow and standalone run, including resume semantics. No new flow-stage shortcut.
- [ ] Test legacy mode call equivalence, Skill hash tamper rejection, current-cycle CSV/clearance gating, package/runtime progress integration, and no mock completion in live mode. Run focused/regression suites, record RED/GREEN, commit.

### Task 4: Profile/Skill/Runtime IDE controls and readiness

**Files:** Modify `runtime/app/main.py`, existing equipment request models, `runtime/web/templates/windows_equipment.html`, `runtime/web/static/{windows_equipment,equipment_skill_workflow_editor,runtime_ide}.js` as necessary. Add focused JS and API tests. Do not create a separate app/page/model catalogue.

**Interfaces:** Uses Task 1 profile store and Task 3 workflow policy validation. Existing profile settings GET/POST envelope gains normalized mode/limits. Policy editing is on versioned editable Skill data, not an unsigned execution override. Readiness reports worker capability, endpoint vision and declared Skill policy/postconditions without actuating or starting a model.

- [ ] Write failing API/JS behavior tests for mode default, persist/reload, invalid mode/limits/policy, profile isolation and preserving `vision_link_enabled`/unknown preferences.
- [ ] Add an English execution-mode select and bounded inputs in existing Settings. Save/Apply never starts equipment. Show capability/policy/endpoint readiness and the concrete unavailable reason.
- [ ] Add policy editing/validation using the existing Skill editor and deploy pipeline; expose the same settings and validation in Runtime IDE. Deployed Skill policies are not changed in place.
- [ ] Show computer-use step/observation/action/evidence links in existing progress panels; browser refresh reads persisted state and never launches inference. Escape model-provided text using existing DOM safe helpers.
- [ ] Verify desktop UI via isolated browser fixtures, existing profile controls and Runtime IDE serialization; record tests and commit.

### Task 5: Synthetic end-to-end package, documentation and full regression

**Files:** Add `runtime/tests/fixtures/equipment_computer_use/` synthetic package and image fixtures; add `runtime/tests/integration/test_equipment_computer_use_e2e.py`; update worker README, `system/agents/equipment_agent.md`, `system/device_bridges/windows_pyautogui_bridge.md`, user manual EN/KO, `runtime/distribution-files.json` and layout manifest only for owned new files.

**Interfaces:** Exercises Tasks 1–4 without production data, network or devices. The fixture package `computer_use_demo_v1` uses a synthetic desktop adapter and a persisted result artifact; it is never installed in an operator's profile automatically.

- [ ] Add a failing full-path test: profile settings → valid versioned Skill → equipment agent → registered worker tools → model decision boundaries → postcondition/evidence → existing Skill/flow result. Verify artifacts and hashes, browser reload idempotency, interrupted/ambiguous receipt handling and legacy execution side-by-side.
- [ ] Supply the synthetic package through test fixtures; verify success and failure cases do not rely on model saying done. Keep all test-only adapters under tests.
- [ ] Document setup, limits, permission authoring, Windows worker compatibility/update requirement, endpoint requirements, artifacts, unknown-action recovery, disabled-by-default rollback and validation limits. Add pinned upstream references; state code is an original integration, not a UI-TARS model dependency.
- [ ] Run all focused tests and the repository suite in blocked-device/network sandbox. Name baseline/environment failures individually. Run node tests and source/manifest parity checks; never fix unrelated tests by weakening production checks.
- [ ] Optional non-actuating real-model fixture evaluation only if the configured endpoint is already running and available; do not start it. Otherwise report actual-model and Windows hardware validation as not run.
- [ ] Whole-branch review, fix verified important findings with regression tests, update this plan's ledger, and leave the isolated feature branch ready for separately authorized deployment/merge.

## Verification commands and worktree

Worktree: `/home/jin/Desktop/AX4LAB/.worktrees/equipment-computer-use`, branch `feat/equipment-computer-use`.
Baseline parent: `95025c9`. Python interpreter is the existing outer `.venv/bin/python` with worktree runtime on PYTHONPATH; no editable install changes.
Run Python through the controller-provided `.superpowers/sdd/2026-10-26-equipment-computer-use-implementation/run-tests.sh`; it isolates network, devices and writable state.
`node --test runtime/tests/js/*.test.js` uses the installed Node runtime. Full suite is the same sandbox script without test file arguments.

## Execution notes

- User explicitly selected subagent implementation and immediate continuous execution; use a fresh implementer and scoped review per task, then final review. No additional planning approval is pending.
- New source files remain in the isolated branch. Main production checkout and Windows PC remain unchanged.
