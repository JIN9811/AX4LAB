const test = require('node:test');
const assert = require('node:assert/strict');
const upload = require('../../web/static/knowledge_source_upload.js');
const fs = require('node:fs');
const vm = require('node:vm');

test('manual upload sends original file bytes to Knowledge without multipart or Equipment execution', async () => {
  const file = new Blob(['manual'], {type: 'text/plain'});
  file.name = 'QM manual.txt';
  const result = await upload.sendFile(file, async (url, options) => {
    assert.equal(url, '/api/knowledge/sources/upload?filename=QM%20manual.txt');
    assert.equal(options.method, 'POST');
    assert.equal(await options.body.text(), 'manual');
    return {ok: true, json: async () => ({ok: true, source_id: 'source-1', scheduled: false})};
  });
  assert.equal(result.source_id, 'source-1');
  assert.equal(upload.uploadMessage(result), 'Uploaded — Knowledge processing is off.');
});

test('invalid files never reach the upload API', async () => {
  let calls = 0;
  for (const file of [{name: 'manual.exe', size: 10}, {name: 'empty.pdf', size: 0},
    {name: 'large.pdf', size: 64 * 1024 * 1024 + 1}]) {
    await assert.rejects(upload.sendFile(file, async () => { calls++; }));
  }
  assert.equal(calls, 0);
});

test('server failures cannot become successful uploads', async () => {
  await assert.rejects(upload.sendFile({name: 'manual.pdf', size: 10}, async () => ({
    ok: false, json: async () => ({detail: 'Rename the new file before uploading.'}),
  })), /Rename the new file/);
  assert.equal(upload.uploadMessage({duplicate: true, scheduled: true}), 'Already uploaded — queued for Knowledge.');
});

test('an uploaded reference reports missing when its source is removed', async () => {
  function element() {
    return {listeners: {}, dataset: {}, children: [], value: '',
      get textContent() { return this.value + this.children.map(child => child.textContent).join(' '); },
      set textContent(value) { this.value = value; this.children = []; },
      addEventListener(name, listener) { this.listeners[name] = listener; },
      append(...children) { this.children.push(...children); },
      replaceChildren(...children) { this.children = children; },
      setAttribute() {}};
  }
  const elements = Object.fromEntries(['file', 'choose', 'drop', 'message', 'files', 'worker']
    .map(name => [`[data-source-${name}]`, element()]));
  const root = {...element(), isConnected: true, querySelector: name => elements[name]};
  let source = {source_id: 'source-1', current: true, status: 'ready', paths: ['manual.txt']};
  let poll;
  const context = {
    document: {hidden: false, querySelectorAll: () => [root], createElement: element, dispatchEvent() {}},
    window: {addEventListener() {}}, CustomEvent: class {},
    setInterval: callback => { poll = callback; return 1; }, clearInterval() {},
    fetch: async (url, options) => ({ok: true, json: async () => options?.method === 'POST'
      ? {ok: true, source_id: 'source-1', filename: 'manual.txt', scheduled: true}
      : {enabled: true, state: 'idle', library: {sources: [source]}}}),
  };
  vm.runInNewContext(fs.readFileSync(require.resolve('../../web/static/knowledge_source_upload.js'), 'utf8'), context);
  const settle = async () => { for (let i = 0; i < 5; i++) await new Promise(setImmediate); };
  await settle();
  elements['[data-source-file]'].files = [{name: 'manual.txt', size: 10}];
  elements['[data-source-file]'].listeners.change();
  await settle();
  assert.equal(elements['[data-source-files]'].children[0].dataset.status, 'ready');
  assert.match(elements['[data-source-files]'].children[0].textContent, /manual.txt/);
  source = {...source, current: false, status: 'missing'};
  poll(); await settle();
  assert.equal(elements['[data-source-files]'].children[0].dataset.status, 'missing');
  assert.match(elements['[data-source-files]'].children[0].textContent, /manual.txt.*missing/);
});
