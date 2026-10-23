# Latest main content integration

## Scope and acceptance

The user approved combining the repository-layout branch, completed portable installation changes, and the original repository's latest main content. Integrate the net change from `ba273ddb0fc2bf8795630d51d93d3932748e0a51` to `3136aa3c66e10c8151472d955914b5390b17ea3d` into destination base `2f29adf9d95c692a15531833f2352f0e7f40925d`.

## Global Constraints

- Only modify `<AX4LAB_CHECKOUT>`, branch `refactor/repository-layout`. The original repository `<SOURCE_CHECKOUT>` is read-only.
- Preserve the `runtime/`, `system/`, and user-facing `docs/` structure and all portable installation behavior. Do not overwrite the destination with the old root layout.
- Integrate the source's final content, not its reverted intermediate documentation redesign.
- Retire the source-deleted paper manuscript package and its dedicated validator/test; preserve the experimental evidence relocated into runtime evidence. Do not erase experiment data, models, calibration, or private state.
- Keep frozen migration identities truthful; record later integration/remaps explicitly rather than rewriting historical identities to imply unchanged bytes.
- No operational server, device, model, service, global launcher, or Rebot workspace actions. No push, remote repository creation, or publication.
- Validation is offline and scoped: source-delta accounting, documentation/link checks, layout/distribution checks, and portability regression checks. Do not rerun the full experiment suite or download large dependencies.

## Task 1: Integrate mapped upstream changes

Read the existing layout manifest and reference rewrite helpers. Produce exact accounting of all 157 net changed source records, including old/new/destination paths and the integration disposition. Apply the source net content with mapped paths and preserve destination-specific portability text/behavior. Resolve both-edited files deliberately (not blanket ours/theirs). Delete the obsolete manuscript/checker/test using scoped tracked-file edits, move evidence into `system/runtime/evidence/`, and preserve the citation file if it remains in source. Update navigation, document/publication inventories and approved hashes only as required by reviewed content. Preserve prior historical baselines and add explicit supersession metadata if required. Do not create a generic syncing framework.

The implementation owns content edits, related manifest fixes, and necessary focused regression tests. The controller owns independent validation harness/ledger and final evidence checks. Follow test-driven development for any new behavior in validation tooling. Use `apply_patch` for authored edits; a reviewed script is allowed for bulk mechanical mapping.

Write a durable compact integration report under `system/maintenance/` with pinned revisions, changed-file accounting, retained portability changes, paper retirement/evidence preservation, and actual validation evidence. Run relevant existing checks without hardware access, self-review, and commit locally. Never claim the full suite passes. Provide the commit and any gaps to the controller.

## Verification and review

The controller will independently compare the pinned source delta and mapped destinations, verify the source repository remains unchanged, run isolated documentation/layout/portability checks, and dispatch task-scoped plus whole-integration review. Fix actionable findings within this scope and retain the branch locally for the user.
