const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('web/static/lerobot.js', 'utf8');

test('standard defaults use backend resources and preserve user paths', () => {
  const context = {
    setInputValue(el, value) { if (el) el.value = value; },
    setCheckboxValue() {}, syncIsaacLabMimicRgbdInputs() {}, syncExcludeFlaggedEpisodesCheckboxes() {},
  };
  for (const name of source.match(/\b\w+(?:Input|Select)\b/g)) context[name] = { value: '', dataset: {} };
  context.isaacSyntheticIsaacLabPathInput.dataset.resourceDefault = '/new checkout/lab';
  context.isaacSyntheticIsaacSimPythonInput.dataset.resourceDefault = '/configured/python.sh';
  context.isaacSyntheticStagePathInput.dataset.resourceDefault = '/new checkout/runtime/scene.usda';
  context.isaacSyntheticIsaacSimPythonInput.value = '/operator/python.sh';
  vm.createContext(context);
  const start = source.indexOf('function applyIsaacLabStandardDefaults(');
  vm.runInContext(source.slice(start, source.indexOf('\n}', start) + 2), context);
  context.applyIsaacLabStandardDefaults();
  assert.equal(context.isaacSyntheticIsaacLabPathInput.value, '/new checkout/lab');
  assert.equal(context.isaacSyntheticIsaacSimPythonInput.value, '/operator/python.sh');
  assert.equal(context.isaacSyntheticStagePathInput.value, '/new checkout/runtime/scene.usda');
  context.isaacSyntheticStagePathInput.value = '/operator/scene.usda';
  context.applyIsaacLabStandardDefaults();
  assert.equal(context.isaacSyntheticStagePathInput.value, '/operator/scene.usda');
});
