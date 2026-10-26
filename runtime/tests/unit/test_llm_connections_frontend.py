"""Exercise the connection editor's real event handlers without a browser/server."""
from pathlib import Path
import shutil
import subprocess

import pytest


SOURCE = Path(__file__).resolve().parents[2] / 'web/static/llm_connections.js'


@pytest.mark.skipif(not shutil.which('node'), reason='Node.js is needed for JS behavior tests')
@pytest.mark.parametrize('scenario', ['local_roles', 'save_roles', 'probe_worker', 'endpoint_add', 'endpoint_edit', 'endpoint_remove', 'lifecycle_identity', 'key_binding', 'preserve_draft', 'save_locks_inputs', 'legacy_missing_endpoints', 'legacy_missing_worker', 'legacy_recovery'])
def test_connection_editor_without_discovery_controls(scenario):
    script = r"""
const vm = require('node:vm'), fs = require('node:fs'), assert = require('node:assert/strict');
const nodes = new Map(), requests = [];
function node() {
  return {value:'', textContent:'', hidden:false, disabled:false, children:[], handlers:{},
    classList:{toggle(){}}, open:false, checked:false, showModal(){this.open=true}, close(){this.open=false}, append(...items){this.children.push(...items)},
    replaceChildren(...items){this.children=items}, dataset:{}, setAttribute(){}, removeAttribute(){},
    closest(){return this}, focus(){}, checkValidity(){return true}, reportValidity(){return true},
    addEventListener(event,fn){this.handlers[event]=fn}};
}
const removed=new Set(['catalog-url','catalog-token','catalog-discover','catalog-discovered','catalog-models','catalog-add']);
function el(id) {if(removed.has(id)) return null; if(!nodes.has(id)) nodes.set(id,node());return nodes.get(id)}
el('connections-view').value='current';el('connection-test-role').value='worker';
const settings={endpoints:[
  {id:'office',label:'Office GPU',provider:'vllm',model:'shared-model',base_url:'http://office.test/v1',management_id:'gpu-a',capabilities:{text:true,vision:true},has_access_token:true},
  {id:'lab',label:'Lab GPU',provider:'vllm',model:'shared-model',base_url:'http://lab.test/v1',management_id:'gpu-b',capabilities:{text:true,vision:false},has_access_token:false},
  {id:'spare',label:'Spare GPU',provider:'vllm',model:'shared-model',base_url:'http://spare.test/v1',management_id:'',capabilities:{text:true,vision:false},has_access_token:false},
  {id:'cloud',label:'Cloud API',provider:'openai',model:'cloud-model',base_url:'https://cloud.test/v1',management_id:'',capabilities:{text:true,vision:true},has_access_token:false}],
  profiles:{openai:{orchestrator_endpoint:'cloud',worker_endpoint:'cloud',orchestrator_fallback:'',worker_fallback:'',base_url:'https://cloud.test/v1'},
    vllm:{orchestrator_endpoint:'office',worker_endpoint:'lab',orchestrator_fallback:'',worker_fallback:''}},
  management_targets:[{id:'gpu-a',label:'First GPU'},{id:'gpu-b',label:'Second GPU'}],
  active_backend:'vllm',busy:false,api_key:{has_key:true,enabled:true,endpoint_matches:true},
  runtime:{backend:{name:'vllm',proxy_url:'http://office.test/v1'}},
  resolved_endpoints:{worker:'http://lab.test/v1',orchestrator:'http://office.test/v1'}};
let blockedResolve;
const compatible=JSON.parse(JSON.stringify(settings));
if(process.argv[2]==='legacy_missing_endpoints'||process.argv[2]==='legacy_recovery')delete settings.endpoints;
if(process.argv[2]==='legacy_missing_worker')delete settings.profiles.vllm.worker_endpoint;
vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),{
  document:{hidden:false,getElementById:el,createElement:node,querySelectorAll:()=>[...nodes.values()]},
  window:{AX4LABModelCards:{render(){}},setTimeout(){}},
  fetch:async(url,options)=>{
    requests.push({url,...options});
    if(process.argv[2]==='save_locks_inputs'&&options.method==='PUT')await new Promise(resolve=>{blockedResolve=resolve});
    const data=url.endsWith('/models')?{ok:true,enabled:true,models:[]}:
      url.endsWith('/test')?{ok:true,model:'shared-model',reply:'Confirmed',elapsed_s:0.1}:settings;
    return {ok:true,json:async()=>data};
  },
});
const settle=()=>new Promise(resolve=>setImmediate(resolve));
const event=()=>({preventDefault(){}});
const clickRow=(action,id)=>el('catalog-registered').handlers.click({target:{closest:()=>({disabled:false,dataset:{endpointAction:action,endpointId:id}})}});
(async()=>{
 await settle();
 if(process.argv[2].startsWith('legacy_')) {
   assert.match(el('connections-status').textContent,/server.*(?:update|restart)|(?:update|restart).*server/i);
   for(const id of ['connection-save','connection-test','endpoint-add','api-key-load-btn','api-key-unload-btn','api-key-open-btn'])assert.equal(el(id).disabled,true,id);
   assert.equal(el('connections-refresh').disabled,false);
   el('connections-view').value='vllm';el('connections-view').handlers.change();
   el('endpoint-add').handlers.click();assert.equal(el('endpoint-dialog').open,false);
   clickRow('remove','spare');
   el('connections-form').handlers.submit(event());el('connection-test').handlers.click();
   el('endpoint-form').handlers.submit(event());
   el('api-key-input').value='not-a-real-key';el('api-key-form').handlers.submit(event());
   el('api-key-load-btn').handlers.click();el('api-key-unload-btn').handlers.click();
   el('registered-model-cards').handlers.click({target:{closest:()=>({disabled:false,dataset:{modelAction:'load',endpointId:'lab'}})}});
   await settle();assert.ok(requests.every(r=>r.method==='GET'));
   if(process.argv[2]==='legacy_recovery')Object.assign(settings,compatible);
   el('connections-refresh').handlers.click();await settle();
   if(process.argv[2]==='legacy_recovery') {
     assert.equal(el('connection-save').disabled,false);
     el('connections-view').value='vllm';el('connections-view').handlers.change();
     assert.equal(el('connection-worker').value,'lab');
   } else assert.match(el('connections-status').textContent,/server.*(?:update|restart)|(?:update|restart).*server/i);
   return;
 }
 el('connections-view').value='vllm'; el('connections-view').handlers.change();
 if(process.argv[2]==='local_roles') {
   assert.equal(el('connections-editor').hidden,false);
   assert.equal(el('connection-orchestrator').value,'office');
   assert.equal(el('connection-worker').value,'lab');
   assert.equal(el('catalog-registered').children.length,3);
   assert.deepEqual(el('connection-worker').children.map(item=>item.value),['','office','lab','spare']);
   assert.ok(el('connection-worker').children[1].textContent.includes('Office GPU'));
   assert.ok(el('connection-worker').children[2].textContent.includes('Lab GPU'));
   assert.ok(requests.every(r=>r.method==='GET' &&
     ['/api/runtime/llm-connections','/api/runtime/models'].includes(r.url)));
 } else if(['save_roles','save_locks_inputs'].includes(process.argv[2])) {
   el('connection-orchestrator').value='lab';
   el('connections-form').handlers.submit({preventDefault(){}}); await settle();
   const req=requests.find(r=>r.method==='PUT');
   assert.equal(JSON.parse(req.body).provider,'vllm');
   assert.deepEqual(JSON.parse(req.body).connection,{orchestrator_endpoint:'lab',worker_endpoint:'lab',orchestrator_fallback:'',worker_fallback:''});
   if(process.argv[2]==='save_locks_inputs') {
     assert.equal(el('connection-orchestrator').disabled,true);assert.equal(el('connections-view').disabled,true);
     blockedResolve();await settle();
   }
 } else if(process.argv[2]==='probe_worker') {
   el('connection-test').handlers.click();await settle();
   const body=JSON.parse(requests.find(r=>r.url.endsWith('/test')).body);
   assert.equal(body.role,'worker');assert.equal(body.connection.worker_endpoint,'lab');
   assert.equal(requests.filter(r=>r.method!=='GET').length,1);
 } else if(process.argv[2]==='endpoint_add') {
   el('endpoint-add').handlers.click();
   el('endpoint-id').value='remote';el('endpoint-label').value='Remote GPU';
   el('endpoint-url').value='http://remote.test/v1';el('endpoint-model').value='shared-model';
   el('endpoint-management').value='';el('endpoint-vision').checked=true;el('endpoint-token').value='test-token';
   el('endpoint-form').handlers.submit(event());await settle();
   const req=requests.find(r=>r.method==='PUT');
   assert.equal(req.url,'/api/runtime/llm-connections/endpoints/remote');
   assert.deepEqual(JSON.parse(req.body),{label:'Remote GPU',provider:'vllm',base_url:'http://remote.test/v1',model:'shared-model',management_id:'',capabilities:{text:true,vision:true},access_token:'test-token'});
 } else if(process.argv[2]==='endpoint_edit') {
   clickRow('edit','office');
   assert.equal(el('endpoint-id').value,'office');assert.equal(el('endpoint-id').readOnly,true);assert.equal(el('endpoint-token').value,'');
   el('endpoint-url').value='http://moved.test/v1';el('endpoint-form').handlers.submit(event());await settle();
   const req=requests.find(r=>r.method==='PUT');assert.equal(req.url,'/api/runtime/llm-connections/endpoints/office');
   assert.equal(JSON.parse(req.body).access_token,null);
 } else if(process.argv[2]==='endpoint_remove') {
   clickRow('remove','spare');await settle();
   assert.equal(requests.find(r=>r.method==='DELETE').url,'/api/runtime/llm-connections/endpoints/spare');
   assert.ok(requests.every(r=>!r.url.includes('/models/load')&&!r.url.includes('/models/unload')));
 } else if(process.argv[2]==='lifecycle_identity') {
   el('registered-model-cards').handlers.click({target:{closest:()=>({disabled:false,dataset:{modelAction:'load',endpointId:'lab',model:'endpoint:lab'}})}});
   await settle();assert.deepEqual(JSON.parse(requests.find(r=>r.url.endsWith('/models/load')).body),{endpoint_id:'lab'});
 } else if(process.argv[2]==='key_binding') {
   el('api-key-open-btn').handlers.click();settings.profiles.openai.base_url='https://changed.test/v1';
   el('api-key-input').value='new-key';el('api-key-form').handlers.submit(event());await settle();
   assert.equal(JSON.parse(requests.find(r=>r.url==='/api/runtime/api-key').body).expected_base_url,'https://cloud.test/v1');
 } else if(process.argv[2]==='preserve_draft') {
   el('connection-orchestrator').value='spare';el('connections-form').handlers.input();
   el('connections-view').value='openai';el('connections-view').handlers.change();
   el('connections-view').value='vllm';el('connections-view').handlers.change();
   assert.equal(el('connection-orchestrator').value,'spare');
 }
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    result = subprocess.run(['node', '-e', script, str(SOURCE), scenario], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(not shutil.which('node'), reason='Node.js is needed for JS behavior tests')
def test_shared_cards_keep_same_model_endpoints_distinct():
    script = r"""
const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
function node(){return {dataset:{},children:[],textContent:'',append(...items){this.children.push(...items)},replaceChildren(){this.children=[]}}}
const host=node(),count=node(),window={};
vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),{window,document:{getElementById:id=>id==='registered-model-cards'?host:count,createElement:node}});
window.AX4LABModelCards.render([
 {id:'office',model:'endpoint:office',served_model:'shared-model',label:'Office GPU',base_url:'http://office.test/v1',managed:true},
 {id:'lab',model:'endpoint:lab',served_model:'shared-model',label:'Lab GPU',base_url:'http://lab.test/v1',managed:true},
], [{model:'endpoint:office',state:'loaded',loaded:true},{model:'endpoint:lab',state:'unloaded',loaded:false}],
 {orchestrator_endpoint:'office',worker_endpoint:'lab'}, {managedEnabled:true});
assert.equal(host.children.length,2);
assert.equal(host.children[0].children[1].children[1].textContent,'Office GPU');
assert.ok(host.children[0].title.includes('shared-model'));
assert.ok(host.children[0].children[1].children[0].textContent.includes('Orchestrator'));
assert.ok(host.children[1].children[1].children[0].textContent.includes('Worker'));
const officeActions=host.children[0].children[2].children,labActions=host.children[1].children[2].children;
assert.equal(officeActions[1].dataset.endpointId,'office');assert.equal(officeActions[1].disabled,true);
assert.equal(labActions[1].dataset.endpointId,'lab');assert.equal(labActions[1].disabled,false);
"""
    source = SOURCE.with_name('llm_model_cards.js')
    result = subprocess.run(['node', '-e', script, str(source)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(not shutil.which('node'), reason='Node.js is needed for JS behavior tests')
def test_dashboard_model_action_uses_endpoint_id():
    script = r"""
const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
const source=fs.readFileSync(process.argv[1],'utf8'),requests=[];
const start=source.indexOf('async function setModelServingState('),end=source.indexOf('\nfunction renderApiKeyStatus(',start);
vm.runInNewContext(source.slice(start,end)+"\nsetModelServingState('lab','load',null)",{
  postJson:async(url,body)=>{requests.push({url,body});return {ok:true}},refreshModelStatuses:async()=>{},refreshState:async()=>{},
});
setImmediate(()=>{assert.equal(requests[0].url,'/api/runtime/models/load');assert.equal(JSON.stringify(requests[0].body),JSON.stringify({endpoint_id:'lab'}))});
"""
    result = subprocess.run(['node', '-e', script, str(SOURCE.with_name('app.js'))], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(not shutil.which('node'), reason='Node.js is needed for JS behavior tests')
@pytest.mark.parametrize('filename,function_name,next_function', [
    ('module_management.js', 'createModule', 'createDraftModuleTemplate'),
    ('runtime_ide.js', 'createModuleFromDesigner', 'loadHandlers'),
])
def test_module_designer_leaves_transform_model_to_configured_route(filename, function_name, next_function):
    script = r"""
const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
const source=fs.readFileSync(process.argv[1],'utf8'),requests=[];
const start=source.indexOf(`async function ${process.argv[2]}(`),end=source.indexOf(`\nasync function ${process.argv[3]}(`,start);
const input=value=>({value}),file={name:'sample.py',text:async()=> 'def run(): return 1'};
vm.runInNewContext(source.slice(start,end)+`\n${process.argv[2]}()`,{
  designerPythonFileInput:{files:[file]},designerModuleIdInput:input('sample'),designerLabelInput:input('Sample'),
  designerCategoryInput:input('custom'),designerHandlerSelect:input('runtime.step_complete'),designerLlmRoleInput:input('worker'),
  designerNotesInput:input(''),designerStatus:{},designerCreateBtn:{},
  fillDesignerFromFile(){},slugify:value=>value,setDesignerStatus(){},
  requestJson:async(url,options)=>{requests.push({url,body:JSON.parse(options.body)});return new Promise(()=>{})},
});
setImmediate(()=>{
  assert.equal(requests.length,1);assert.equal(requests[0].url,'/api/modules');
  assert.equal(requests[0].body.transform_with_llm,true);assert.equal(requests[0].body.llm_role,'worker');
  assert.equal(Object.hasOwn(requests[0].body,'transform_model'),false,'GUI must not override the configured module_designer route');
});
"""
    result = subprocess.run(
        ['node', '-e', script, str(SOURCE.with_name(filename)), function_name, next_function],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(not shutil.which('node'), reason='Node.js is needed for JS behavior tests')
@pytest.mark.parametrize('filename,function_name,next_function', [
    ('module_management.js', 'renderConfigSummary', 'dryRunPhaseLabel'),
    ('runtime_ide.js', 'updateModuleSummary', 'logicalRouteRecords'),
])
@pytest.mark.parametrize('backend', ['', 'openai', 'vllm', 'ollama', 'nemoclaw', 'mock'])
def test_module_backend_selector_preserves_unsupported_saved_override(filename, function_name, next_function, backend):
    script = r"""
const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
const source=fs.readFileSync(process.argv[1],'utf8'),backend=process.argv[4];
const start=source.indexOf(`function ${process.argv[2]}(`),end=source.indexOf(`\nfunction ${process.argv[3]}(`,start);
const payload={module:{id:'sample',llm:{backend}}},output={innerHTML:'',querySelectorAll:()=>[]};
vm.runInNewContext(source.slice(start,end)+`\n${process.argv[2]}(${process.argv[2]==='updateModuleSummary'?'payload.module':'payload'})`,{
 payload,configSummaryOutput:output,moduleSummary:output,document:{getElementById:()=>null},
 normalizedModulePayload:value=>value,moduleLlm:module=>module.llm,modulePrompt:()=>({}),moduleSupervisorPolicy:()=>({}),
 modulePreflightMarkup:()=>'',runtimeNodeIconMarkup:()=>'',moduleIconName:()=>'',handlerOptions:()=>'',renderModuleToolPicker:()=>'',
 moduleTextLines:()=>'',jsonTextareaValue:JSON.stringify,escapeHtml:value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
});
const select=output.innerHTML.match(/<select id="(?:mm-config|ide-module)-llm-backend"[^>]*>([\s\S]*?)<\/select>/)[1];
const options=[...select.matchAll(/<option value="([^"]*)"([^>]*)>([^<]*)<\/option>/g)].map(([,value,attributes,label])=>({value,attributes,label}));
assert.deepEqual(options.filter(option=>!option.attributes.includes('disabled')).map(option=>option.value),['','openai','vllm']);
const selected=options.filter(option=>option.attributes.includes('selected'));
assert.equal(selected.length,1);assert.equal(selected[0].value,backend);
if(!['','openai','vllm'].includes(backend)) {
 assert.match(selected[0].label,/unsupported/i);assert.ok(selected[0].attributes.includes('disabled'));
}
"""
    result = subprocess.run(
        ['node', '-e', script, str(SOURCE.with_name(filename)), function_name, next_function, backend],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_runtime_ide_run_backend_choices_match_supported_routes():
    from html.parser import HTMLParser

    class BackendChoices(HTMLParser):
        selected = False

        def __init__(self):
            super().__init__()
            self.values = []

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == 'select':
                self.selected = attrs.get('id') == 'ide-run-backend'
            elif tag == 'option' and self.selected:
                self.values.append(attrs.get('value'))

        def handle_endtag(self, tag):
            if tag == 'select':
                self.selected = False

    choices = BackendChoices()
    choices.feed((SOURCE.parents[1] / 'templates/runtime_ide.html').read_text())
    assert choices.values == ['', 'openai', 'vllm']
