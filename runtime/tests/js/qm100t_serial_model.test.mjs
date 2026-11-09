import test from 'node:test';
import assert from 'node:assert/strict';
import {readSerialSnapshot, calibratedGapMm} from '../../device_bridges/serial_communication/modules/qm_indicator/views/model/serial-bridge.mjs';
import {measurementToGapMm, gapFromDownwardDisplacementMm} from '../../device_bridges/serial_communication/modules/qm_indicator/views/model/calibration.mjs';

const sample = {
  state:'connected', stale:false, age_s:0.1,
  measurement:{values:{load:12, disp1:-218.21, disp2:0}, units:{load:'kgf',disp1:'mm'},
    received_at:123, valid:true, checksum_valid:true, quality:'provisional'},
};
const limits = {min:0, max:740};

test('reads only the selected existing session and preserves units and displacement', async () => {
  const requests=[];
  const snapshot=await readSerialSnapshot('profile/1', {fetch:async(url,options)=>{
    requests.push({url,options});return {ok:true,json:async()=>sample};
  }});
  assert.equal(requests.length,1);
  assert.equal(requests[0].url,'/api/serial/profiles/profile%2F1/latest');
  assert.equal(requests[0].options.method,'GET');
  assert.equal(snapshot.profile_id,'profile/1');
  assert.deepEqual(snapshot.measurement,sample.measurement);
  assert.equal(calibratedGapMm(snapshot,measurementToGapMm,limits),null);
});

test('no selected profile performs no network access', async () => {
  const snapshot=await readSerialSnapshot('',{fetch:()=>{throw new Error('unexpected request');}});
  assert.equal(snapshot.state,'unbound');
  assert.equal(snapshot.measurement,null);
});

test('HTTP failures never masquerade as fresh data', async () => {
  await assert.rejects(readSerialSnapshot('missing',{fetch:async()=>({ok:false,status:404})}),/404/);
});

test('only fresh valid samples reach operator calibration', () => {
  for(const patch of [{state:'disconnected'},{stale:true},{measurement:null},
    {measurement:{...sample.measurement,valid:false}},
    {measurement:{...sample.measurement,checksum_valid:false}}]){
    assert.equal(calibratedGapMm({...sample,...patch},()=>{throw new Error('must not calibrate');},limits),null);
  }
  assert.equal(calibratedGapMm(sample,()=>0,limits),0);
  assert.equal(calibratedGapMm(sample,()=>740,limits),740);
  for(const value of [null,undefined,NaN,Infinity,-1,741,'110']){
    assert.equal(calibratedGapMm(sample,()=>value,limits),null);
  }
});

test('operator function receives the original measurement and snapshot without a built-in transform', () => {
  assert.equal(calibratedGapMm(sample,(measurement,snapshot)=>{
    assert.equal(measurement,sample.measurement);
    assert.equal(snapshot,sample);
    return 123.4;
  },limits),123.4);
});

test('absolute displacement increases downward and decreases the compression gap', () => {
  for (const sign of [-1, 1]) {
    assert.equal(gapFromDownwardDisplacementMm(sign * 677.8, 677.8, 30), 30);
    assert.equal(gapFromDownwardDisplacementMm(sign * 687.8, 677.8, 30), 20);
    assert.equal(gapFromDownwardDisplacementMm(sign * 667.8, 677.8, 30), 40);
    assert.equal(gapFromDownwardDisplacementMm(sign * 707.8, 677.8, 30), 0);
  }
  // Beyond contact must be rejected by the existing range gate, never clamped.
  assert.equal(gapFromDownwardDisplacementMm(708.8, 677.8, 30), -1);
  for (const value of [null, undefined, '677.8', NaN, Infinity]) {
    assert.equal(gapFromDownwardDisplacementMm(value, 677.8, 30), null);
    assert.equal(gapFromDownwardDisplacementMm(677.8, value, 30), null);
    assert.equal(gapFromDownwardDisplacementMm(677.8, 677.8, value), null);
  }
  assert.equal(gapFromDownwardDisplacementMm(677.8, -677.8, 30), null);
  assert.equal(gapFromDownwardDisplacementMm(677.8, 677.8, -30), null);
});
