# Human demonstration and visual Skill recovery

## Approved scope

Extend the existing Equipment Skill path: human demonstration recorded at 15 FPS, separate capture from encoding/storage, VLM-assisted interpretation into the existing editable Skill, and screenshot-grounded restoration before resuming a failed segment. Keep existing equipment contracts and completed-operation boundaries. No production restart or physical equipment execution in this change.

## Tasks

1. Recorder: default 15 FPS; bounded producer/writer queue; timestamp acquisition separately from storage; preserve input/event pre/post evidence; drain before finalizing; report overload/failures instead of claiming complete evidence. Synchronize Windows distribution. Focused concurrency/evidence tests and short isolated capture benchmark.
2. Authoring: use existing recording import, annotations and compile lifecycle. Select bounded event/transition frames from the full recording; retain all original evidence. Store VLM intent, pre/post conditions, target semantics, success/failure evidence and proposed variables as reviewed annotations. Do not modify human actions or deploy ambiguous/model-generated changes automatically. Focused API/runtime tests.
3. Recovery: give the selected VLM fresh screen evidence and bounded existing task/Skill context. Execute only permitted recovery operations, verify a fresh restored screen, and resume the same unexecuted segment. Never repeat completed/unknown-effect physical operations. Persist recovery evidence/candidates without automatic Skill promotion. Focused execution tests.
4. Integration: wire existing GUI/authoring controls and documentation; run the relevant combined tests, a short 15 FPS recording check, and a bounded isolated visual-model smoke if the configured endpoint is available.

## Shared interfaces

- Keep recording/Skill schema compatibility and hash-addressed artifacts.
- Authoring consumes existing periodic/event/boundary evidence; recording FPS is independent of VLM sampling.
- Recovery consumes existing annotation context and uses existing bridge tools plus execution journal.
- Recorder files, annotation files, and recovery files have separate owners; shared runtime changes are coordinated.

## Verification limits

Use targeted regression tests, not the entire repository suite. Synthetic Windows/UI fixtures establish software behavior only; they do not establish physical UTM safety or Windows-native performance. Keep all pre-existing worktree changes.

## Completed verification

- Implemented all four tasks. Review corrections cover stale deployment invalidation, explicit locator rejection, refreshing manual crops in the review GUI, and deduplicating event-image links while retaining incomplete-evidence warnings.
- Focused Python authoring/API/runtime/recovery suites: **273 passed**. Windows bridge helper suite with system OpenCV: **209 passed**. Focused JavaScript: **54 passed**. Python compilation, JavaScript syntax, bridge distribution/source identity, and diff whitespace checks passed.
- Private 1920×1080 animated-screen fixture, 30 seconds with keyboard/mouse events: **14.97 FPS**, no capture errors or missing event post-links; all saved hashes and 15 locator results verified. Peak RSS was **269 MiB**, CPU **47.5% of one core**. This is Linux Xvfb/Pillow, not native Windows. Recording data was about 116 MB in this deliberately dynamic fixture.
- Sampling that real fixture retained 128 of 600 unique raster frames in eight chunks. Its dense 74 non-move events exceeded the bounded evidence budget; incomplete model event coverage was correctly disclosed. Full evidence stayed on disk.
- Real configured Gemma endpoint: an isolated recorded Escape demonstration produced intent, pre/postconditions and success/failure evidence without modifying the recorded action. A separate live isolated modal restoration selected one Escape, then verified a fresh screenshot; independent DOM checks confirmed the modal closed and no test started.
- Browser fixture verified semantic editing, explicit locator acceptance/rejection, crop → save → review, and deployed read-only state. No physical instrument inputs, production server restarts, or Windows Worker deployment occurred.
- Broad diagnostic runs are not fully green: six unrelated JavaScript cases fail (two existing live-state assertions/environment issues and four missing Three.js dependencies); two legacy equipment routing tests assume model-name selection without an endpoint. They were not changed as part of this feature.

Evidence is under `/tmp/ax4lab_capture_15fps_check`, `/tmp/ax4lab_demo_authoring_smoke`, `/tmp/ax4lab_visual_recovery_smoke`, and `/tmp/ax4lab-demo-*-report.md`. These are local verification artifacts, not packaged production data. Updated source remains on the feature worktree; both Linux and Windows processes must load it before the new behavior is operational.
