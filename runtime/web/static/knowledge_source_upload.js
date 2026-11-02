(function () {
  'use strict';
  const extensions = new Set(['pdf', 'docx', 'md', 'txt', 'csv', 'json', 'yaml', 'yml', 'html', 'htm']);
  const maxBytes = 64 * 1024 * 1024;

  async function sendFile(file, fetcher = fetch) {
    if (!extensions.has(String(file.name || '').split('.').pop().toLowerCase())) {
      throw new Error('Choose a PDF, DOCX, or supported text document.');
    }
    if (!file.size) throw new Error('The file is empty.');
    if (file.size > maxBytes) throw new Error('Source files must be 64 MiB or smaller.');
    const response = await fetcher(`/api/knowledge/sources/upload?filename=${encodeURIComponent(file.name)}`, {
      method: 'POST', headers: {'Content-Type': 'application/octet-stream'}, body: file,
    });
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Source upload failed.');
    return result;
  }

  function uploadMessage(result) {
    return `${result.duplicate ? 'Already uploaded' : 'Uploaded'} — ${result.scheduled
      ? 'queued for Knowledge.' : 'Knowledge processing is off.'}`;
  }

  function mount(root) {
    const input = root.querySelector('[data-source-file]');
    const choose = root.querySelector('[data-source-choose]');
    const zone = root.querySelector('[data-source-drop]');
    const message = root.querySelector('[data-source-message]');
    const list = root.querySelector('[data-source-files]');
    const worker = root.querySelector('[data-source-worker]');
    let busy = false, refreshing = false;
    const uploads = new Map();

    async function refresh() {
      if (refreshing || document.hidden) return;
      refreshing = true;
      try {
        const response = await fetch('/api/knowledge/sources/status');
        if (!response.ok) throw new Error('Knowledge status unavailable.');
        const status = await response.json();
        worker.textContent = status.enabled ? `Knowledge: ${String(status.state).replaceAll('_', ' ')}`
          : 'Auto processing off';
        const sources = status.library?.sources || [];
        const current = sources.filter(item => item.current);
        const states = new Map(sources.map(item => [item.source_id, item]));
        const rows = uploads.size ? [...uploads.entries()] : current.slice(-6).map(item => [item.source_id, {
          filename: (item.paths || []).join(', ') || item.source_id,
        }]);
        list.replaceChildren(...rows.map(([id, item]) => {
          const row = document.createElement('li');
          const source = states.get(id);
          const state = source?.status || 'uploaded';
          const label = document.createElement('span');
          label.textContent = item.filename;
          const badge = document.createElement('span');
          badge.className = 'knowledge-source-state';
          badge.textContent = `${state === 'ready' ? 'Ready' : state.replaceAll('_', ' ')}${source?.error ? ` · ${source.error}` : ''}`;
          row.append(label, badge);
          row.dataset.status = state;
          return row;
        }));
      } catch (error) {
        worker.textContent = error.message;
      } finally { refreshing = false; }
    }

    async function accept(files) {
      if (busy) { message.textContent = 'Wait for the current upload to finish.'; return; }
      if (!files.length) return;
      busy = true;
      choose.disabled = true;
      root.setAttribute('aria-busy', 'true');
      const results = [];
      try {
        for (const file of files) {
          message.textContent = `Uploading ${file.name}…`;
          try {
            const result = await sendFile(file);
            uploads.set(result.source_id, result);
            results.push(`${file.name}: ${uploadMessage(result)}`);
          } catch (error) { results.push(`${file.name}: ${error.message}`); }
        }
        message.textContent = results.join('\n');
        await refresh();
        document.dispatchEvent(new CustomEvent('knowledge-source-uploaded'));
      } finally {
        busy = false;
        choose.disabled = false;
        input.value = '';
        root.setAttribute('aria-busy', 'false');
      }
    }
    choose.addEventListener('click', () => input.click());
    input.addEventListener('change', () => accept([...input.files]));
    zone.addEventListener('dragover', event => { event.preventDefault(); zone.classList.add('drag-active'); });
    zone.addEventListener('dragleave', event => { if (!zone.contains(event.relatedTarget)) zone.classList.remove('drag-active'); });
    zone.addEventListener('drop', event => {
      event.preventDefault(); zone.classList.remove('drag-active'); accept([...event.dataTransfer.files]);
    });
    refresh();
    const timer = setInterval(() => { if (root.isConnected) refresh(); else clearInterval(timer); }, 5000);
    window.addEventListener('pagehide', () => clearInterval(timer), {once: true});
  }

  if (typeof module !== 'undefined' && module.exports) module.exports = {sendFile, uploadMessage};
  if (typeof document !== 'undefined') document.querySelectorAll('[data-knowledge-upload]').forEach(mount);
}());
