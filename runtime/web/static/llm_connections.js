/* Separate connection editor. No run-control or experiment-start requests. */
(() => {
  "use strict";
  const el = id => document.getElementById(id);
  let settings = null;
  let models = {models: []};
  let pending = false;
  let schemaCompatible = false;
  const updateNotice = "Server update/restart required: this page needs endpoint-based connection support. Update or restart AX4LAB when safe, then click Load Current Mode. Editing, testing, and model/API controls are disabled until the server is compatible.";
  let keyEndpoint = "";
  let editingEndpoint = null;
  const drafts = {};
  const view = () => el("connections-view").value;
  const fields = {
    orchestrator_endpoint: "connection-orchestrator", worker_endpoint: "connection-worker",
    orchestrator_fallback: "connection-orchestrator-fallback", worker_fallback: "connection-worker-fallback",
  };

  async function request(url, method = "GET", body) {
    if (method !== 'GET' && !schemaCompatible) throw new Error(updateNotice);
    const response = await fetch(url, {method, headers: {"Content-Type": "application/json"},
      ...(body === undefined ? {} : {body: JSON.stringify(body)})});
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Request failed (${response.status}).`);
    return data;
  }

  function notice(message, error = false) {
    el("connections-status").textContent = message;
    el("connections-status").className = error ? "is-error" : "";
  }

  function readForm() {
    return Object.fromEntries(Object.entries(fields).map(([key, id]) => [key, el(id).value]));
  }

  function mutationsAllowed() {
    if (schemaCompatible) return true;
    notice(updateNotice, true);
    return false;
  }

  function supportsEndpointSettings(configuration) {
    return Array.isArray(configuration?.endpoints) &&
      configuration.endpoints.every(item => item && typeof item.id === 'string' && item.id &&
        ['openai', 'vllm'].includes(item.provider)) &&
      ['openai', 'vllm'].every(provider =>
        typeof configuration.profiles?.[provider]?.orchestrator_endpoint === 'string' &&
        typeof configuration.profiles?.[provider]?.worker_endpoint === 'string');
  }

  function fillOptions(select, rows, selected, optional = false) {
    select.replaceChildren();
    const empty = document.createElement('option');
    empty.value = ''; empty.textContent = optional ? 'None' : 'Select an endpoint';
    select.append(empty);
    for (const item of rows) {
      const option = document.createElement('option');
      option.value = item.id;
      option.textContent = `${item.label || item.id} · ${item.model} · ${item.base_url}`;
      select.append(option);
    }
    if (selected && !rows.some(item => item.id === selected)) {
      const missing = document.createElement('option');
      missing.value = selected; missing.textContent = `Unavailable endpoint: ${selected}`;
      missing.disabled = true; select.append(missing);
    }
    select.value = selected || '';
  }

  function renderKey() {
    const key = settings?.api_key || {};
    const enabled = Boolean(key.enabled);
    const mismatch = key.endpoint_matches === false;
    el("api-key-status-text").textContent = key.has_key ? "Registered" : "Not registered";
    const detail = mismatch ? "Saved key belongs to another endpoint. Enter a key for this address."
      : enabled ? "API primary · enabled" : "API disabled · local route retained";
    el("api-key-detail").textContent = detail;
    el("connection-key-note").textContent = detail;
    if (!el("api-key-dialog").open) el("api-key-dialog-status").textContent = mismatch ? detail : "Saved keys are never displayed. A new key is bound to the saved API endpoint.";
    el("api-key-dot").className = `model-load-dot ${enabled ? "loaded" : "unloaded"}`;
    el("api-key-chip").classList.toggle("is-loaded", enabled);
    el("api-key-load-btn").disabled = pending || !key.has_key || enabled || mismatch;
    el("api-key-unload-btn").disabled = pending || !enabled;
  }

  function renderCurrent() {
    if (!schemaCompatible) {
      el('connections-route').textContent = 'Server update required';
      el('backend-status-label').textContent = 'Server update required';
      el('nemoclaw-status-label').textContent = 'Controls unavailable';
      el('api-key-status-text').textContent = 'Unavailable';
      el('api-key-detail').textContent = 'Refresh after the server update.';
      el('connections-endpoints').replaceChildren();
      window.AX4LABModelCards.render([], [], {}, {busy:true, managedEnabled:false});
      setEditorPending(pending);
      notice(updateNotice, true);
      return;
    }
    const runtime = settings.runtime || {};
    const active = settings.active_backend;
    const api = settings.api_key?.enabled;
    el("connections-route").textContent = `${api ? "API primary" : `Local · ${active}`} · ${settings.busy ? "Busy" : "Idle"}`;
    el("backend-status-label").textContent = runtime.backend?.label || active;
    el("backend-status-detail").textContent = `Endpoint ${runtime.backend?.proxy_url || "unavailable"}`;
    el("nemoclaw-status-label").textContent = settings.busy ? "Working" : "Ready";
    el("nemoclaw-status-detail").textContent = "Current Mode reads the existing runtime. No connection is changed by opening this view.";
    const localRows = (settings.endpoints || []).filter(item => item.provider === 'vllm').map(item => ({
      ...item, served_model:item.model, model:`endpoint:${item.id}`, managed:Boolean(item.management_id),
    }));
    window.AX4LABModelCards.render(localRows, models.models || [],
      settings.profiles.vllm, {busy:pending || settings.busy, managedEnabled:Boolean(models.ok && models.enabled)});
    renderKey();
    el("connection-save").disabled = pending || settings.busy;
    el("connection-test").disabled = pending || settings.busy;
    const endpoints = el("connections-endpoints");
    endpoints.replaceChildren();
    for (const [label, address] of [
      ["API", settings.profiles.openai.base_url],
      ["Local · Orchestrator", settings.resolved_endpoints?.orchestrator],
      ["Local · Worker", settings.resolved_endpoints?.worker],
    ]) {
      const term = document.createElement("dt"), value = document.createElement("dd");
      term.textContent = label; value.textContent = address || settings.endpoint_notice || "Unavailable";
      endpoints.append(term, value);
    }
  }

  async function refresh() {
    const [configuration, status] = await Promise.all([
      request("/api/runtime/llm-connections"), request("/api/runtime/models"),
    ]);
    settings = configuration; models = status;
    schemaCompatible = supportsEndpointSettings(configuration);
    setEditorPending(pending);
    renderCurrent();
    if (schemaCompatible && settings.load_error) notice(settings.load_error, true);
  }

  function showView() {
    if (!schemaCompatible) el('connections-view').value = 'current';
    const current = view() === "current";
    el("connections-current").hidden = !current;
    el("connections-editor").hidden = current;
    el("connection-result").hidden = true;
    if (current || !schemaCompatible) return;
    const profile = drafts[view()] || settings.profiles[view()] || {};
    const rows = (settings.endpoints || []).filter(item => item.provider === view());
    for (const [key, id] of Object.entries(fields)) fillOptions(el(id), rows, profile[key], key.endsWith('_fallback'));
    el("connections-editor-title").textContent = view() === "openai" ? "API Connection" : "Local LLM Connection";
    el("connection-api-key-row").hidden = view() !== 'openai';
    renderCatalog();
  }

  function renderCatalog() {
    if (!schemaCompatible) return;
    const host = el('catalog-registered');
    host.replaceChildren();
    const assigned = new Set(Object.values(settings?.profiles || {}).flatMap(profile => Object.keys(fields).map(key => profile[key])));
    for (const item of (settings?.endpoints || []).filter(endpoint => endpoint.provider === view())) {
      const row = document.createElement('div'); row.className = 'catalog-row';
      const text = document.createElement('div'), name = document.createElement('strong'), address = document.createElement('small');
      name.textContent = item.label || item.id;
      address.textContent = `${item.model} · ${item.base_url} · ${item.id}${item.management_id ? ' · Managed' : ''}`;
      text.append(name, address);
      const actions = document.createElement('div'); actions.className = 'catalog-actions';
      for (const [action, caption] of [['edit','Edit'],['remove','Remove']]) {
        const button = document.createElement('button'); button.type = 'button'; button.className = 'btn mini';
        button.dataset.endpointAction = action; button.dataset.endpointId = item.id; button.textContent = caption;
        button.disabled = pending || settings.busy || (action === 'remove' && assigned.has(item.id));
        if (action === 'remove' && assigned.has(item.id)) button.title = 'Save replacement role assignments before removing this endpoint.';
        actions.append(button);
      }
      row.append(text, actions); host.append(row);
    }
    if (!host.children.length) host.textContent = 'No endpoints registered. Add an endpoint to assign it to a role.';
    el('endpoint-add').disabled = pending || settings.busy;
  }

  async function action(message, fn, {readOnly = false} = {}) {
    if (pending) return;
    if (!readOnly && !mutationsAllowed()) return;
    pending = true;
    setEditorPending(true);
    notice(message);
    renderCurrent();
    try { await fn(); }
    catch (error) {
      notice(error.message, true);
      if (el("api-key-dialog").open) el("api-key-dialog-status").textContent = error.message;
      if (el("endpoint-dialog").open) el("endpoint-status").textContent = error.message;
    }
    finally { pending = false; setEditorPending(false); renderCurrent(); if (view() !== 'current') renderCatalog(); }
  }

  function setEditorPending(disabled) {
    for (const control of document.querySelectorAll("#connections-form input, #connections-form select, #connections-form button, #api-key-form input, #api-key-form button, #endpoint-form input, #endpoint-form select, #endpoint-form button, [data-endpoint-action]")) control.disabled = disabled || !schemaCompatible;
    for (const id of ['connection-save', 'connection-test', 'api-key-open-btn', 'connections-api-key', 'api-key-load-btn', 'api-key-unload-btn']) el(id).disabled = disabled || !schemaCompatible;
    el("connections-view").disabled = disabled;
    el("connections-refresh").disabled = disabled;
    el("endpoint-add").disabled = disabled || !schemaCompatible || settings?.busy;
  }

  el("connections-view").addEventListener("change", showView);
  el("connections-refresh").addEventListener("click", () => action("Loading current settings…", async () => {
    await refresh(); el("connections-view").value = "current"; showView();
    if (schemaCompatible) notice("Current Mode loaded.");
  }, {readOnly:true}));
  el("connections-form").addEventListener("input", () => {
    drafts[view()] = readForm();
  });
  el("connections-form").addEventListener("submit", event => {
    event.preventDefault();
    const provider = view(), connection = readForm();
    action("Saving connection…", async () => {
      const data = await request("/api/runtime/llm-connections", "PUT", {provider, connection});
      delete drafts[provider];
      await refresh(); showView(); notice(data.message);
    });
  });
  el("connection-test").addEventListener("click", () => {
    if (!el("connections-form").reportValidity()) return;
    const provider = view(), connection = readForm(), role = el("connection-test-role").value;
    action("Testing this endpoint only…", async () => {
      const result = el("connection-result"); result.hidden = false; result.textContent = "Waiting for a reply (up to 60 seconds)…";
      try {
        const data = await request("/api/runtime/llm-connections/test", "POST", {provider, connection, role});
        result.className = `connections-result ${data.ok ? "is-success" : "is-error"}`;
        result.textContent = `${data.ok ? "Connected" : "Connection failed"} · ${data.model} · ${data.elapsed_s}s\n${data.reply || data.message}`;
        notice(data.ok ? "Connection verified. Settings were not changed." : data.message, !data.ok);
      } catch (error) { result.textContent = error.message; result.className = "connections-result is-error"; throw error; }
    });
  });
  el('registered-model-cards').addEventListener('click', event => {
    const button = event.target.closest('button[data-model-action]');
    if (!button || button.disabled) return;
    action("Updating model serving state…", async () => {
      const operation = button.dataset.modelAction;
      const data = await request(`/api/runtime/models/${operation}`, "POST", {endpoint_id: button.dataset.endpointId});
      if (!data.ok) throw new Error(data.message || "Model action failed.");
      await refresh(); notice(data.message);
    });
  });

  el('catalog-registered').addEventListener('click', event => {
    const button = event.target.closest('button[data-endpoint-action]');
    if (!button || button.disabled || pending || !mutationsAllowed()) return;
    const item = settings.endpoints.find(endpoint => endpoint.id === button.dataset.endpointId);
    if (!item) return;
    if (button.dataset.endpointAction === 'edit') { openEndpointDialog(item); return; }
    if (button.dataset.endpointAction !== 'remove') return;
    drafts[view()] = readForm();
    action('Removing registration…', async () => {
      await request(`/api/runtime/llm-connections/endpoints/${encodeURIComponent(item.id)}`, 'DELETE');
      await refresh(); showView(); notice('Endpoint unregistered. Its server was not stopped.');
    });
  });

  function openEndpointDialog(item = null) {
    if (!mutationsAllowed() || pending || settings.busy) return;
    editingEndpoint = item;
    drafts[view()] = readForm();
    el('endpoint-dialog-title').textContent = item ? 'Edit Endpoint' : 'Add Endpoint';
    el('endpoint-id').value = item?.id || ''; el('endpoint-id').readOnly = Boolean(item);
    el('endpoint-label').value = item?.label || '';
    el('endpoint-url').value = item?.base_url || '';
    el('endpoint-model').value = item?.model || '';
    el('endpoint-token').value = '';
    el('endpoint-vision').checked = Boolean(item?.capabilities?.vision);
    const management = el('endpoint-management'); management.replaceChildren();
    const none = document.createElement('option'); none.value = ''; none.textContent = 'External server · no load/unload control'; management.append(none);
    const targets = settings.management_targets || [];
    for (const target of targets) {
      const option = document.createElement('option'); option.value = target.id; option.textContent = target.label || target.id;
      management.append(option);
    }
    if (item?.management_id && !targets.some(target => target.id === item.management_id)) {
      const missing = document.createElement('option'); missing.value = item.management_id;
      missing.textContent = `Unavailable target: ${item.management_id}`; management.append(missing);
    }
    management.value = item?.management_id || '';
    el('endpoint-management-field').hidden = view() !== 'vllm';
    el('endpoint-status').textContent = item?.has_access_token
      ? 'A token is stored. Leave blank to keep it for this same address; changing the address clears it.'
      : 'Enter the served model ID manually. Saving registers a connection; it does not start its server.';
    el('endpoint-dialog').showModal();
  }
  el('endpoint-add').addEventListener('click', () => openEndpointDialog());
  el('endpoint-close').addEventListener('click', () => el('endpoint-dialog').close());
  el('endpoint-form').addEventListener('submit', event => {
    event.preventDefault();
    if (!mutationsAllowed()) return;
    if (!el('endpoint-form').reportValidity()) return;
    const id = el('endpoint-id').value.trim(), provider = editingEndpoint?.provider || view();
    if (!editingEndpoint && settings.endpoints.some(item => item.id === id)) {
      el('endpoint-status').textContent = 'This endpoint ID already exists. Choose a different ID.'; return;
    }
    const endpoint = {
      label:el('endpoint-label').value.trim(), provider, base_url:el('endpoint-url').value.trim(),
      model:el('endpoint-model').value.trim(), management_id:provider === 'vllm' ? el('endpoint-management').value : '',
      capabilities:{text:true,vision:el('endpoint-vision').checked}, access_token:el('endpoint-token').value || null,
    };
    action('Saving endpoint registration…', async () => {
      await request(`/api/runtime/llm-connections/endpoints/${encodeURIComponent(id)}`, 'PUT', endpoint);
      el('endpoint-token').value = ''; el('endpoint-dialog').close();
      await refresh(); showView(); notice('Endpoint saved. No model or experiment was started.');
    });
  });

  function openKeyDialog() {
    if (!mutationsAllowed() || pending) return;
    if (view() === 'openai' && Object.entries(readForm()).some(([key, value]) => value !== (settings.profiles.openai[key] || ''))) {
      notice("Save API role assignments first, then enter their key.", true); return;
    }
    el("api-key-input").value = "";
    keyEndpoint = settings.profiles.openai.base_url;
    el("api-key-dialog-status").textContent = `Save a key for ${keyEndpoint}. Saved keys are never displayed.`;
    el("api-key-enable-input").checked = Boolean(settings.api_key?.enabled || !settings.api_key?.endpoint_matches);
    el("api-key-dialog").showModal();
  }
  el("api-key-open-btn").addEventListener("click", openKeyDialog);
  el("connections-api-key").addEventListener("click", openKeyDialog);
  el("api-key-close-btn").addEventListener("click", () => el("api-key-dialog").close());
  el("api-key-form").addEventListener("submit", event => {
    event.preventDefault();
    const api_key = el("api-key-input").value.trim();
    if (!api_key) { el("api-key-dialog-status").textContent = "Enter an API key."; return; }
    action("Saving API key…", async () => {
      await request("/api/runtime/api-key", "POST", {api_key, enabled: el("api-key-enable-input").checked, expected_base_url: keyEndpoint});
      el("api-key-input").value = ""; el("api-key-dialog").close();
      await refresh(); notice("API key saved for this endpoint.");
    });
  });
  for (const operation of ["load", "unload"]) {
    el(`api-key-${operation}-btn`).addEventListener("click", () => action("Updating API routing…", async () => {
      const data = await request(`/api/runtime/api-key/${operation}`, "POST", {});
      if (!data.ok) throw new Error(data.message || "API action failed.");
      await refresh(); notice(operation === "load" ? "API routing enabled." : "API routing disabled.");
    }));
  }
  async function poll() {
    if (!document.hidden && !pending && view() === "current") {
      try { await refresh(); } catch (error) { notice(error.message, true); }
    }
    window.setTimeout(poll, 5000);
  }
  refresh().then(() => { showView(); poll(); }).catch(error => { notice(error.message, true); poll(); });
})();
