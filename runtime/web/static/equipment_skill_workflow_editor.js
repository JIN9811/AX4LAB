function parseComputerUsePolicy(text) {
  const value = String(text ?? "").trim();
  if (!value) return null;
  try {
    const parsed = JSON.parse(value);
    if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") throw new Error();
    return parsed;
  } catch (_error) {
    throw new Error("Computer-use policy must be a valid JSON object.");
  }
}

function serializeComputerUsePolicy(policy) {
  return policy && typeof policy === "object" && !Array.isArray(policy)
    ? JSON.stringify(policy, null, 2)
    : "";
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { parseComputerUsePolicy, serializeComputerUsePolicy };
}

(function initializeEquipmentSkillWorkflowEditor() {
  "use strict";

  if (typeof document === "undefined") return;
  const root = document.getElementById("skill-workflow-editor");
  const model = window.EquipmentSkillWorkflowModel;
  if (!root || !model) return;

  const skillId = root.dataset.skillId;
  const version = root.dataset.skillVersion;
  const workerId = new URLSearchParams(window.location.search).get("worker") || "";
  const apiBase = `/api/equipment/skills/${encodeURIComponent(skillId)}/${encodeURIComponent(version)}/workflow`;
  const elements = {
    lifecycle: document.getElementById("workflow-editor-lifecycle"),
    dirty: document.getElementById("workflow-editor-dirty"),
    duration: document.getElementById("workflow-editor-duration"),
    check: document.getElementById("workflow-editor-check"),
    save: document.getElementById("workflow-editor-save"),
    close: document.getElementById("workflow-editor-close"),
    split: document.getElementById("workflow-editor-split"),
    add: document.getElementById("workflow-editor-add-step"),
    addAction: document.getElementById("workflow-editor-add-action"),
    list: document.getElementById("workflow-editor-step-list"),
    count: document.getElementById("workflow-editor-step-count"),
    status: document.getElementById("workflow-editor-status"),
    worker: document.getElementById("workflow-editor-worker"),
    computerUsePolicy: document.getElementById("workflow-editor-computer-use-policy"),
    applyComputerUsePolicy: document.getElementById("workflow-editor-apply-computer-use-policy"),
    cropDialog: document.getElementById("workflow-crop-dialog"),
    cropStage: document.getElementById("workflow-crop-stage"),
    cropSource: document.getElementById("workflow-crop-source"),
    cropBox: document.getElementById("workflow-crop-box"),
    cropPreview: document.getElementById("workflow-crop-preview"),
    cropCoordinates: document.getElementById("workflow-crop-coordinates"),
    cropReset: document.getElementById("workflow-crop-reset"),
    cropApply: document.getElementById("workflow-crop-apply"),
    cropCancel: document.getElementById("workflow-crop-cancel"),
  };
  const state = {
    workflow: null,
    workflowSha256: "",
    annotations: { steps: [] },
    reviewDrafts: {},
    editable: false,
    dirty: false,
    expandedStepId: "",
    selectedStepId: "",
    issues: [],
    busy: false,
    crop: null,
  };

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (character) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[character]));
  }

  async function apiJson(url, options = {}) {
    const scoped = new URL(url, window.location.origin);
    const profile = new URLSearchParams(window.location.search).get("profile_id");
    if (profile) scoped.searchParams.set("profile_id", profile);
    const response = await fetch(scoped.pathname + scoped.search, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    let payload = {};
    try { payload = await response.json(); } catch (_error) { payload = {}; }
    if (!response.ok) {
      const detail = payload.detail || payload;
      const error = new Error(String(detail.message || detail.failure_code || `HTTP ${response.status}`));
      error.status = response.status;
      error.payload = detail;
      throw error;
    }
    return payload;
  }

  function setStatus(message, tone = "idle") {
    elements.status.textContent = message;
    elements.status.dataset.tone = tone;
  }

  function setBusy(busy) {
    state.busy = busy;
    if (elements.split) elements.split.disabled = busy || !state.workflow;
    [elements.check, elements.save, elements.add, elements.addAction, elements.computerUsePolicy, elements.applyComputerUsePolicy].forEach((button) => {
      if (button) button.disabled = busy || (!state.editable && button !== elements.check);
    });
    if (busy) elements.list.querySelectorAll("input, select, textarea, button").forEach((control) => { control.disabled = true; });
  }

  function hasUnsavedChanges() {
    return state.dirty || Object.keys(state.reviewDrafts).length > 0;
  }

  const splitDialog = document.getElementById("workflow-split-dialog");
  const splitContent = document.getElementById("workflow-split-content");
  const splitStatus = document.getElementById("workflow-split-status");
  const splitGenerate = document.getElementById("workflow-split-generate");
  const splitConfirm = document.getElementById("workflow-split-confirm");
  const splitClose = document.getElementById("workflow-split-close");
  const splitBase = apiBase.replace(/\/workflow$/, "/split-proposal");
  let splitState = { proposal: null, result: null, stale: false };

  function renderSplit() {
    const { proposal, result, stale } = splitState;
    splitContent.replaceChildren();
    for (const [index, part] of (proposal?.parts || []).entries()) {
      const article = document.createElement("article");
      article.className = "skill-split-part";
      const heading = document.createElement("strong");
      heading.textContent = part.name;
      const steps = document.createElement("small");
      steps.textContent = ` ${index + 1} · ${part.step_ids.length} steps · ${part.step_ids[0]} → ${part.step_ids.at(-1)}`;
      article.append(heading, steps);
      for (const text of [part.purpose, part.preconditions?.length ? `Before: ${part.preconditions.join("; ")}` : "", part.postconditions?.length ? `After: ${part.postconditions.join("; ")}` : ""]) {
        if (!text) continue;
        const paragraph = document.createElement("p"); paragraph.textContent = text; article.append(paragraph);
      }
      splitContent.append(article);
    }
    for (const branch of proposal?.branches || []) {
      const row = document.createElement("div"); row.className = "skill-split-branch";
      row.textContent = `After part ${branch.after_part}: ${branch.condition} — Needs demonstration. ${branch.description}`;
      splitContent.append(row);
    }
    for (const child of result?.children || []) {
      const link = document.createElement("a");
      const url = new URL(`/equipment/skills/${encodeURIComponent(child.skill_id)}/${encodeURIComponent(child.version)}/workflow-editor`, window.location.origin);
      const profile = new URLSearchParams(window.location.search).get("profile_id");
      if (profile) url.searchParams.set("profile_id", profile);
      link.href = url.pathname + url.search; link.textContent = child.name; link.target = "_blank"; link.rel = "noopener";
      splitContent.append(link);
    }
    splitConfirm.disabled = state.busy || !proposal?.split_recommended || Boolean(result) || stale;
  }

  async function splitRequest(action) {
    setBusy(true); splitGenerate.disabled = true; splitConfirm.disabled = true;
    splitStatus.dataset.tone = "idle";
    try { await action(); }
    catch (error) { splitStatus.textContent = error.message; splitStatus.dataset.tone = "error"; }
    finally { setBusy(false); splitGenerate.disabled = false; renderEditor(); renderSplit(); }
  }

  elements.split?.addEventListener("click", () => {
    if (state.busy) return;
    if (hasUnsavedChanges()) { setStatus("Save workflow and review changes before splitting.", "warning"); return; }
    splitDialog.showModal();
    splitRequest(async () => {
      splitStatus.textContent = "Loading proposal…";
      splitState = await apiJson(`${splitBase}/latest`);
      splitStatus.textContent = splitState.result ? "Drafts created. Review each skill before deployment." : splitState.stale ? "Source changed. Generate a new proposal." : splitState.proposal ? "Review the proposed boundaries before creating drafts." : "Generate a proposal from this saved demonstration.";
    });
  });
  splitGenerate?.addEventListener("click", () => splitRequest(async () => {
    if (hasUnsavedChanges()) throw new Error("Save workflow and review changes before splitting.");
    splitStatus.textContent = "Analyzing boundaries with the selected model…";
    const payload = await apiJson(splitBase, {method: "POST", body: JSON.stringify({expected_workflow_sha256: state.workflowSha256})});
    splitState = {proposal: payload.proposal, result: null, stale: false};
    splitStatus.textContent = payload.proposal.split_recommended ? "Review boundaries. Branch suggestions need another demonstration." : "One coherent task — no split recommended.";
  }));
  splitConfirm?.addEventListener("click", () => {
    if (state.busy || !splitState.proposal?.split_recommended || splitState.result || splitState.stale) return;
    if (!window.confirm(`Create ${splitState.proposal.parts.length} separate skill drafts? The original and active flow will stay unchanged.`)) return;
    splitRequest(async () => {
      splitStatus.textContent = "Creating drafts…";
      const payload = await apiJson(`${splitBase}/${encodeURIComponent(splitState.proposal.proposal_id)}/confirm`, {method: "POST", body: JSON.stringify({confirm_create: true})});
      splitState.result = payload.result;
      splitStatus.textContent = "Drafts created. Review each skill before deployment.";
    });
  });
  splitClose?.addEventListener("click", () => splitDialog.close());

  function annotationFor(stepId) {
    return (state.annotations.steps || []).find((annotation) => annotation.step_id === stepId);
  }

  const reviewFields = [
    ["intent", "Intent"], ["target_semantics", "Target meaning"],
    ["preconditions", "Preconditions", true], ["postconditions", "Postconditions", true],
    ["success_evidence", "Success evidence", true], ["failure_evidence", "Failure evidence", true],
    ["ambiguity", "Ambiguity / uncertainty"],
  ];

  function reviewMarkup(step) {
    const annotation = annotationFor(step.step_id);
    if (!annotation) return "";
    const draft = state.reviewDrafts[step.step_id] || {};
    const disabled = !state.editable || state.busy ? "disabled" : "";
    const pendingLocator = annotation.locator_status === "proposed" && annotation.locator;
    const fields = reviewFields.map(([key, label, list]) => {
      const value = draft[key] ?? (list ? (annotation[key] || []).join("\n") : annotation[key] || "");
      return `<label>${label}${list ? " <small>(one item per line)</small>" : ""}<textarea class="text-input" rows="2" data-step-id="${escapeHtml(step.step_id)}" data-review-field="${key}" ${list ? "" : 'maxlength="1000"'} ${disabled}>${escapeHtml(value)}</textarea></label>`;
    }).join("");
    const reasons = (annotation.review_reasons || []).map((reason) => escapeHtml(String(reason).replaceAll("_", " "))).join(" · ");
    const variables = (annotation.proposed_variables || []).map((variable) => `<li><strong>${escapeHtml(variable.name)}</strong> <span>${escapeHtml(variable.type || "string")}</span><br>Recorded: <code>${escapeHtml(variable.recorded_value)}</code> · Field: ${escapeHtml(variable.action_field || "unspecified")}<br>${escapeHtml(variable.description)}</li>`).join("");
    const locator = pendingLocator || {};
    const previewBase64 = locator.image_candidates?.[0]?.png_base64;
    const locatorPreview = typeof previewBase64 === "string" && /^[A-Za-z0-9+/=]+$/.test(previewBase64)
      ? `<img src="data:image/png;base64,${previewBase64}" alt="Proposed locator preview for ${escapeHtml(step.label || step.step_id)}">` : "";
    const region = locator.region_normalized || locator.region;
    const locatorDetails = [locator.locator_backend, Array.isArray(region) ? `Region: ${region.join(", ")}` : "", locator.window_title || locator.target_window || locator.target_window_regex,
      Array.isArray(locator.image_candidates) ? `${locator.image_candidates.length} image candidate(s)` : ""].filter(Boolean).map(escapeHtml).join(" · ");
    return `<section class="skill-semantic-review" aria-label="Semantic review for ${escapeHtml(step.label || step.step_id)}">
      <div class="skill-semantic-review-heading"><strong>Semantic Review</strong><span class="badge ${annotation.review_required ? "warning" : "ok"}">${annotation.review_required ? "Review required" : "Reviewed"}</span><small>Source: ${escapeHtml(annotation.source || "manual")}</small></div>
      ${reasons ? `<p class="skill-semantic-review-note">Review reasons: ${reasons}</p>` : ""}
      <div class="skill-semantic-review-fields">${fields}</div>
      ${variables ? `<details class="skill-semantic-proposals"><summary>Variable proposals (${annotation.proposed_variables.length}) — not execution bindings</summary><p>Recorded values remain unchanged. Reviewing this step does not bind or substitute variables.</p><ul>${variables}</ul></details>` : ""}
      ${pendingLocator ? `<div class="skill-semantic-locator"><strong>Proposed locator — not applied</strong>${locatorPreview}<p>${locatorDetails || "Model-proposed target locator"}</p><label><input type="checkbox" data-step-id="${escapeHtml(step.step_id)}" data-accept-locator ${draft.acceptLocator ? "checked" : ""} ${disabled}> Also accept this locator and update the saved workflow</label><small>Unchecked: save semantic review only; locator review stays pending. Acceptance requires a separate confirmation and invalidates compiled artifacts.</small><div class="button-row"><button class="btn mini" type="button" data-step-id="${escapeHtml(step.step_id)}" data-step-command="reject-locator" ${disabled || (state.dirty ? "disabled" : "")}>Reject Locator &amp; Save Review</button><small>Reject this proposal and keep the current saved workflow locator unchanged.</small></div></div>` : annotation.locator_status === "rejected" ? '<p class="skill-semantic-review-note">Locator proposal rejected. The saved workflow locator was kept unchanged.</p>' : ""}
      <div class="button-row"><button class="btn mini primary" type="button" data-step-id="${escapeHtml(step.step_id)}" data-step-command="review" ${disabled || (state.dirty ? "disabled" : "")}>${draft.acceptLocator && pendingLocator ? "Save Review &amp; Apply Locator" : "Save &amp; Accept Semantic Review"}</button><small>${state.dirty ? "Save workflow changes before accepting review." : draft.acceptLocator && pendingLocator ? "Updates the saved locator after confirmation. Does not run equipment or bind variables." : "Saves review only. Does not run the step or bind variables."}</small></div>
    </section>`;
  }

  async function saveSemanticReview(stepId, { rejectLocator = false } = {}) {
    if (!state.editable || state.busy) return;
    if (state.dirty) throw new Error("Save the workflow before accepting semantic review. Local edits are preserved.");
    const annotation = annotationFor(stepId);
    if (!annotation) return;
    const draft = state.reviewDrafts[stepId] || {};
    const reviewed = { step_id: stepId, review_required: false, review_reasons: [] };
    for (const [key, _label, list] of reviewFields) {
      const value = draft[key] ?? (list ? (annotation[key] || []).join("\n") : annotation[key] || "");
      reviewed[key] = list ? value.split("\n").map((item) => item.trim()).filter(Boolean) : value.trim();
      if (list && (reviewed[key].length > 16 || reviewed[key].some((item) => item.length > 1000))) throw new Error(`${_label}: use at most 16 items, each 1000 characters or fewer.`);
    }
    if (rejectLocator) {
      if (annotation.locator_status !== "proposed" || !annotation.locator) return;
      if (!window.confirm("Reject this proposed locator and save the semantic review? The current saved workflow locator will remain unchanged. No equipment will run.")) return;
      reviewed.reject_locator = true;
    } else if (draft.acceptLocator && annotation.locator_status === "proposed" && annotation.locator) {
      if (!window.confirm("Accept this proposed locator and update the saved executable workflow? Existing compiled artifacts will be invalidated. No equipment will run.")) return;
      reviewed.locator = annotation.locator;
      reviewed.locator_status = "reviewed";
    }
    setBusy(true);
    try {
      const payload = await apiJson(apiBase.replace(/\/workflow$/, "/annotate"), {
        method: "POST", body: JSON.stringify({ use_model: false, annotations: { steps: [reviewed] } }),
      });
      state.annotations = payload.annotations;
      state.workflow = model.normalizeWorkflowState(payload.workflow);
      state.workflowSha256 = payload.manifest.workflow_sha256;
      root.dataset.skillLifecycle = payload.manifest.lifecycle;
      delete state.reviewDrafts[stepId];
      const pending = annotationFor(stepId)?.review_required;
      const pendingMessage = annotationFor(stepId)?.locator_status === "proposed" ? "Semantic review saved. Proposed locator review remains pending." : "Semantic review saved. Further review remains required.";
      setStatus(pending ? pendingMessage : rejectLocator ? "Semantic review accepted; locator proposal rejected. Saved workflow unchanged; no equipment was run." : "Semantic review accepted. No equipment was run; variable proposals remain unbound.", pending ? "warning" : "ok");
    } catch (error) {
      setStatus(`Review save failed: ${error.message}. Local review edits were preserved.`, "error");
    } finally {
      setBusy(false);
      renderEditor();
    }
  }

  function issuesFor(stepId) {
    return state.issues.filter((issue) => String(issue.step_id || "") === stepId);
  }

  function fieldInput(stepId, label, path, value, type = "text", attrs = "") {
    return `<label>${escapeHtml(label)}<input class="text-input" type="${type}" value="${escapeHtml(value)}" data-step-id="${escapeHtml(stepId)}" data-field-path="${escapeHtml(path)}" ${attrs}></label>`;
  }

  function selectInput(stepId, label, path, value, options) {
    const choices = options.map(([key, text]) => `<option value="${escapeHtml(key)}" ${key === value ? "selected" : ""}>${escapeHtml(text)}</option>`).join("");
    return `<label>${escapeHtml(label)}<select class="text-input" data-step-id="${escapeHtml(stepId)}" data-field-path="${escapeHtml(path)}">${choices}</select></label>`;
  }

  function actionFields(step) {
    const id = step.step_id;
    const action = step.action || {};
    const name = action.action;
    const pointer = ["move_to", "click", "double_click", "drag_to"].includes(name);
    const parts = [];
    if (pointer) {
      parts.push(fieldInput(id, "X", "action.x", action.x ?? "", "number", "step=1"));
      parts.push(fieldInput(id, "Y", "action.y", action.y ?? "", "number", "step=1"));
    }
    if (["move_to", "drag_to"].includes(name)) parts.push(fieldInput(id, "Duration s", "action.duration_sec", action.duration_sec ?? 0.25, "number", 'min="0.05" max="5" step="0.05"'));
    if (["click", "double_click", "drag_to"].includes(name)) parts.push(selectInput(id, "Button", "action.button", action.button || "left", [["left", "Left"], ["middle", "Middle"], ["right", "Right"]]));
    if (["scroll", "hscroll"].includes(name)) parts.push(fieldInput(id, "Clicks", "action.clicks", action.clicks ?? 1, "number", "step=1"));
    if (name === "write") parts.push(fieldInput(id, "Text", "action.text", action.text || "", "text", 'maxlength="512"'));
    if (name === "press") {
      parts.push(fieldInput(id, "Key", "action.key", action.key || "enter"));
      parts.push(fieldInput(id, "Presses", "action.presses", action.presses ?? 1, "number", 'min="1" step="1"'));
      parts.push(fieldInput(id, "Interval s", "action.interval", action.interval ?? 0, "number", 'min="0" step="0.01"'));
    }
    if (name === "hotkey") parts.push(fieldInput(id, "Keys", "action.keys", (action.keys || []).join("+"), "text", 'data-value-kind="keys"'));
    if (name === "set_input_language") {
      parts.push(fieldInput(id, "Layout ID", "action.layout_id", action.layout_id || "00000409", "text", 'maxlength="8" pattern="[0-9A-Fa-f]{8}"'));
      parts.push(fieldInput(id, "Locale", "action.locale", action.locale || "en_US"));
      parts.push(fieldInput(id, "Language", "action.language", action.language || "en"));
      parts.push(selectInput(id, "IME mode", "action.ime_mode", action.ime_mode || "alphanumeric", [["alphanumeric", "Alphanumeric"], ["native", "Native"]]));
      parts.push(fieldInput(id, "Typing mode", "action.typing_mode", action.typing_mode || "latin"));
    }
    if (name === "wait") parts.push(fieldInput(id, "Seconds", "action.seconds", action.seconds ?? 1, "number", 'min="0" max="30" step="0.1"'));
    if (["wait_until", "wait_until_image", "wait_until_text"].includes(name)) parts.push(fieldInput(id, "Target", "action.target", action.target || ""));
    if (name === "wait_until_text") parts.push(fieldInput(id, "Expected text", "action.text", action.text || ""));
    if (name === "wait_for_file") parts.push(fieldInput(id, "File pattern", "action.pattern", action.pattern || ""));
    if (["wait_until", "wait_until_image", "wait_until_text", "wait_for_file"].includes(name)) {
      parts.push(fieldInput(id, "Timeout s", "action.timeout_s", action.timeout_s ?? 30, "number", 'min="0.1" max="3600" step="0.1"'));
      parts.push(fieldInput(id, "Poll interval s", "action.poll_interval_s", action.poll_interval_s ?? 0.5, "number", 'min="0.05" max="10" step="0.05"'));
    }
    if (name === "screenshot") parts.push(fieldInput(id, "Checkpoint", "action.checkpoint", action.checkpoint || "checkpoint"));
    return parts.join("");
  }

  function locatorMarkup(step) {
    const candidates = Array.isArray(step.action?.image_candidates) ? step.action.image_candidates : [];
    const preview = candidates[0]?.png_base64
      ? `<img src="data:image/png;base64,${candidates[0].png_base64}" alt="Locator preview for ${escapeHtml(step.label)}">`
      : `<span>No embedded locator</span>`;
    return `<div class="skill-workflow-locator"><div>${preview}<small>${candidates.length ? `${candidates.length} candidate(s)` : "Coordinate or target lookup"}</small></div><div class="skill-workflow-locator-actions"><button class="btn mini" type="button" data-step-command="crop" data-step-id="${escapeHtml(step.step_id)}" ${state.editable ? "" : "disabled"}>Edit Crop</button><label class="btn mini ${state.editable ? "" : "disabled"}">Replace locator<input type="file" accept="image/png" data-locator-step="${escapeHtml(step.step_id)}" ${state.editable ? "" : "disabled"}></label></div></div>`;
  }

  function renderStep(step, index) {
    const expanded = step.step_id === state.expandedStepId;
    const selected = step.step_id === state.selectedStepId;
    const issues = issuesFor(step.step_id);
    const needsReview = annotationFor(step.step_id)?.review_required;
    const issueMarkup = issues.length ? `<div class="skill-workflow-step-issues">${issues.map((issue) => `<span>${escapeHtml(issue.message)}</span>`).join("")}</div>` : "";
    const actionOptions = Object.entries(model.ACTION_LABELS).map(([key, label]) => `<option value="${escapeHtml(key)}" ${key === step.action?.action ? "selected" : ""}>${escapeHtml(label)}</option>`).join("");
    return `<article class="skill-workflow-step-card ${expanded ? "expanded" : ""} ${selected ? "selected" : ""} ${issues.length ? "invalid" : ""}" data-step-card="${escapeHtml(step.step_id)}" draggable="${state.editable}">
      <button class="skill-workflow-step-summary" type="button" data-expand-step="${escapeHtml(step.step_id)}">
        <span class="skill-workflow-step-index">${String(index + 1).padStart(2, "0")}</span>
        <span><strong>${escapeHtml(step.label || step.step_id)}</strong><small>${escapeHtml(model.actionSummary(step))}</small></span>
        <span class="skill-workflow-step-state">${issues.length ? `${issues.length} issue(s)` : needsReview ? "Review required" : expanded ? "Expanded" : "Ready"}</span>
      </button>
      <div class="skill-workflow-step-editor" ${expanded ? "" : "hidden"}>
        <div class="skill-workflow-fields">
          ${fieldInput(step.step_id, "Step label", "label", step.label || "", "text", 'maxlength="160"')}
          <label>Action<select class="text-input" data-step-id="${escapeHtml(step.step_id)}" data-action-type>${actionOptions}</select></label>
          ${actionFields(step)}
          <label class="skill-workflow-check"><input type="checkbox" data-step-id="${escapeHtml(step.step_id)}" data-field-path="checkpoint_after" ${step.checkpoint_after ? "checked" : ""}> Capture checkpoint after step</label>
        </div>
        ${locatorMarkup(step)}
        ${reviewMarkup(step)}
        ${issueMarkup}
        <div class="button-row skill-workflow-step-actions">
          <button class="btn mini" type="button" data-step-command="up" data-step-id="${escapeHtml(step.step_id)}" ${index === 0 || !state.editable ? "disabled" : ""}>Move up</button>
          <button class="btn mini" type="button" data-step-command="down" data-step-id="${escapeHtml(step.step_id)}" ${index === state.workflow.steps.length - 1 || !state.editable ? "disabled" : ""}>Move down</button>
          <button class="btn mini" type="button" data-step-command="duplicate" data-step-id="${escapeHtml(step.step_id)}" ${state.editable ? "" : "disabled"}>Duplicate</button>
          <button class="btn mini danger" type="button" data-step-command="delete" data-step-id="${escapeHtml(step.step_id)}" ${state.editable ? "" : "disabled"}>Delete</button>
          <button class="btn mini primary" type="button" data-step-command="test" data-step-id="${escapeHtml(step.step_id)}" ${!workerId || hasUnsavedChanges() || needsReview || issues.length ? "disabled" : ""}>Test one step</button>
        </div>
      </div>
    </article>`;
  }

  function renderEditor() {
    if (!state.workflow) return;
    const bounds = model.durationBounds(state.workflow);
    elements.lifecycle.textContent = root.dataset.skillLifecycle || "draft";
    elements.lifecycle.className = `badge ${state.editable ? "idle" : "warning"}`;
    elements.dirty.textContent = hasUnsavedChanges() ? "Unsaved" : "Saved";
    elements.dirty.className = `badge ${hasUnsavedChanges() ? "warning" : "ok"}`;
    elements.duration.textContent = `Wait estimate ${bounds.minimum_s.toFixed(1)}-${bounds.maximum_s.toFixed(1)}s`;
    elements.count.textContent = `${state.workflow.steps.length} step${state.workflow.steps.length === 1 ? "" : "s"}`;
    elements.list.innerHTML = state.workflow.steps.map(renderStep).join("");
    elements.worker.textContent = `Worker: ${workerId || "not selected (step test disabled)"}`;
    elements.save.disabled = state.busy || !state.editable || !state.dirty;
    elements.add.disabled = state.busy || !state.editable;
    elements.addAction.disabled = state.busy || !state.editable;
    if (elements.computerUsePolicy) elements.computerUsePolicy.disabled = state.busy || !state.editable;
    if (elements.applyComputerUsePolicy) elements.applyComputerUsePolicy.disabled = state.busy || !state.editable;
    if (!state.editable) {
      elements.list.querySelectorAll("input, select, textarea").forEach((control) => { control.disabled = true; });
    }
    if (state.busy) elements.list.querySelectorAll("input, select, textarea, button").forEach((control) => { control.disabled = true; });
  }

  function markDirty(workflow, selectedStepId = state.selectedStepId) {
    state.workflow = workflow;
    state.selectedStepId = selectedStepId;
    state.expandedStepId = selectedStepId || state.expandedStepId;
    state.dirty = true;
    state.issues = [];
    setStatus("Unsaved workflow changes.", "warning");
    renderEditor();
  }

  function typedValue(input) {
    if (input.type === "checkbox") return input.checked;
    if (input.dataset.valueKind === "keys") return input.value.split("+").map((value) => value.trim()).filter(Boolean);
    if (input.type === "number") return input.value === "" ? null : Number(input.value);
    return input.value;
  }

  async function loadWorkflow() {
    setBusy(true);
    try {
      const payload = await apiJson(apiBase);
      state.workflow = model.normalizeWorkflowState(payload.workflow);
      state.workflowSha256 = payload.workflow_sha256;
      state.annotations = payload.annotations || { steps: [] };
      state.reviewDrafts = {};
      state.editable = payload.editable === true;
      state.dirty = false;
      state.issues = [];
      state.selectedStepId = state.workflow.steps[0]?.step_id || "";
      state.expandedStepId = state.selectedStepId;
      if (elements.computerUsePolicy) {
        elements.computerUsePolicy.value = serializeComputerUsePolicy(state.workflow.computer_use);
      }
      root.dataset.skillLifecycle = payload.manifest?.lifecycle || root.dataset.skillLifecycle;
      const pendingReview = state.annotations.steps?.some((annotation) => annotation.review_required);
      setStatus(!state.editable ? "This deployed Skill version is read-only." : pendingReview ? "Workflow loaded. Review semantic evidence and proposed locators before compiling." : "Exact Skill workflow loaded.", !state.editable || pendingReview ? "warning" : "ok");
    } catch (error) {
      setStatus(`Load failed: ${error.message}`, "error");
      throw error;
    } finally {
      setBusy(false);
      renderEditor();
    }
  }

  async function checkWorkflow() {
    setBusy(true);
    try {
      const payload = await apiJson(`${apiBase}/check`, { method: "POST", body: JSON.stringify({ workflow: state.workflow }) });
      state.issues = payload.issues || [];
      setStatus(payload.ok ? "Workflow contract check passed." : `${state.issues.length} workflow issue(s) require correction.`, payload.ok ? "ok" : "error");
      return payload.ok;
    } finally {
      setBusy(false);
      renderEditor();
    }
  }

  async function saveWorkflow() {
    if (!state.editable || !state.dirty) return;
    const valid = await checkWorkflow();
    if (!valid) return;
    setBusy(true);
    try {
      const payload = await apiJson(apiBase, {
        method: "PUT",
        body: JSON.stringify({ expected_workflow_sha256: state.workflowSha256, workflow: state.workflow }),
      });
      state.workflow = model.normalizeWorkflowState(payload.workflow);
      state.workflowSha256 = payload.manifest.workflow_sha256;
      state.annotations = payload.annotations || state.annotations;
      root.dataset.skillLifecycle = payload.manifest.lifecycle;
      state.dirty = false;
      state.issues = [];
      setStatus("Workflow saved. Previous compiled artifacts were invalidated.", "ok");
    } catch (error) {
      if (error.status === 409) setStatus("Save conflict: this Skill changed elsewhere. Local edits were preserved.", "error");
      else setStatus(`Save failed: ${error.message}`, "error");
    } finally {
      setBusy(false);
      renderEditor();
    }
  }

  async function testStep(stepId) {
    if (hasUnsavedChanges()) throw new Error("Save the workflow and semantic review before testing a step.");
    if (annotationFor(stepId)?.review_required) throw new Error("Accept semantic and locator review before testing this step.");
    if (!workerId) throw new Error("Open the editor from a selected Worker to test a step.");
    if (!window.confirm("Run only this saved step on the selected Worker?")) return;
    setBusy(true);
    try {
      const payload = await apiJson(`${apiBase}/steps/${encodeURIComponent(stepId)}/test`, {
        method: "POST",
        body: JSON.stringify({ bridge_id: workerId, confirm_execute: true }),
      });
      setStatus(`Step ${payload.step_id} completed on ${workerId}.`, "ok");
    } finally {
      setBusy(false);
      renderEditor();
    }
  }

  async function imageCandidate(file, kind = "editor") {
    if (!file || file.type !== "image/png") throw new Error("Select a PNG locator image.");
    if (file.size > 256 * 1024) throw new Error("Locator PNG must be 256 KiB or smaller.");
    const bytes = new Uint8Array(await file.arrayBuffer());
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    const sha256 = Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, "0")).join("");
    const pngBase64 = btoa(Array.from(bytes, (value) => String.fromCharCode(value)).join(""));
    const dimensions = await new Promise((resolve, reject) => {
      const image = new Image();
      image.onload = () => resolve({ width: image.naturalWidth, height: image.naturalHeight });
      image.onerror = () => reject(new Error("Unable to read locator image dimensions."));
      image.src = `data:image/png;base64,${pngBase64}`;
    });
    if (dimensions.width > 512 || dimensions.height > 512) throw new Error("Locator dimensions must be 512x512 or smaller.");
    return { kind, png_base64: pngBase64, sha256, ...dimensions, confidence: 0.9 };
  }

  function renderCrop() {
    if (!state.crop || !elements.cropSource.complete || !elements.cropSource.naturalWidth) return;
    const [x, y, width, height] = state.crop.box;
    Object.assign(elements.cropBox.style, {
      left: `${x * 100}%`,
      top: `${y * 100}%`,
      width: `${width * 100}%`,
      height: `${height * 100}%`,
    });
    const dimensions = model.cropPixelRect(
      state.crop.box,
      elements.cropSource.naturalWidth,
      elements.cropSource.naturalHeight,
    );
    elements.cropPreview.width = dimensions.output_width;
    elements.cropPreview.height = dimensions.output_height;
    const context = elements.cropPreview.getContext("2d");
    context.clearRect(0, 0, dimensions.output_width, dimensions.output_height);
    context.drawImage(
      elements.cropSource,
      dimensions.source_x,
      dimensions.source_y,
      dimensions.source_width,
      dimensions.source_height,
      0,
      0,
      dimensions.output_width,
      dimensions.output_height,
    );
    elements.cropCoordinates.textContent = `x ${x.toFixed(3)} · y ${y.toFixed(3)} · w ${width.toFixed(3)} · h ${height.toFixed(3)} · ${dimensions.output_width}×${dimensions.output_height}`;
  }

  async function openCropEditor(stepId) {
    if (!state.editable) return;
    setStatus("Loading the verified pre-action frame.", "idle");
    try {
      const source = await apiJson(`${apiBase}/steps/${encodeURIComponent(stepId)}/locator-source`);
      const localStep = state.workflow.steps.find((item) => item.step_id === stepId);
      const localBox = localStep?.action?.target_bbox_norm;
      const currentBox = Array.isArray(localBox) && localBox.length === 4
        ? localBox.map(Number)
        : source.target_bbox_norm;
      state.crop = {
        stepId,
        source,
        box: [...currentBox],
        aiBox: [...(source.ai_target_bbox_norm || source.target_bbox_norm)],
        drag: null,
      };
      const loaded = new Promise((resolve, reject) => {
        elements.cropSource.onload = resolve;
        elements.cropSource.onerror = () => reject(new Error("Unable to load the verified pre-action frame."));
      });
      elements.cropSource.src = `${source.image_url}?sha256=${encodeURIComponent(source.source_sha256)}`;
      elements.cropDialog.showModal();
      await loaded;
      renderCrop();
      setStatus("Adjust the Target ROI, then apply and save the workflow.", "ok");
    } catch (error) {
      state.crop = null;
      if (elements.cropDialog.open) elements.cropDialog.close();
      setStatus(`Crop source unavailable: ${error.message}`, "error");
    }
  }

  function closeCropEditor() {
    state.crop = null;
    elements.cropSource.removeAttribute("src");
    if (elements.cropDialog.open) elements.cropDialog.close();
  }

  function canvasBlob(canvas) {
    return new Promise((resolve, reject) => canvas.toBlob(
      (blob) => blob ? resolve(blob) : reject(new Error("Unable to encode the crop as PNG.")),
      "image/png",
    ));
  }

  async function boundedCropBlob() {
    let source = elements.cropPreview;
    let blob = await canvasBlob(source);
    while (blob.size > 256 * 1024 && Math.max(source.width, source.height) > 64) {
      const scale = Math.max(64 / Math.max(source.width, source.height), 0.82);
      const reduced = document.createElement("canvas");
      reduced.width = Math.max(1, Math.floor(source.width * scale));
      reduced.height = Math.max(1, Math.floor(source.height * scale));
      reduced.getContext("2d").drawImage(source, 0, 0, reduced.width, reduced.height);
      source = reduced;
      blob = await canvasBlob(source);
    }
    if (blob.size > 256 * 1024) throw new Error("The cropped PNG exceeds 256 KiB. Select a smaller Target ROI.");
    return blob;
  }

  async function applyCrop() {
    if (!state.crop) return;
    elements.cropApply.disabled = true;
    try {
      const stepId = state.crop.stepId;
      const step = state.workflow.steps.find((item) => item.step_id === stepId);
      const existing = Array.isArray(step?.action?.image_candidates) ? step.action.image_candidates : [];
      const dimensions = model.cropPixelRect(
        state.crop.box,
        elements.cropSource.naturalWidth,
        elements.cropSource.naturalHeight,
      );
      const candidate = {
        ...await imageCandidate(await boundedCropBlob(), "manual_target"),
        crop_origin: [dimensions.source_x, dimensions.source_y],
      };
      let workflow = model.updateStepField(
        state.workflow,
        stepId,
        ["action", "image_candidates"],
        [candidate, ...existing.slice(1)],
      );
      workflow = model.updateStepField(workflow, stepId, ["action", "target_bbox_norm"], [...state.crop.box]);
      workflow = model.updateStepField(workflow, stepId, ["action", "ai_target_bbox_norm"], [...state.crop.aiBox]);
      workflow = model.updateStepField(workflow, stepId, ["action", "locator_origin"], "manual_crop");
      closeCropEditor();
      markDirty(workflow, stepId);
      setStatus("Target crop applied locally. Save the workflow to persist it.", "warning");
    } catch (error) {
      setStatus(`Crop apply failed: ${error.message}`, "error");
    } finally {
      elements.cropApply.disabled = false;
    }
  }

  elements.list.addEventListener("click", async (event) => {
    const expand = event.target.closest("[data-expand-step]");
    if (expand) {
      const stepId = expand.dataset.expandStep;
      state.selectedStepId = stepId;
      state.expandedStepId = state.expandedStepId === stepId ? "" : stepId;
      renderEditor();
      return;
    }
    const command = event.target.closest("[data-step-command]");
    if (!command) return;
    if (state.busy || (!state.editable && command.dataset.stepCommand !== "test")) return;
    const stepId = command.dataset.stepId;
    const index = state.workflow.steps.findIndex((step) => step.step_id === stepId);
    try {
      if (command.dataset.stepCommand === "up") markDirty(model.moveStep(state.workflow, stepId, index - 1), stepId);
      if (command.dataset.stepCommand === "down") markDirty(model.moveStep(state.workflow, stepId, index + 1), stepId);
      if (command.dataset.stepCommand === "duplicate") {
        const next = model.duplicateStep(state.workflow, stepId);
        markDirty(next, next.steps[index + 1].step_id);
      }
      if (command.dataset.stepCommand === "delete") {
        if (state.reviewDrafts[stepId] && !window.confirm("Delete this step and its unsaved semantic review edits?")) return;
        delete state.reviewDrafts[stepId];
        markDirty(model.deleteStep(state.workflow, stepId), state.workflow.steps[Math.max(0, index - 1)]?.step_id || "");
      }
      if (command.dataset.stepCommand === "review") await saveSemanticReview(stepId);
      if (command.dataset.stepCommand === "reject-locator") await saveSemanticReview(stepId, { rejectLocator: true });
      if (command.dataset.stepCommand === "test") await testStep(stepId);
      if (command.dataset.stepCommand === "crop") await openCropEditor(stepId);
    } catch (error) { setStatus(error.message, "error"); }
  });

  elements.list.addEventListener("input", (event) => {
    const input = event.target;
    if (!state.editable || state.busy || !input.dataset.reviewField || !annotationFor(input.dataset.stepId)) return;
    const draft = state.reviewDrafts[input.dataset.stepId] ||= {};
    draft[input.dataset.reviewField] = input.value;
    elements.dirty.textContent = "Unsaved";
    elements.dirty.className = "badge warning";
    elements.list.querySelectorAll('[data-step-command="test"]').forEach((button) => { button.disabled = true; });
    setStatus("Unsaved semantic review. Use Save & Accept Semantic Review on this step.", "warning");
  });

  elements.list.addEventListener("change", async (event) => {
    const input = event.target;
    const stepId = input.dataset.stepId;
    if (!state.editable || state.busy) return;
    if (Object.hasOwn(input.dataset, "acceptLocator")) {
      const draft = state.reviewDrafts[stepId] ||= {};
      draft.acceptLocator = input.checked;
      renderEditor();
      return;
    }
    if (input.dataset.locatorStep) {
      try {
        const candidate = await imageCandidate(input.files[0]);
        markDirty(model.updateStepField(state.workflow, input.dataset.locatorStep, ["action", "image_candidates"], [candidate]), input.dataset.locatorStep);
      } catch (error) { setStatus(error.message, "error"); }
      return;
    }
    if (!stepId || !state.editable) return;
    if (input.hasAttribute("data-action-type")) {
      markDirty(model.updateStepField(state.workflow, stepId, ["action"], model.actionDefaults(input.value)), stepId);
      return;
    }
    const path = String(input.dataset.fieldPath || "").split(".").filter(Boolean);
    if (path.length) markDirty(model.updateStepField(state.workflow, stepId, path, typedValue(input)), stepId);
  });

  elements.list.addEventListener("dragstart", (event) => {
    if (!state.editable || state.busy) { event.preventDefault(); return; }
    const card = event.target.closest("[data-step-card]");
    if (card) event.dataTransfer.setData("text/plain", card.dataset.stepCard);
  });
  elements.list.addEventListener("dragover", (event) => event.preventDefault());
  elements.list.addEventListener("drop", (event) => {
    event.preventDefault();
    const target = event.target.closest("[data-step-card]");
    const stepId = event.dataTransfer.getData("text/plain");
    if (!target || !stepId || !state.editable || state.busy) return;
    const targetIndex = state.workflow.steps.findIndex((step) => step.step_id === target.dataset.stepCard);
    markDirty(model.moveStep(state.workflow, stepId, targetIndex), stepId);
  });

  elements.add.addEventListener("click", () => {
    if (!state.editable || state.busy) return;
    const reference = state.selectedStepId || state.workflow.steps.at(-1)?.step_id || "";
    const next = model.insertStep(state.workflow, reference, "after", elements.addAction.value);
    const referenceIndex = next.steps.findIndex((step) => step.step_id === reference);
    markDirty(next, next.steps[Math.min(referenceIndex + 1, next.steps.length - 1)].step_id);
  });
  elements.applyComputerUsePolicy?.addEventListener("click", () => {
    if (!state.editable || state.busy) return;
    try {
      const policy = parseComputerUsePolicy(elements.computerUsePolicy?.value || "");
      const workflow = { ...state.workflow };
      if (policy) workflow.computer_use = policy;
      else delete workflow.computer_use;
      markDirty(workflow);
      setStatus("Computer-use policy applied to this editable Skill version. Check and Save to persist it.", "warning");
    } catch (error) {
      setStatus(error.message, "error");
    }
  });
  elements.check.addEventListener("click", () => checkWorkflow().catch((error) => setStatus(error.message, "error")));
  elements.save.addEventListener("click", () => saveWorkflow());
  elements.close.addEventListener("click", () => {
    if (!hasUnsavedChanges() || window.confirm("Close and discard unsaved workflow and semantic review changes?")) window.close();
  });
  window.addEventListener("beforeunload", (event) => {
    if (!hasUnsavedChanges()) return;
    event.preventDefault();
    event.returnValue = "";
  });

  elements.cropBox.addEventListener("pointerdown", (event) => {
    if (!state.crop) return;
    event.preventDefault();
    const handle = event.target.closest("[data-crop-handle]")?.dataset.cropHandle || "move";
    const sourceRect = elements.cropSource.getBoundingClientRect();
    state.crop.drag = {
      pointerId: event.pointerId,
      handle,
      startX: event.clientX,
      startY: event.clientY,
      sourceWidth: sourceRect.width,
      sourceHeight: sourceRect.height,
      startBox: [...state.crop.box],
    };
    elements.cropBox.setPointerCapture(event.pointerId);
  });

  elements.cropBox.addEventListener("pointermove", (event) => {
    const drag = state.crop?.drag;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const deltaX = (event.clientX - drag.startX) / Math.max(1, drag.sourceWidth);
    const deltaY = (event.clientY - drag.startY) / Math.max(1, drag.sourceHeight);
    state.crop.box = model.adjustCropBox(drag.startBox, drag.handle, deltaX, deltaY);
    renderCrop();
  });

  function endCropDrag(event) {
    if (!state.crop?.drag || state.crop.drag.pointerId !== event.pointerId) return;
    state.crop.drag = null;
    if (elements.cropBox.hasPointerCapture(event.pointerId)) elements.cropBox.releasePointerCapture(event.pointerId);
  }

  elements.cropBox.addEventListener("pointerup", endCropDrag);
  elements.cropBox.addEventListener("pointercancel", endCropDrag);
  elements.cropReset.addEventListener("click", () => {
    if (!state.crop) return;
    state.crop.box = [...state.crop.aiBox];
    renderCrop();
  });
  elements.cropApply.addEventListener("click", () => applyCrop());
  elements.cropCancel.addEventListener("click", closeCropEditor);
  elements.cropDialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    closeCropEditor();
  });

  loadWorkflow().catch(() => {});
})();
