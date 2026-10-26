# Equipment profile workspace implementation plan

> Use test-driven development and inline execution. Preserve unrelated local changes.

## Design agreed in conversation

New Profile creates another UTM, not an LLM role. Selecting/creating a profile reloads all lower workspace panels for that profile. Apply persists the profile/worker combination for future execution, without starting equipment. Existing UTM data remains unchanged. Custom profiles start empty rather than inheriting physical locators, credentials, Skills or evidence.

## Architecture

Extend the existing equipment registry with a private persistent profile catalogue. Scope the existing bridge APIs and worker storage by profile; preserve legacy paths for the built-in UTM. Keep the same workspace template and execution contracts. Reload the workspace on selection to prevent stale asynchronous responses. Pin execution to a profile at agent entry; applying configuration does not retarget active operations.

## Constraints and review focus

- No hardware, model calls, production restart, commit or push during verification.
- Do not copy old physical coordinates or tokens into another UTM.
- Reject invalid/unknown profile IDs, never silently use another device.
- Scope recordings, Skills, jobs, runtime and evidence as well as visible form fields.
- Keep explicit run profile identity stable; reject Apply during an active run.
- Retain previous endpoint/PLC work and operator settings.
- Work in the existing requested checkout; tests use isolated writable temp storage and blocked device/network access.

## Tasks

- [x] 1. Add failing storage/bridge/API tests: creation persistence, duplicate/path rejection, independent config/credentials, Apply with worker, busy protection, runtime identity.
- [x] 2. Implement profile catalogue in `runtime/utils/equipment_profiles.py`, scoped bridge configuration and existing API integration. Verify the failing tests become green.
- [x] 3. Add New Profile / Apply to `windows_equipment.html`; profile-aware reload, API queries, local job keys and Skill/runtime filtering in `windows_equipment.js`. Verify desktop/mobile interaction against isolated fixtures.
- [x] 4. Run existing relevant equipment tests, inspect full diff, update user docs and report verification limits. No equipment actuation or operational restart implied.

## Progress

- Investigation: existing dropdown is display-only; bridge settings and connection memory are shared; runtime already supports profile filters; Skill Flow is already keyed by profile.
- Verification: 14 new profile tests pass; focused equipment regression suite passes 227 tests. Expanded GUI regression: 337 passed, 3 failures in unrelated existing progress-source assertions and a missing OMX mesh asset. These failures were not suppressed or changed.
- Browser verification: real template and scripts with isolated API fixtures, desktop 1920×1080 and mobile 390×844. Creation, navigation, Apply, old-profile restoration and no page errors verified. No physical calls.
- Review: fixed cross-profile evidence/current-history leaks, default-profile execution pinning, explicit Skill bridge ownership and saved Worker precedence after Apply. Follow-up review found no remaining important issue in that scope.
- Deployment: operational server was not restarted; restart approval requested separately. No commit or push performed.
- UI refinement requested by user: replace the redundant Worker dropdown with an inline Profile name input. New Profile or Enter creates and persists the profile, then navigates to its workspace. Apply uses the existing Saved Workers selection. Browser desktop/mobile checks and 48 JavaScript tests plus 15 profile/storage/API tests pass; no operational restart performed.
- Deployment follow-up: restarted the idle operational server with user approval. Real browser creation of `UTM 2` and reopening after reload verified. Reproduced unresponsive New Profile with a cached pre-profile script; versioned the workspace script URL to invalidate it.
- Delete follow-up requested by user: confirmation names the selected profile; cancel sends no request. Retire custom profiles from the catalogue while retaining saved settings and evidence. Protect built-ins, the applied profile and active runs/jobs. Return to the applied profile after deletion, and reject stale deleted-profile URLs.
- Follow-up verification: 52 JavaScript tests and 20 profile/storage/API tests pass. Browser fixtures exercise stale-cache creation, Enter, Apply, cancel/confirm deletion, reload and applied-profile protection with no page errors. Full Python suite attempted in the device/network-blocked sandbox; collection stops at `tests/unit/test_specimen_pose_tracker.py` because that isolated Python environment lacks `cv2`. No unrelated tests or experiment logic changed to suppress this limitation.
- Review follow-up: protect profiles during console proxy mutations until the actual worker finishes, including browser-request cancellation; restore Delete Profile button text after a rejected request. Final focused suites: 53 JavaScript + 22 Python tests pass. Browser creation/deletion fixture remains green; versioned script served by the live idle server.
- Final identity-race regression: read the console request body before resolving its bridge/profile so an intervening Apply cannot separate execution from its deletion guard. 23 Python profile tests now pass (53 JavaScript tests unchanged).
