/**
 * Operator calibration seam. Return the physical platen contact gap in mm,
 * or null to keep the manual model position. The reference remains unset.
 *
 * measurement: existing serial record (values, units, unit_codes, received_at,
 * valid, checksum_valid, quality, session_id). snapshot: connection/freshness.
 * User confirmed: use absolute displacement; it increases when moving down.
 * Instrument datum is associated with the upper tensile fixture, not the
 * compression contact gap. Confirm the channel and same-pose reference here.
 */
export const calibration = Object.freeze({
  channel: 'disp1',
  referenceAbsMm: null,
  referenceGapMm: 30,
});

export function gapFromDownwardDisplacementMm(displacementMm, referenceAbsMm, referenceGapMm) {
  if (![displacementMm, referenceAbsMm, referenceGapMm].every(Number.isFinite)
      || referenceAbsMm < 0 || referenceGapMm < 0) return null;
  return referenceGapMm - (Math.abs(displacementMm) - referenceAbsMm);
}

export function measurementToGapMm(measurement, snapshot) {
  if (measurement?.units?.[calibration.channel] !== 'mm') return null;
  return gapFromDownwardDisplacementMm(measurement?.values?.[calibration.channel],
    calibration.referenceAbsMm, calibration.referenceGapMm);
}
