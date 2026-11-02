const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../../web/static/lerobot.js'), 'utf8');
function load(name, context) {
  const start = source.indexOf(`function ${name}(`);
  vm.runInContext(source.slice(start, source.indexOf('\n}', start) + 2), context);
}

test('native controls choose the selected profile session, not the latest other robot', () => {
  const context = vm.createContext({profileSelect: {value: 'rebot_b601_rs'},
    basePayload: x => x, isActiveSession: x => x.status === 'RUNNING',
    lastSessionByWorkflow: {record: 'quest'}, lastSessions: [
      {session_id: 'dual', profile_id: 'rebot_b601_rs', workflow: 'record', status: 'RUNNING', native_rebot: true},
      {session_id: 'quest', profile_id: 'rebot_b601_rs_quest', workflow: 'record', status: 'RUNNING', native_rebot: true},
    ]});
  load('sessionPayload', context);
  assert.equal(context.sessionPayload('record').session_id, 'dual');
  context.profileSelect.value = 'robotis_omx_ai';
  assert.equal(context.sessionPayload('record').session_id, '');
});

test('native editor survives refresh and OMX returns to its original controls', () => {
  const elements = {};
  const $ = id => elements[id] ||= {value: '', dataset: {}, disabled: false,
    classList: {toggle(name, value) { this[name] = value; }}, closest() { return null; }};
  const context = vm.createContext({$, document: {querySelectorAll: () => []}, fpsInput: $('fps')});
  load('renderRebotSettings', context);
  const data = {rebot_native_settings: {rebot_b601_rs: {python: '/native/python', config: {fps: 30}}}};
  context.renderRebotSettings(data, {profile_id: 'rebot_b601_rs'});
  assert.equal($('lerobot-rebot-python').value, '/native/python');
  assert.equal($('fps').value, '30');
  assert.equal($('training-card').classList['rebot-hidden'], true);
  $('lerobot-rebot-config').value = 'operator edit';
  context.renderRebotSettings(data, {profile_id: 'rebot_b601_rs'});
  assert.equal($('lerobot-rebot-config').value, 'operator edit');
  context.renderRebotSettings(data, {profile_id: 'robotis_omx_ai'});
  assert.equal($('device-port-setup').classList.hidden, false);
  assert.equal($('training-card').classList['rebot-hidden'], false);
  assert.equal($('btn-train-start').disabled, false);
});
