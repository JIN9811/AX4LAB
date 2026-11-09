/**
 * Operator calibration seam. Return the physical platen contact gap in mm,
 * or null to keep the manual model position. No calibration is assumed.
 *
 * measurement: existing serial record (values, units, unit_codes, received_at,
 * valid, checksum_valid, quality, session_id). snapshot: connection/freshness.
 * DISP1/DISP2 are instrument readings, not an absolute platen gap.
 * See docs/gui/qm100t_model.md before supplying your measured mapping here.
 */
export function measurementToGapMm(measurement, snapshot) {
  return null;
}
