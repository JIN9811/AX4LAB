/* Shared catalog projection. Adding/removing registrations never controls a server. */
window.AX4LABModelCards = {
  render(rows, statuses, roles, {busy = false, managedEnabled = false} = {}) {
    const host = document.getElementById('registered-model-cards');
    if (!host) return;
    const byModel = new Map((statuses || []).map(item => [item.model, item]));
    const signature = JSON.stringify([rows, statuses, roles, busy, managedEnabled]);
    if (host.dataset.signature === signature) return;
    host.dataset.signature = signature;
    host.replaceChildren();
    for (const item of rows || []) {
      const reference = `endpoint:${item.id}`;
      const status = byModel.get(reference);
      const state = item.managed ? (status?.state || 'unknown') : 'registered';
      const chip = document.createElement('div');
      chip.className = `model-chip ${status?.loaded ? 'is-loaded' : ''}`;
      chip.dataset.model = reference;
      chip.dataset.endpointId = item.id;
      const dot = document.createElement('span'); dot.className = 'chip-dot';
      const copy = document.createElement('div'); copy.className = 'model-copy';
      const label = document.createElement('small');
      const assignments = [];
      if (roles?.orchestrator_endpoint === item.id) assignments.push('Orchestrator');
      if (roles?.worker_endpoint === item.id) assignments.push('Worker / vision');
      label.textContent = assignments.join(' · ') || 'Local endpoint';
      const name = document.createElement('strong'); name.textContent = item.label || item.id;
      const served = document.createElement('small'); served.textContent = item.served_model || '';
      copy.append(label, name, served);
      chip.title = `${item.label || item.id} · ${item.served_model || ''} · ${state} · ${item.base_url}`;
      const actions = document.createElement('div'); actions.className = 'model-actions';
      const statusDot = document.createElement('span'); statusDot.className = `model-load-dot ${state}`;
      actions.append(statusDot);
      if (item.managed) {
        for (const [operation, caption] of [['load','Loading'],['unload','Unloading']]) {
          const button = document.createElement('button');
          button.type = 'button'; button.className = `btn mini model-${operation}-btn`;
          button.dataset.model = reference; button.dataset.endpointId = item.id; button.dataset.modelAction = operation;
          button.textContent = caption;
          button.disabled = busy || !managedEnabled || !status || (operation === 'load'
            ? ['loaded','loading'].includes(state) : !['loaded','loading'].includes(state));
          actions.append(button);
        }
      } else {
        const note = document.createElement('small'); note.textContent = 'Registered'; actions.append(note);
      }
      chip.append(dot, copy, actions); host.append(chip);
    }
    if (!rows?.length) host.textContent = 'No local endpoints registered.';
    const count = document.getElementById('registered-model-count');
    if (count) count.textContent = `${rows?.length || 0} endpoints`;
  }
};
