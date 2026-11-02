# Rebot GUI runtime implementation plan

> **For agentic workers:** Use executing-plans and test-driven development.

**Goal:** Use the existing AX4LAB LeRobot GUI to configure, validate, start, observe and stop the installed Rebot dual-leader and Quest teleoperation/recording paths.

**Architecture:** Keep the existing GUI and API endpoints. Dispatch Rebot profiles to a small native adapter inside the LeRobot bridge. Use the installed native LeRobot CLI/config schemas, not OMX wrappers. Store machine-specific native settings locally per profile; never modify the Rebot deployment or actual runtime sources.

**Tech stack:** Python/FastAPI, existing vanilla JS GUI, native LeRobot Python environment.

**Spec:** User-approved two-profile request and subsequent requirement that the profiles actually work in the existing GUI. Existing setup repository and actual runtime are the source of truth.

## Constraints / review focus

- No robot connection, movement, calibration or CAN changes during verification.
- Existing OMX settings and behavior must not change.
- Preserve nested arm/camera config and native environment; do not inject OMX modules.
- Stop/status must be scoped to the selected profile/session; no global process cleanup or forced torque changes.
- Never accept a stale/unknown session as permission to stop another profile.
- Expose unsupported policy/replay paths honestly, not through silent fallback.
- Use real installed config parsers without constructing devices to verify both workflows.

## Tasks

- [x] Native adapter: persisted settings, strict schema/type boundary, native command generation, parser-only validation; unit tests first.
- [x] Existing bridge/API dispatch: native start/status/scoped graceful stop and record controls, isolation from OMX; lifecycle tests with fake process only.
- [x] GUI: conditional Rebot settings and validation, existing action buttons; browser test with no actuation.
- [x] Import local working configurations, run actual installed parser checks, independent review and document verified/unverified scope. AX4LAB restart approved; idle/no robot sessions verified.

## Progress

- Initial audit: existing serial/camera preflights, shared source environment, broad stop cleanup and OMX post-processing cannot be reused unconditionally for Rebot.
- Prior focused tests passed 5/5; bridge suite baseline 249 passed, 2 failed (missing temporary mirror runtime_paths dependency; pyav/torchcodec expectation). These unrelated failures are not being hidden or used to widen this task.

## Verification / handoff

- Focused native/profile/GUI suite: 79 passed. JavaScript suites: 14 passed.
- Installed Miniforge LeRobot parsed both native profiles for Teleop and Record, without constructing devices.
- Running server API verified both settings save/read round trips, parser validation, and four non-actuating command previews. Previous selected OMX profile restored; zero robot sessions created.
- Browser: both profiles' Use Profile, Validate Profile, Teleop preview and Record preview succeeded; OMX cards restored on switching back; no page errors. Browser verification rejects live execution requests.
- Independent review corrections: partial startup cleanup, truthful cleanup status, scoped PTY recording keys, external-owner detection, nested CLI mappings, FPS override validation and profile/session isolation.
- Regression bridge suite retains the same two pre-existing failures noted above; a new cache-version assertion failure was corrected and the focused suite rerun.
- Physical motion, actual camera streaming and a saved real episode remain unverified. No Rebot workspace, deployment repository, calibration or CAN settings were modified. Quest policy/replay and training are explicitly outside this adapter's supported workflows.
