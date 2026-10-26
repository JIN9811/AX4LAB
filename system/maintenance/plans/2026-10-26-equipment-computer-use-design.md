# Equipment computer-use execution

Status: approved by the user on 2026-10-26; implementation requested with subagents.
Baseline: `9ac1812` on `main` (2026-10-26).

## Intent

Use the configured multimodal LLM to observe the equipment application's
screen, select a small action, inspect the result, and continue the current
task. This is inference-time GUI control, not VLA training or robot control.

The user requested a baseline commit/push followed by design and implementation.
The discussed direction is an opt-in executor inside AX4LAB's existing equipment
module. It must retain profiles, Skill Flow, runtime identity, equipment evidence,
and the experiment's completion/handoff rules.

## Approaches

1. **Structured decisions inside the existing equipment runtime — selected
   direction.** A fixed JSON action contract works with the existing endpoint
   model calls. A trusted dispatcher executes actions and gathers new evidence.
   This requires a bounded loop and worker protocol support but does not depend
   on a particular model's native tool-call parser.
2. **Native model tool calls.** Appropriate later for endpoints with verified
   tool schemas and parsers. It would add model-specific compatibility work now;
   it would not remove the need for execution, evidence, and recovery controls.
3. **An independent desktop agent.** Simpler as a demonstration, but would duplicate
   equipment execution and could bypass run/Skill/CSV identity. Not selected.

The details below are implementation proposals, not claims about existing
behavior or hardware validation.

## Scope and non-goals

- Add a profile-scoped execution mode and a computer-use executor.
- Reuse the existing equipment agent, deployed Skill package, block order,
  approved task, registered tools, runtime projection, and artifact system.
- Keep the existing Skill execution path as the default. Missing configuration
  means the old path; existing profiles and saved flows are not migrated into
  computer-use mode.
- Do not change other agents, experiment routing, model selection, calibration,
  specimen checks, PLC safeguards, or UTM completion criteria.
- Do not install another model, add a second inference server, or train a policy.
- Do not deploy to the Windows PC, restart production, or actuate equipment as
  part of implementation verification. Those require a separate deployment/test
  step. An old worker remains usable in legacy mode.
- Do not promise reduced latency or KV memory before measuring it.

### First supported Skill and delivery boundary

The first fully configured Skill is a synthetic `computer_use_demo_v1` package
for a non-equipment screen fixture: navigate to a form, enter host-supplied
values, submit, and verify a saved fixture artifact. It is deployable only to the
isolated test worker and is never automatically added to the real profile.
Include target/permission/postcondition authoring and readiness validation so
real equipment Skills can subsequently opt in through the same contract.

This delivery does **not** claim that UTM_QM or another physical UTM is ready for
autonomous computer-use. Authoring actual equipment control mappings and proving
their postconditions requires observing that application's screens and a
separately authorized validation. Existing UTM Skills and their deployed hashes
remain unchanged. This is the proposed acceptance boundary for design approval.

## Existing integration points

| Responsibility | Existing owner | Change |
| --- | --- | --- |
| Profile/worker selection | `utils/equipment_profiles.py`, profile settings API | Persist execution mode and limits; pin a snapshot at task start |
| Workflow and handoff | `EquipmentAgent._run_equipment_skill_flow` | Keep canonical blocks, entry gates, transition records and completion binding |
| Deployed Skill execution | `EquipmentAgent._run_equipment_skill` | Select legacy or computer-use execution after package/profile checks |
| Execution persistence | `EquipmentRuntimeService`, `EquipmentSkillRegistry` | Reuse execution identity and lifecycle; attach computer-use step metadata |
| Tool/device ownership | `device_bridges/windows_pyautogui` | Register observe/action/status tools under the existing bridge module |
| Desktop execution | Bundled Windows worker and installer copy | Add capability-negotiated, authenticated execution protocol |
| Model transport | `BaseLLMBackend.complete`, endpoint routing | Add task-specific structured-output metadata; do not change other tasks |
| Workspace | Existing equipment page and Runtime IDE | Show mode, readiness, current observation/action and artifacts in existing panels |

The current flow requires deployed Skill bindings. This design preserves that
requirement: the Skill supplies task intent, allowed capabilities, target app,
and verified postconditions. Computer-use selects GUI actions instead of
replaying recorded pointer steps. It is not a way to run an unbound task or
declare completion without a deployed contract.

## Execution contract

At entry, freeze the profile, worker identity, endpoint reference, Skill version
and hashes, flow/block, run/cycle/specimen IDs, export context, and execution mode.
Applying another profile or changing settings affects the next execution only.
Both workspace Run and the experiment loop use this same executor.

The block execution sequence is:

1. Perform the existing Skill/profile/run and live-execution checks.
2. Check endpoint vision capability and worker computer-use protocol support.
3. Acquire exclusive desktop ownership for this execution.
4. Capture an authenticated, identified screenshot of the allowed application.
5. Ask the configured model for one structured decision.
6. Validate the entire response, scope, frame, action and task permissions.
7. Execute at most one mutating action and record its receipt.
8. Capture fresh evidence; evaluate trusted postconditions; repeat if necessary.
9. Return through the existing Skill result, block transition and handoff code.

The first version allows one mutating action per turn. `wait`, completion
proposals and escalation are separate decisions. This keeps intermediate
navigation observable; larger batches are deferred.

### Decisions

Use a versioned schema, for example `ax4lab.equipment_computer_use.decision.v1`.
Every response carries the supplied observation ID and exactly one of:

- `act`: one allowed click, double-click, scroll, key operation, bounded text
  input, or invocation of a specifically declared registered operation;
- `wait`: bounded observation delay without input;
- `complete`: request trusted postcondition verification;
- `needs_operator`: a short, visible reason.

Use strict field/type checks, bounded strings/numbers, finite coordinates and
`additionalProperties: false`. Reject unknown actions, conflicting branches,
partial/truncated output, Markdown-wrapped output, extra JSON objects and stale
observation references. A format retry receives validation feedback but performs
no desktop action. At most two format attempts per observation.

The LLM cannot supply executable Python, shell/PowerShell, API URLs, tokens,
program definitions, result evidence, arbitrary filesystem destinations, or
replacement run IDs. Text input uses declared fields and host-resolved values
where identity matters, such as the current-cycle CSV filename.

### Action authority and physical operations

The application/window and permitted GUI controls come from the deployed Skill,
not from screenshot text. Screens and retrieved documents are untrusted data.
Coordinates use screenshot pixel dimensions with an explicit mapping to native
desktop pixels; reject changed window geometry, wrong foreground application,
out-of-range targets, or unsupported display transforms.

A window allowlist alone is not sufficient for a UTM. Each computer-use-enabled
Skill must declare allowed targets and protected controls. Starting compression,
moving the actuator and other physical operations remain registered, guarded
operations; the model cannot substitute a raw coordinate click on those
controls. GUI navigation and data entry may use fresh visual grounding within
the declared permitted targets. A missing target/permission mapping makes that
Skill unavailable in computer-use mode, not less restrictive.

Existing evidence checks remain authoritative. A `complete` response, a successful
click receipt, or an unchanged screenshot does not establish test completion,
specimen clearance, exported CSV validity, or readiness for analysis.

## Worker protocol and concurrency

Expose a versioned computer-use capability through the worker's authenticated
health/capability response. Add authenticated observe, execute, status and
release operations. These do not inherit localhost unauthenticated setup access.
An unsupported worker returns an actionable upgrade-required status before any
input. There is no fallback from unsupported computer-use to raw `/execute`.

Maintain one active desktop lease per worker desktop, not one per profile.
Ownership includes worker boot/session identity, authenticated principal,
execution ID and an unguessable lease token. Existing mutating HTTP operations,
local console execution and recording operations that conflict with ownership
must respect the same worker lock. Independent profiles cannot control the same
desktop concurrently. Passive status reads remain available.

An observation includes worker/session identity, frame ID, timestamp, image hash,
dimensions, application/window identity and geometry. The worker verifies
ownership, frame age, foreground/geometry and declared target guards immediately
before mutation. Avoid requiring the entire screenshot to be pixel-identical:
changing force/time displays must not invalidate otherwise stable controls.
Protected target regions/anchors are checked explicitly. Physical races with
human input cannot be eliminated; unexpected focus/input invalidates the turn.

An action has a host-issued ID and canonical payload hash. Persist intent before
dispatch and receipt after execution. Repeating the same ID/hash returns status
or the original receipt; the same ID with different content is rejected. A
network timeout triggers a status query, never a new action ID and blind retry.

After worker/server restart, an intent without a terminal receipt is ambiguous.
Do not replay it automatically. Reconcile current observation and task-specific
evidence; if these cannot prove the effect, use the existing operator-attention
path. This is at-most-once dispatch with ambiguity handling, not an exactly-once
claim. Lease expiry does not authorize another operation while an earlier action
is still executing or unresolved.

Cancellation stops future actions and drains/reconciles an in-flight action.
It must not claim that a desktop click already sent was undone, or that a UTM
motion stopped. Existing equipment stop semantics stay unchanged.

## Model context and memory

- Resolve the endpoint by its registered reference and capabilities, not a
  hardcoded Gemma/model name. Use the existing endpoint auth and model selection.
  Pin the endpoint for a computer-use execution and do not traverse the shared
  cross-provider fallback chain for its screenshots. Other agent tasks retain
  their existing configured fallback behavior.
- Send an unchanged instruction/schema/task prefix, then compact authoritative
  state, recent action receipts, and the latest screenshot.
- Retain one screenshot in normal requests. Permit two only for an explicit
  before/after comparison. Do not append all historical frames to the conversation.
- Bound recent textual action history independently from the persistent audit
  ledger; summaries never replace run identity, action receipts or evidence.
- Display/video frames are not model requests. Only completion of an action,
  task-relevant change or a bounded wait schedules another observation/inference.
- Allow one inference request per desktop execution. Late responses from a
  cancelled/superseded turn cannot execute. Keep only the latest pending frame.
- Use JSON Schema constrained output when the endpoint supports it. Otherwise,
  use the same strict local validator with JSON-content output. An unsupported
  schema retry is allowed only for an explicit capability error, before execution;
  never change endpoint/model automatically.
- Record prompt/completion tokens and cache/latency metrics when returned by the
  endpoint. Mark absent cache counters unavailable rather than zero. Fixed-prefix
  caching is an opportunity, not a correctness dependency.

Profile settings expose the maximum decision turns and per-request timeout.
Builder defaults: 64 decision turns per active GUI-navigation block, 120-second
model request timeout, two format attempts. Existing block/experiment deadlines
remain authoritative and are never reset by another decision. Long UTM monitoring
uses the existing monitor/wait operation, not 64 screenshots in a tight loop.
These limits apply only to the new mode, not existing experiment cycles.

## Persistence, GUI and module contracts

Profile Settings adds `Execution mode: Skill Flow / Computer Use`, with Skill Flow
selected by default. It uses the existing equipment endpoint selection; no
duplicate model catalogue. Show endpoint/worker/Skill readiness and the concrete
reason if the new mode is unavailable. Save persists settings; Apply/Run do not
silently switch workers or models. Preserve existing settings when saving new
keys; the current profile-settings writer replaces the record and must be made
merge-safe for these fields.

Runtime IDE uses the same profile setting and deployed Skill contract. Extend
the existing Skill schema/validation/editor only with explicitly declared
computer-use permissions and postcondition references. Old Skills remain valid
for legacy execution and unavailable for computer-use until configured. Do not
generate permissive defaults or silently rewrite deployed Skill hashes.

Use the existing Agentic Progress lifecycle, current block, cancel and runtime
list. Add observation/action/validation details there rather than a separate
agent or a second progress state machine. Reloading the browser reads persisted
execution state and never starts another worker or model call.

Store step observations, decisions, execution receipts, validation results and
timings under the run's artifact tree with run/cycle/profile/Skill identities.
Images and receipts have content hashes. Link them through the existing artifact
collector so report/replay consumers can inspect them. Retain the audit ledger
on disk while keeping in-memory history bounded. Mask configured sensitive screen
regions before inference and persisted previews; never log credentials. Fail
before actuation if a required durable receipt cannot be written.

Update bridge module tool declarations, Skill/package contract checks, runtime
metadata and public user instructions. Keep the installer worker and bundled
worker source synchronized and add an explicit source-parity assertion; update
release manifests and their existing allowlist tests if files are added.

## Verification and rollout

Implement in an isolated worktree/server with temporary storage and blocked
device/network access. Reuse the installed Python environment without copying
private connections or historical experiment data. No production reload during
development.

Required tests:

- Legacy mode produces the same tool calls/results; profiles are isolated and
  active execution settings cannot be retargeted.
- Structured output validates types, bounds, truncation, stale frames and prompt
  injection attempts; completion proposals cannot manufacture evidence.
- Coordinate mapping covers resize, DPI, changed windows and non-square images.
- Duplicate IDs, mismatched hashes, delayed/lost responses, worker restart,
  concurrent profiles/legacy console requests and cancellation do not repeat
  physical effects.
- A synthetic desktop adapter exercises navigation, typing, scroll, waits,
  task completion, wrong application, popups and operator-required paths.
- Existing Skill Flow, package/deployment integrity, entry vision, current-cycle
  CSV binding, clearance evidence and equipment-to-analysis handoff still apply.
- Browser fixtures verify persistence, mode readiness, reload and current progress.
- Context stays bounded over a long synthetic session; no retained unbounded
  image list and no inference launched by every video frame.
- Worker capability and source/release parity are tested.

Then perform an optional actual-model, non-actuating evaluation on fixtures using
the configured endpoint. Do not start a model service or replace the endpoint.
Report action-schema validity, target accuracy and latency separately from mock
test results. Real Windows/UTM execution remains unverified until a supervised
test is explicitly arranged and the upgraded paired worker is ready.

Baseline verification before this feature: 53 JavaScript tests passed; the scoped
Python run had 391 passes, 6 failures and 3 skips. Failures concern local layout
receipts/files, two existing progress-source assertions, an offload function-name
assertion and a missing OMX mesh route. Keep these visible; do not change
experiment logic or weaken tests just to report a green feature baseline.

## Approval decisions

The proposed implementation preserves the old execution mode, reuses deployed
Skills as task/permission/evidence contracts, and keeps physical controls on
registered guarded operations. It requires an updated Windows worker for the
new mode. Development and synthetic validation occur in an isolated worktree;
production deployment and real equipment execution are separate steps.

Builder check completed: the only major ambiguity was which Skill must be ready
in this delivery. The synthetic first-Skill boundary above resolves the proposal;
the user can choose to expand it to equipment-specific mapping before approval.
