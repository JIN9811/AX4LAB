# QM100T model page and serial calibration seam

User scope: add the completed measured UTM model under Device Bridge → Serial
Communication → Qmesys QM100T, prepare the serial data path only, commit and push.
The operator will supply calibration; no displacement offset, sign or scale is
chosen here. Existing model geometry and manual movement must be preserved.

1. Add a QM-only model link and `/serial/modules/qm_indicator/views/model` page. Preserve the selected
   profile in both directions; allow a manual preview without a profile. Reject
   missing profiles and profiles for other instruments. Keep loopback protection.
2. Bundle the existing offline viewer, scene, model downloads, dimensions and
   third-party attribution. Include all deployed files in the positive runtime
   distribution manifest. Do not publish measurement photographs or local paths.
3. Read the existing profile's latest measurement with GET only. Expose the
   unmodified measurement/state to a documented calibration function returning
   `null` by default. Only a finite calibrated gap within the model range and a
   fresh connected sample may update the preview. Leave hardware control intact.
4. Verify routes, no serial I/O on page opening, calibration boundaries and
   distribution coverage. Use the running AX4LAB UI for navigation, manual
   movement and disconnected-state checks; use synthetic input for data checks.
5. Review the scoped changes, commit and push main normally (no history rewrite).

Repository baseline: `3b6debd`; main is clean and 24 commits ahead of origin/main.
The requested normal project push will also publish those existing ancestor
commits. Do not reset, squash or discard them.

Acceptance: no dependency on the standalone port 8876; no automatic port open,
read command, motion command, zeroing or inferred DISP-to-gap conversion.

Modularity refinement after checking `system/modularity.md`, the serial module
README and the common workspace module rule: declare `views` in module.yaml;
keep all model/view/calibration files inside `qm_indicator/views/model`; expose
generic module/view routes and metadata-rendered links. No device-name branches
in the shared shell, no descriptors containing executable code or external URLs,
no provider imports during discovery, and no files escaping the view directory.

Validation: serial suite 52 passed; JavaScript calibration/data-path suite 5
passed; independent module/geometry review found no remaining important defect.
Browser navigation, profile-preserving return, CAS isolation, 0/450 mm movement,
and disconnected/manual state verified on a hardware-disabled local server using
the production router and assets. The running AX4LAB server has reload disabled
and was unresponsive during QA; it was not restarted or used for hardware tests.

Additional runtime-root regression tests: 78 passed, 2 failed. Both failures were
reproduced at unchanged baseline `3b6debd` in an isolated archive:
`test_bootstrap_passes_identical_binding_to_bridge_graph` (missing model role),
`test_registered_equipment_writes_simulated_artifacts_and_runtime_records_to_named_roots`
(missing execution key). No unrelated runtime behavior was changed.

Wheel/sdist exact-content test passed from a clean checkout permission snapshot.
The development checkout's group-write modes otherwise cause an existing wheel
permission assertion failure. Publication size checks require lossless gzip for
the scene and GLB/USD; decoded bytes remain unchanged. Generated textures were
visually reviewed and exact asset hashes are registered for publication.
