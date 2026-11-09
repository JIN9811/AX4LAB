import {readSerialSnapshot, calibratedGapMm} from './serial-bridge.mjs';
import {measurementToGapMm} from './calibration.mjs';

const $=id=>document.getElementById(id);
const profileId=new URLSearchParams(window.location.search).get('profile_id') || '';
const backParams=new URLSearchParams({module_id:document.body.dataset.moduleId});
if (profileId) backParams.set('profile_id',profileId);
$('backSerial').href='/serial?'+backParams;
let timer=null, controller=null, stopped=false;

function render(snapshot) {
  // Public read-only data path for later calibration tools and diagnostics.
  window.qm100tSerial=structuredClone(snapshot);
  window.dispatchEvent(new CustomEvent('qm100t:serial-snapshot',{detail:structuredClone(snapshot)}));
  const fresh=snapshot.state==='connected' && snapshot.stale===false && !!snapshot.measurement;
  document.querySelector('.serial-source').dataset.stale=String(!fresh);
  $('serialSourceState').textContent=snapshot.error ? '수신 상태 확인 실패' :
    snapshot.state==='unbound' ? '프로필 미선택' :
    snapshot.state!=='connected' ? '연결 안 됨' :
    !snapshot.measurement ? '데이터 대기' : fresh ? '수신 중' : '수신 지연';
  for (const [key,id] of [['load','serialLoad'],['disp1','serialDisp1'],['disp2','serialDisp2']]) {
    const value=snapshot.measurement?.values?.[key], unit=snapshot.measurement?.units?.[key];
    $(id).textContent=value==null ? '—' : String(value)+(unit?' '+unit:'');
  }
  $('serialSourceNote').textContent=snapshot.error || (profileId
    ? '기존 통신 세션의 수신값입니다. 캘리브레이션 전에는 수동 간격을 유지합니다.'
    : 'QM100T 통신 화면에서 프로필을 선택하면 수신값을 연결할 수 있습니다.');
  applyCalibration(snapshot);
}

function applyCalibration(snapshot) {
  if (!window.qm100tModel) return;
  try {
    const gap=calibratedGapMm(snapshot, measurementToGapMm, window.qm100tModel.limits);
    $('calibrationState').textContent=gap===null ? '캘리브레이션 대기' : '캘리브레이션 적용';
    if (gap!==null) window.qm100tModel.setGapMm(gap);
  } catch (error) {
    $('calibrationState').textContent='캘리브레이션 오류';
    console.error('QM100T calibration:',error);
  }
}

async function refresh() {
  if (stopped) return;
  if (!document.hidden) {
    controller=new AbortController();
    const timeout=setTimeout(()=>controller?.abort(),5000);
    try {
      const snapshot=await readSerialSnapshot(profileId,{signal:controller.signal});
      if (!stopped) render(snapshot);
    } catch (error) {
      if (!stopped) render({schema:'ax4lab.qm100t_model.serial.v1',profile_id:profileId,
        state:'unavailable',stale:true,age_s:null,measurement:null,error:error.message});
    } finally {clearTimeout(timeout);controller=null;}
  }
  if (!stopped && profileId) timer=setTimeout(refresh,500);
}

window.addEventListener('pagehide',()=>{stopped=true;clearTimeout(timer);controller?.abort();});
window.addEventListener('pageshow',event=>{if(event.persisted){stopped=false;refresh();}});
refresh();
