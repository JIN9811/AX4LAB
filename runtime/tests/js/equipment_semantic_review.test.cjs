"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const model = require("../../web/static/equipment_skill_workflow_model.js");
const root = path.join(__dirname, "../../web/static");
const tick = () => new Promise(resolve => setImmediate(resolve));

function fixture() {
  return {
    editable: true, workflow_sha256: "original-hash",
    manifest: {lifecycle: "review_required", workflow_sha256: "original-hash"},
    workflow: {steps: [{step_id: "step-001", label: "Open specimen", action: {action: "click", x: 20, y: 30}}]},
    annotations: {status: "review_required", steps: [{
      step_id: "step-001", intent: "Open specimen dialog", target_semantics: "Specimen number button",
      preconditions: ["Test method selected"], postconditions: ["Specimen dialog visible"],
      success_evidence: ["Editable specimen field"], failure_evidence: ["Dialog did not open"],
      ambiguity: "Two similar buttons", source: "model", review_required: true,
      review_reasons: ["ambiguity", "model_locator_change"], locator_status: "proposed",
      locator: {region_normalized: [0.1, 0.2, 0.3, 0.4], locator_backend: "opencv"},
      proposed_variables: [{name: "specimen_id", type: "string", recorded_value: "DEMO-001", description: "Specimen label", action_field: "text", status: "proposed"}],
    }]},
  };
}

async function editorHarness(options = {}) {
  const payload = fixture();
  if (options.locatorPreview) payload.annotations.steps[0].locator.image_candidates = [{png_base64: "aGVsbG8="}];
  if (options.deployed) { payload.editable = false; payload.manifest.lifecycle = "deployed"; }
  const elements = {}, requests = [], confirms = [], windowEvents = {};
  function element(id) {
    return elements[id] ||= {dataset: {}, listeners: {}, innerHTML: "", textContent: "", value: "", disabled: false,
      addEventListener(name, fn) { this.listeners[name] = fn; },
      querySelectorAll() { return []; },
    };
  }
  Object.assign(element("skill-workflow-editor").dataset, {skillId: "specimen", skillVersion: "1.0.0"});
  const context = vm.createContext({
    document: {getElementById: element}, URL, URLSearchParams,
    window: {EquipmentSkillWorkflowModel: model, location: {origin: "http://fixture.test", search: "?profile_id=lab-a&worker=safe-fixture"},
      confirm(message) { confirms.push(message); return options.confirm !== false; }, close() {},
      addEventListener(name, fn) { windowEvents[name] = fn; }},
    fetch: async (url, request = {}) => {
      const body = request.body ? JSON.parse(request.body) : null;
      requests.push({url, method: request.method || "GET", body});
      if (request.method === "POST" && url.includes("/workflow/check")) return {ok: true, json: async () => ({ok: true, issues: []})};
      if (request.method === "PUT" && options.savedAnnotations) {
        payload.workflow = body.workflow;
        payload.annotations = structuredClone(options.savedAnnotations);
        payload.manifest.workflow_sha256 = "manual-crop-hash";
        return {ok: true, json: async () => structuredClone(payload)};
      }
      if (request.method === "POST" && url.includes("/annotate")) {
        if (options.saveGate) await options.saveGate;
        if (options.failSave) return {ok: false, status: 409, json: async () => ({detail: {message: "Changed elsewhere"}})};
        Object.assign(payload.annotations.steps[0], body.annotations.steps[0]);
        if (body.annotations.steps[0].reject_locator) {
          payload.annotations.steps[0].locator_status = "rejected";
          delete payload.annotations.steps[0].locator;
        } else if (!body.annotations.steps[0].locator && payload.annotations.steps[0].locator_status === "proposed") {
          payload.annotations.steps[0].review_required = true;
          payload.annotations.steps[0].review_reasons = ["model_locator_change"];
        }
        payload.manifest.workflow_sha256 = "reviewed-hash";
        return {ok: true, json: async () => structuredClone(payload)};
      }
      return {ok: true, json: async () => structuredClone(payload)};
    },
  });
  vm.runInContext(fs.readFileSync(path.join(root, "equipment_skill_workflow_editor.js"), "utf8"), context);
  await tick();
  const dispatch = async (type, dataset, value = "", checked = false) => {
    const target = {dataset, value, checked, type: checked ? "checkbox" : "text", disabled: false,
      hasAttribute: name => name === "data-action-type" && Boolean(dataset.actionType),
      closest: selector => selector === "[data-step-command]" && dataset.stepCommand ? target : null};
    await element("workflow-editor-step-list").listeners[type]?.({target});
  };
  return {elements, requests, confirms, windowEvents, dispatch, payload,
    markup: () => element("workflow-editor-step-list").innerHTML,
    change: (field, value) => dispatch("input", {stepId: "step-001", reviewField: field}, value),
    review: () => dispatch("click", {stepId: "step-001", stepCommand: "review"}),
  };
}

test("editor renders semantic evidence and proposed variables without treating them as bindings", async () => {
  const h = await editorHarness();
  for (const value of ["Open specimen dialog", "Specimen number button", "Test method selected", "Dialog did not open", "Two similar buttons", "specimen_id", "DEMO-001"]) assert.ok(h.markup().includes(value), value);
  assert.match(h.markup(), /Review required/);
  assert.match(h.markup(), /not execution bindings/i);
  assert.match(h.markup(), /data-accept-locator/);
  assert.doesNotMatch(h.markup(), /data-accept-locator[^>]*checked/);
});

test("proposed locator preview is visible before approval and checked acceptance clearly names workflow mutation", async () => {
  const h = await editorHarness({locatorPreview: true});
  assert.match(h.markup(), /<img[^>]+alt="Proposed locator preview/);
  await h.dispatch("change", {stepId: "step-001", acceptLocator: ""}, "", true);
  assert.match(h.markup(), /Save Review &amp; Apply Locator/);
  assert.doesNotMatch(h.markup(), /Saves review only\./);
});

test("semantic acceptance sends edited evidence only and never silently applies a proposed locator", async () => {
  const h = await editorHarness();
  await h.change("intent", "Open the confirmed specimen dialog");
  await h.change("preconditions", "Test method selected\nOperator reviewed dialog\n");
  await h.review();
  const post = h.requests.find(request => request.method === "POST");
  assert.ok(post, "review action must save through the annotation API");
  assert.equal(post.url, "/api/equipment/skills/specimen/1.0.0/annotate?profile_id=lab-a");
  assert.equal(post.body.use_model, false);
  const step = post.body.annotations.steps[0];
  assert.equal(step.intent, "Open the confirmed specimen dialog");
  assert.deepEqual(step.preconditions, ["Test method selected", "Operator reviewed dialog"]);
  assert.equal(step.review_required, false);
  for (const field of ["locator", "locator_status", "action", "proposed_variables"]) assert.equal(Object.hasOwn(step, field), false, field);
  assert.equal(h.requests.some(request => /execute|test/.test(request.url)), false);
  assert.match(h.elements["workflow-editor-status"].textContent, /locator.*pending|review.*remain/i);
});

for (const confirm of [true, false]) test(`proposed locator acceptance ${confirm ? "requires confirmation and includes locator" : "is cancelled without any write"}`, async () => {
  const h = await editorHarness({confirm});
  await h.dispatch("change", {stepId: "step-001", acceptLocator: ""}, "", true);
  await h.review();
  assert.equal(h.confirms.length, 1);
  assert.match(h.confirms[0], /locator/i);
  const posts = h.requests.filter(request => request.method === "POST");
  assert.equal(posts.length, confirm ? 1 : 0);
  if (confirm) {
    assert.deepEqual(posts[0].body.annotations.steps[0].locator, {region_normalized: [0.1, 0.2, 0.3, 0.4], locator_backend: "opencv"});
    assert.equal(posts[0].body.annotations.steps[0].locator_status, "reviewed");
  }
});

for (const confirm of [true, false]) test(`explicit locator rejection ${confirm ? "saves human review without accepting even a checked proposal" : "can be cancelled without a write"}`, async () => {
  const h = await editorHarness({confirm});
  assert.match(h.markup(), /Reject Locator &amp; Save Review/);
  await h.change("intent", "Keep my manually selected target");
  await h.dispatch("change", {stepId: "step-001", acceptLocator: ""}, "", true);
  await h.dispatch("click", {stepId: "step-001", stepCommand: "reject-locator"});
  assert.equal(h.confirms.length, 1);
  assert.match(h.confirms[0], /Reject.*locator/);
  const posts = h.requests.filter(request => request.method === "POST");
  assert.equal(posts.length, confirm ? 1 : 0);
  if (confirm) {
    const review = posts[0].body.annotations.steps[0];
    assert.equal(posts[0].body.use_model, false);
    assert.equal(review.intent, "Keep my manually selected target");
    assert.equal(review.reject_locator, true);
    assert.equal(review.review_required, false);
    for (const field of ["locator", "locator_status", "action", "proposed_variables"]) assert.equal(Object.hasOwn(review, field), false, field);
    assert.doesNotMatch(h.markup(), /data-accept-locator/);
    assert.match(h.elements["workflow-editor-status"].textContent, /rejected.*unchanged/i);
  }
});

test("manual crop workflow save refreshes annotations before review and cannot reapply the stale model locator", async () => {
  const savedAnnotations = fixture().annotations;
  savedAnnotations.steps[0].locator = {region_normalized: [0.4, 0.4, 0.1, 0.1], locator_backend: "manual_crop"};
  savedAnnotations.steps[0].locator_status = "reviewed";
  const h = await editorHarness({savedAnnotations});
  await h.dispatch("change", {stepId: "step-001", acceptLocator: ""}, "", true);
  await h.dispatch("change", {stepId: "step-001", fieldPath: "action.locator_origin"}, "manual_crop");
  await h.elements["workflow-editor-save"].listeners.click();
  assert.doesNotMatch(h.markup(), /data-accept-locator/, "the PUT response supersedes cached model proposal");
  await h.review();
  const post = h.requests.find(request => request.url.includes("/annotate"));
  assert.ok(post);
  assert.equal(Object.hasOwn(post.body.annotations.steps[0], "locator"), false);
  assert.equal(h.confirms.length, 0);
});

test("dirty workflow blocks review save and does not discard local action changes", async () => {
  const h = await editorHarness();
  await h.dispatch("change", {stepId: "step-001", fieldPath: "action.x"}, "42");
  await h.review();
  await h.dispatch("click", {stepId: "step-001", stepCommand: "reject-locator"});
  assert.equal(h.requests.filter(request => request.method === "POST").length, 0);
  assert.match(h.elements["workflow-editor-status"].textContent, /save.*workflow.*before/i);
  assert.match(h.markup(), /value="42"/);
});

test("deployed review controls are read-only and cannot save annotations", async () => {
  const h = await editorHarness({deployed: true});
  await h.change("intent", "Not allowed");
  await h.review();
  await h.dispatch("click", {stepId: "step-001", stepCommand: "reject-locator"});
  assert.equal(h.requests.filter(request => request.method === "POST").length, 0);
  assert.match(h.markup(), /data-review-field="intent"[^>]*disabled/);
});

test("unsaved semantic edits trigger close protection and survive a rejected save", async () => {
  const h = await editorHarness({failSave: true});
  await h.change("intent", "Keep this edit");
  let prevented = false;
  h.windowEvents.beforeunload({preventDefault() { prevented = true; }});
  assert.equal(prevented, true);
  await h.review();
  assert.match(h.markup(), /Keep this edit/);
  assert.match(h.elements["workflow-editor-status"].textContent, /Changed elsewhere/);
});

test("in-flight annotation save locks palette controls so its response cannot overwrite new workflow edits", async () => {
  let release;
  const saveGate = new Promise(resolve => { release = resolve; });
  const h = await editorHarness({saveGate});
  const saving = h.review();
  try {
    for (const id of ["workflow-editor-add-action", "workflow-editor-computer-use-policy", "workflow-editor-apply-computer-use-policy"]) assert.equal(h.elements[id].disabled, true, id);
  } finally { release(); await saving; }
});

function authoringHarness(job) {
  const elements = Object.fromEntries(["skillAuthoringProgress", "skillAuthoringProgressBar", "skillAuthoringStatus", "skillAuthoringDetail", "recordingStatus", "btnStopSkillAuthoring", "btnImportRecording"].map(id => [id, {dataset: {}, textContent: ""}]));
  const context = vm.createContext({...elements,
    activeSkillAuthoringJobId: "job-1", finalizedSkillAuthoringJobId: "", selectedRecordingId: "rec-1",
    window: {localStorage: {removeItem() {}}}, profileJobKey: value => value,
    setBusy() {}, writeLog() {}, refreshEquipmentSkills: async () => {}, refreshEquipmentRuntime: async () => {},
    loadSkillStoryboardPage: async () => {}, apiJson: async () => ({job}), encodeURIComponent,
  });
  const source = fs.readFileSync(path.join(root, "windows_equipment.js"), "utf8");
  const start = source.indexOf("function skillAuthoringIsActive");
  const end = source.indexOf("async function restoreSkillStoryboard", start);
  vm.runInContext(source.slice(start, end), context);
  return {context, elements};
}

test("completed authoring reports sampled coverage and review gate instead of ready to compile", async () => {
  const h = authoringHarness({status: "COMPLETED", stage: "COMPLETE", skill_id: "specimen", version: "1.0.0", result: {
    manifest: {lifecycle: "review_required"}, annotations: {status: "review_required", steps: [{review_required: true}],
      model_snapshot: {timeline_selected_frame_count: 45, timeline_source_frame_count: 900, timeline_event_coverage_complete: false, timeline_omitted_event_numbers: [7, 8]}},
  }});
  await h.context.pollSkillAuthoringJob();
  assert.doesNotMatch(h.elements.recordingStatus.textContent, /ready to compile/i);
  assert.match(h.elements.recordingStatus.textContent, /review/i);
  assert.match(h.elements.skillAuthoringDetail.textContent, /45.*900/);
  assert.match(h.elements.skillAuthoringDetail.textContent, /7, 8/);
});

test("unknown authoring review state does not claim compile readiness", async () => {
  const h = authoringHarness({status: "COMPLETED", stage: "COMPLETE", skill_id: "specimen", version: "1.0.0"});
  await h.context.pollSkillAuthoringJob();
  assert.doesNotMatch(h.elements.recordingStatus.textContent, /ready to compile/i);
});
