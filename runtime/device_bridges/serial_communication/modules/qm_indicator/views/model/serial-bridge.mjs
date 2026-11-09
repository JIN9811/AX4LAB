/** Read the existing server session; never open a port or request a device read. */
export async function readSerialSnapshot(profileId, {fetch:fetcher=globalThis.fetch, signal}={}) {
  if (!profileId) return {schema:'ax4lab.qm100t_model.serial.v1', profile_id:null,
    state:'unbound', stale:true, age_s:null, measurement:null};
  const response=await fetcher('/api/serial/profiles/'+encodeURIComponent(profileId)+'/latest',
    {method:'GET', cache:'no-store', signal});
  if (!response.ok) throw new Error('시리얼 수신 상태를 읽지 못했습니다 ('+response.status+')');
  const data=await response.json();
  return {schema:'ax4lab.qm100t_model.serial.v1', profile_id:profileId,
    state:data.state, stale:data.stale, age_s:data.age_s, measurement:data.measurement};
}

/** Unknown/stale/invalid samples cannot drive the preview; 0 is a valid gap. */
export function calibratedGapMm(snapshot, calibrate, limits) {
  const measurement=snapshot?.measurement;
  if (snapshot?.state!=='connected' || snapshot.stale!==false || !measurement
      || measurement.valid!==true || measurement.checksum_valid!==true) return null;
  const mm=calibrate(measurement, snapshot);
  return Number.isFinite(mm) && mm>=limits.min && mm<=limits.max ? mm : null;
}
