# Qm RAW collection connector

Approved scope: one connector using test type/test number/sample number; reuse
the existing authenticated worker, artifact download, cycle identity and analysis
path. No latest-file guessing or automatic conversion of cycle numbers to Qm IDs.

- [x] Test Qm parsing (kgf to N, Disp rather than Table, finite values).
- [x] Implement `collect_qm_raw_csv(payload)` and register the equipment tool.
  Require explicit run/specimen identity and Windows acquisition-start timestamp.
  Match the saved filename rule to the requested test type; retain source bytes.
- [x] Route explicitly selected `qm_auto_save` collection through existing run
  calls. Callers supply explicit Qm settings; saved Skills are not rewritten.
- [x] Verify receipt identity, remote SHA-256, local SHA-256, and parsing before
  returning data_ready. Missing/stale/invalid files never trigger UI fallback.
- [x] Exercise existing artifact download and Analysis parser without actuation.
- [x] Document payload and limitations; preserve other work and running services.

This does not create or select a Qm test, start equipment, infer trial IDs, or
replace experiment completion checks. Test-mode calls must not contact hardware.

Validation: 115 focused tests passed. Actual Windows historical
Compression_11_3.csv was downloaded under diagnostic run
qm_connector_validation_20261028, byte-identical to the earlier supplied file
(16,732 bytes, SHA-256 301a7e156b709ebc90d0943e390982279923ebce696afc5dfb43d3a9b308a2c0).
The existing AnalysisAgent reader returned all 795 points. This was an archived
no-specimen measurement, not evidence of a new experiment's completion.
No running service was restarted. Newly launched clients load the connector;
an already-running AX4LAB process needs its normal restart to register the tool.
Full-suite collection remains blocked by missing `selenium` in
test_windows_pyautogui_demo_assets.py. Review found and fixed invalid Qm rows
being discarded during direct reanalysis; the analysis reader now rejects that
file rather than producing a partial curve, with a regression test.
