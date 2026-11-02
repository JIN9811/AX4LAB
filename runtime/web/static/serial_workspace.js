/* One shared server session per profile. No WebSerial or automatic connection. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const state = {modules:[], profiles:[], ports:[], module:null, profile:null, status:null, latest:null,
    epoch:0, cursor:0, session:null, rawEvents:[], activity:[], logState:null, dirty:false, ticking:false, busy:false, tickDone:Promise.resolve()};
  const el = (tag,text,cls) => {const e=document.createElement(tag);if(text!=null)e.textContent=text;if(cls)e.className=cls;return e;};
  function message(text,error=false){$('serial-message').textContent=text;$('serial-message').hidden=!text;$('serial-message').dataset.error=String(error);}
  async function api(path,method='GET',body){
    const response=await fetch('/api/serial'+path,{method,headers:body===undefined?{}:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body),cache:'no-store'});
    const data=await response.json();
    if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:(data.detail?.message||'Request failed'));
    return data;
  }
  const path = () => '/profiles/'+state.profile.id;
  function dirty(){state.dirty=true;$('save-state').textContent='Unsaved';}
  function controls(){
    const connected=state.status?.state==='connected', has=!!state.profile;
    ['connect','save-settings','delete-profile'].forEach(id=>$(id).disabled=!has||state.busy);
    $('connect').disabled ||= connected || state.dirty || !state.module;
    $('save-settings').disabled ||= !state.module;
    $('delete-profile').disabled ||= connected;
    $('disconnect').disabled=!has||state.busy||!state.status||state.status.state==='disconnected';
    ['read-once','toggle-polling','toggle-recording'].forEach(id=>$(id).disabled=!connected||state.busy);
    $('read-once').hidden=!state.module?.capabilities?.includes('read');
    $('toggle-polling').hidden=!state.module?.capabilities?.includes('polling');
    $('new-profile').disabled=!state.module||state.busy;
    $('back-catalog').disabled=state.busy;
    $('profile-select').disabled=state.busy;
  }
  async function action(fn){
    if(state.busy)return;state.busy=true;controls();message('');
    try{await state.tickDone;await fn();}catch(e){message(e.message,true);}
    finally{state.busy=false;controls();await tick();}
  }
  function catalog(){
    const host=$('serial-module-list');host.replaceChildren();
    for(const m of state.modules){
      const button=el('button',null,'serial-module');button.type='button';
      const img=el('img');img.src='/api/serial/modules/'+encodeURIComponent(m.id)+'/icon';img.alt='';
      const text=el('span');text.append(el('strong',m.label));
      button.append(img,text);button.onclick=()=>chooseModule(m.id);host.append(button);
    }
    for(const p of state.profiles.filter(p=>!p.module_available)){
      const button=el('button',p.name+' · Module unavailable','serial-module');
      button.onclick=()=>chooseModule(p.module_id,p.id);host.append(button);
    }
    if(!host.childElementCount)host.append(el('p','No installed device modules.'));
  }
  function chooseModule(id,profileId){
    if(state.dirty&&!confirm('Discard unsaved settings?'))return;
    state.module=state.modules.find(m=>m.id===id)||null;
    const profiles=state.profiles.filter(p=>p.module_id===id),select=$('profile-select');
    select.replaceChildren();
    if(!profiles.length)select.append(new Option('Create a profile',''));
    profiles.forEach(p=>select.append(new Option(p.name,p.id)));
    $('device-title').textContent=state.module?.label||'Module unavailable';
    $('serial-catalog').hidden=true;$('serial-device').hidden=false;
    select.value=profiles.find(p=>p.id===profileId)?.id||profiles[0]?.id||'';
    chooseProfile(select.value);
  }
  function chooseProfile(id){
    state.epoch++;state.profile=state.profiles.find(p=>p.id===id)||null;
    state.status=null;state.latest=null;state.cursor=0;state.session=null;state.rawEvents=[];state.activity=[];state.logState=null;state.dirty=false;
    $('profile-name').value=state.profile?.name||'';$('save-state').textContent='';
    $('serial-events').textContent='';$('event-gap').textContent='';$('serial-activity').textContent='';$('raw-events').open=false;
    const params=new URLSearchParams();if(state.module)params.set('module_id',state.module.id);if(id)params.set('profile_id',id);
    history.replaceState(null,'','/serial?'+params);
    fields();renderStatus({state:'disconnected',receive_state:'no_data'},false);values(null);controls();tick();
  }
  function fields(){
    const host=$('serial-fields');host.replaceChildren();
    const settings=state.profile?.settings||state.module?.defaults||{};
    for(const f of state.module?.fields||[]){
      const label=el('label',f.label),input=el(f.type==='number'?'input':'select');
      input.id='setting-'+f.key;input.dataset.key=f.key;input.disabled=!state.profile;
      if(f.type==='number'){input.type='number';input.min=f.min;input.max=f.max;input.step=f.step||'any';input.required=true;}
      else if(f.type==='select')f.options.forEach(x=>input.append(new Option(String(x),String(x))));
      label.append(input);host.append(label);
      if(f.type==='port')portOptions(input,settings[f.key]);else input.value=settings[f.key];
      input.oninput=()=>{dirty();controls();};
    }
  }
  function portOptions(input,value){
    input.replaceChildren(new Option('Select port',''));
    for(const p of state.ports){
      const option=new Option(p.port+' · '+p.description+(p.availability==='owned'?' · In use':''),p.port);
      option.disabled=!p.available&&p.owner_profile_id!==state.profile?.id;input.append(option);
    }
    if(value&&!state.ports.some(p=>p.port===value))input.append(new Option(value+' · Unavailable',value));
    input.value=value||'';
  }
  async function ports(){
    state.ports=(await api('/ports')).ports;
    const input=$('setting-port');if(input)portOptions(input,input.value);
  }
  function settings(){
    const result={};
    for(const f of state.module.fields){const value=$('setting-'+f.key).value;
      result[f.key]=f.type==='number'?Number(value):(f.type==='select'?f.options.find(x=>String(x)===value):value);
    }
    return result;
  }
  function activity(text,at=Date.now()){
    if(state.activity.at(-1)?.text===text)return;
    state.activity.push({text,at});state.activity=state.activity.slice(-6);
    $('serial-activity').textContent=state.activity.map(x=>new Date(x.at).toLocaleTimeString()+' · '+x.text).join('\n');
  }
  function observeStatus(s){
    const previous=state.logState,recordingId=s.recording?.id||null;
    if(!previous||previous.state!==s.state||previous.error!==s.error){
      activity(s.error?'Error · '+s.error:({connected:'Connected',disconnected:'Disconnected',error:'Connection error'}[s.state]||s.state));
    }
    if(previous&&!!previous.polling!==!!s.polling)activity(s.polling?'Polling started':'Polling stopped');
    if(previous&&previous.recordingId!==recordingId)activity(recordingId?'Recording started':'Recording stopped');
    if(s.recording?.error&&s.recording.error!==previous?.recordingError)activity('Recording error · '+s.recording.error);
    state.logState={state:s.state,error:s.error,polling:s.polling,recordingId,recordingError:s.recording?.error};
  }
  function renderRaw(){
    if(!$('raw-events').open)return;
    const log=$('serial-events'),bottom=log.scrollTop+log.clientHeight>=log.scrollHeight-20;
    log.textContent=state.rawEvents.map(event=>{
      const detail=event.hex||event.message||JSON.stringify(event.values);
      return new Date(event.received_at*1000).toLocaleTimeString()+' '+event.kind.toUpperCase()+' '+detail;
    }).join('\n');
    if(bottom)log.scrollTop=log.scrollHeight;
  }
  function continuousReception(s=state.status){
    // Request/reply modules can poll; passive modules already stream on Connect.
    return !!s?.polling || !state.module?.capabilities?.includes('polling');
  }
  function renderReceiveState(){
    const s=state.status,receive=$('receive-state'),m=state.latest?.measurement;
    if(!s)return;
    if(s.state!=='connected'){
      receive.textContent=s.state==='error'?'Connection error':'Disconnected';
      receive.dataset.state=s.state;
    }else if(!continuousReception(s)){
      receive.textContent=m?'Measured · '+new Date(m.received_at*1000).toLocaleTimeString():'No measurement';
      receive.dataset.state=m?'measured':'no_data';
    }else{
      receive.textContent=s.receive_state.replaceAll('_',' ')+(s.age_s==null?'':' · '+s.age_s.toFixed(1)+' s');
      receive.dataset.state=s.receive_state;
    }
  }
  function renderStatus(s,observe=true){
    if(observe)observeStatus(s);
    state.status=s;const connection=$('connection-state');
    connection.textContent=s.state;connection.dataset.state=s.state;
    renderReceiveState();
    $('reconnect-note').hidden=!s.needs_reconnect;
    $('serial-counters').textContent=`RX ${s.rx_bytes||0} B · TX ${s.tx_bytes||0} B · Parse errors ${s.parse_errors||0}`;
    $('toggle-polling').textContent=s.polling?'Stop polling':'Start polling';
    $('toggle-recording').textContent=s.recording?'Stop recording':'Start recording';
    $('recording-state').textContent=s.recording?(s.recording.error?'Recording error: '+s.recording.error:'Recording · '+s.recording.id.slice(0,8)):(s.error||'');
    controls();
  }
  function values(data){
    state.latest=data;renderReceiveState();
    const host=$('serial-values');host.replaceChildren();
    const m=data?.measurement;
    for(const channel of state.module?.channels||[]){
      const card=el('div',null,'serial-value');
      card.dataset.stale=String(!!data?.stale&&(continuousReception()||state.status?.state!=='connected'));
      const value=m?.values?.[channel.key],unit=m?.units?.[channel.key]||'';
      card.append(el('span',channel.label),el('strong',value==null?'—':value+' '+unit));
      card.append(el('small',value==null?(m?channel.unavailable_label||'Not available':'No measurement'):(m?.quality||'')));host.append(card);
    }
  }
  async function tick(){
    if(!state.profile||state.ticking||state.busy||document.hidden)return;
    const epoch=state.epoch,base=path();state.ticking=true;
    let done;state.tickDone=new Promise(resolve=>{done=resolve;});
    try{
      const [status,latest,initialEvents]=await Promise.all([api(base+'/status'),api(base+'/latest'),api(base+'/events?after='+state.cursor)]);
      if(epoch!==state.epoch)return;
      const events=state.session&&initialEvents.session_id!==state.session?await api(base+'/events?after=0'):initialEvents;
      if(epoch!==state.epoch)return;
      renderStatus(status);values(latest);
      if(events.session_id!==state.session){state.rawEvents=[];state.cursor=0;state.session=events.session_id;}
      // A new server session may have a smaller cursor than the previous one.
      if(events.cursor<state.cursor){state.cursor=0;return;}
      state.cursor=events.cursor;
      if(events.gap)$('event-gap').textContent='Recent data only';
      for(const event of events.events){
        if(event.kind==='request_error')activity(event.message||'Request failed',event.received_at*1000);
      }
      state.rawEvents=state.rawEvents.concat(events.events).slice(-100);renderRaw();
    }catch(e){if(epoch===state.epoch)message(e.message,true);}
    finally{state.ticking=false;done();}
  }
  async function recordings(){
    const data=await api('/recordings'),host=$('serial-recordings');host.replaceChildren();
    for(const r of data.recordings){
      const row=el('div',null,'serial-recording');row.append(el('span',`${r.profile?.name||r.id} · ${new Date(r.started_at*1000).toLocaleString()} · ${r.complete?'Complete':r.ended_at?'Incomplete':'Recording / unclosed'}`));
      for(const [name,label] of [['measurements.csv','CSV'],['measurements.jsonl','JSONL'],['raw.bin','Raw'],['chunks.jsonl','RX timing'],['tx.jsonl','TX'],['manifest.json','Metadata']]){
        const a=el('a',label);a.href='/api/serial/recordings/'+encodeURIComponent(r.id)+'/'+name;row.append(a);
      }
      host.append(row);
    }
    if(!data.recordings.length)host.append(el('p','No recordings','serial-empty'));
  }
  async function load(){
    const [m,p]=await Promise.all([api('/modules'),api('/profiles')]);state.modules=m.modules;state.profiles=p.profiles;
    catalog();if(m.errors.length)message(m.errors.map(x=>x.module+': '+x.message).join(' · '),true);
  }
  $('profile-name').oninput=()=>{if(state.profile){dirty();controls();}};
  $('profile-select').onchange=()=>{if(state.dirty&&!confirm('Discard unsaved settings?')){$('profile-select').value=state.profile?.id||'';return;}chooseProfile($('profile-select').value);};
  $('new-profile').onclick=()=>action(async()=>{
    if(state.dirty&&!confirm('Discard unsaved settings?'))return;
    const p=await api('/profiles','POST',{module_id:state.module.id,name:$('profile-name').value.trim()||state.module.label});
    state.dirty=false;await load();chooseModule(p.module_id,p.id);message('Profile created.');
  });
  $('delete-profile').onclick=()=>action(async()=>{
    if(!confirm('Delete profile “'+state.profile.name+'”? Recordings are kept.'))return;
    const id=state.profile.module_id;await api(path(),'DELETE',{revision:state.profile.revision,confirmed:true});state.dirty=false;await load();chooseModule(id);message('Profile deleted.');
  });
  $('serial-settings').onsubmit=e=>{e.preventDefault();action(async()=>{
    const p=await api(path(),'PUT',{revision:state.profile.revision,name:$('profile-name').value.trim(),settings:settings()});
    state.profile=p;state.dirty=false;state.profiles=state.profiles.map(x=>x.id===p.id?p:x);
    $('profile-select').selectedOptions[0].textContent=p.name;$('save-state').textContent='Saved';message('Settings saved.');
  });};
  $('connect').onclick=()=>action(async()=>{renderStatus(await api(path()+'/connect','POST'));await ports();});
  $('disconnect').onclick=()=>action(async()=>{renderStatus(await api(path()+'/disconnect','POST'));await ports();await recordings();});
  $('read-once').onclick=()=>action(async()=>{await api(path()+'/read','POST',{});message('Measurement received.');});
  $('toggle-polling').onclick=()=>action(async()=>{renderStatus(await api(path()+'/polling','POST',{enabled:!state.status.polling,interval_s:state.status.active_settings?.interval_s||1}));});
  $('toggle-recording').onclick=()=>action(async()=>{await api(path()+'/recording','POST',{enabled:!state.status.recording});await recordings();});
  $('refresh-ports').onclick=()=>action(ports);
  $('refresh-recordings').onclick=()=>action(recordings);
  $('refresh-modules').onclick=()=>action(async()=>{
    if(state.dirty&&!confirm('Discard unsaved settings?'))return;
    const moduleId=state.profile?.module_id||state.module?.id,profileId=state.profile?.id;
    await api('/modules/refresh','POST');state.dirty=false;await load();if(!$('serial-device').hidden)chooseModule(moduleId,profileId);
  });
  $('back-catalog').onclick=()=>{if(state.dirty&&!confirm('Discard unsaved settings?'))return;state.epoch++;state.profile=null;state.dirty=false;$('serial-device').hidden=true;$('serial-catalog').hidden=false;history.replaceState(null,'','/serial');catalog();};
  $('clear-events').onclick=()=>{state.rawEvents=[];state.activity=[];$('serial-events').textContent='';$('serial-activity').textContent='';};
  $('raw-events').ontoggle=renderRaw;
  window.addEventListener('beforeunload',e=>{if(state.dirty){e.preventDefault();e.returnValue='';}});
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)tick();});
  (async()=>{
    try{await load();await recordings();await ports();const p=new URLSearchParams(location.search),profileId=p.get('profile_id');const moduleId=p.get('module_id')||state.profiles.find(x=>x.id===profileId)?.module_id;if(moduleId)chooseModule(moduleId,profileId);}
    catch(e){message(e.message,true);}
    setInterval(tick,200);
  })();
})();
