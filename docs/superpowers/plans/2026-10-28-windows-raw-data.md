# Windows-local RAW data settings

User-approved scope: the Windows bridge console, not the AX4LAB workspace.
Keep existing execution routes intact; no equipment actuation during validation.

- [x] Add failing tests for persistent folder/template settings, exact identity search,
  invalid templates, missing identities, traversal and stale-file rejection.
- [x] Add local console Raw Data fields and Save / Test Search actions.
- [x] Add authenticated read-only search and explicit fresh-file collection endpoints.
  Keep source CSV intact; copied files use existing artifact download contracts.
- [x] Recognize Qm_Tester Time/Load/Disp/Table with its units row.
- [x] Verify HTTP access rules and browser interactions in isolated local worker.
- [x] Sync standalone distribution, update release, apply to idle Windows worker,
  then verify actual folder and Compression_11_3.csv without moving equipment.

No implicit newest-file selection, no mapping of AX4LAB cycle numbers to UTM test
numbers. Collection requires explicit test/sample/run/specimen identity and an
acquisition start timestamp from the caller. Saving configuration alone does not
change current experiment workflows or mark any experiment complete.

Validation: 237 focused unit tests passed. Desktop and mobile browser checks
passed; the deployed Windows console also found `Compression_11_3.csv` (16,732
bytes) in the configured Qm_Tester RAW directory without page errors. Worker
release 2026.10.28.2 is active. No equipment actions were executed. Full-suite
collection was blocked by the environment's missing `selenium` dependency.
