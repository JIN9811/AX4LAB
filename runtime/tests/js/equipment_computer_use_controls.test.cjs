"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.join(__dirname, "../..");

function source(file) {
  return fs.readFileSync(path.join(root, "web/static", file), "utf8");
}

function block(file, start, end) {
  const text = source(file);
  const first = text.indexOf(start);
  const last = text.indexOf(end, first);
  assert.notEqual(first, -1, `${start} must exist in ${file}`);
  assert.notEqual(last, -1, `${end} must follow ${start} in ${file}`);
  return text.slice(first, last);
}

function expectedSettingsPayload(values) {
  const maxTurns = Number(values.maxTurns);
  const requestTimeout = Number(values.requestTimeout);
  const frameMaxAge = Number(values.frameMaxAge);
  return {
    vision_link_enabled: values.visionLinkEnabled === true,
    execution_mode: values.mode,
    computer_use: {max_turns: maxTurns, request_timeout_s: requestTimeout, frame_max_age_s: frameMaxAge},
  };
}

test("Computer-use settings use one shared browser serializer on both existing pages", () => {
  const helperPath = path.join(root, "web/static/equipment_computer_use_settings.js");
  assert.equal(fs.existsSync(helperPath), true, "shared computer-use settings helper must exist");
  const helper = require(helperPath);
  assert.deepEqual(helper.payload({
    mode: "computer_use", maxTurns: "24", requestTimeout: "80", frameMaxAge: "40", visionLinkEnabled: true,
  }), {
    vision_link_enabled: true,
    execution_mode: "computer_use",
    computer_use: {max_turns: 24, request_timeout_s: 80, frame_max_age_s: 40},
  });
  assert.throws(() => helper.payload({
    mode: "automatic", maxTurns: "24", requestTimeout: "80", frameMaxAge: "40", visionLinkEnabled: true,
  }), /Execution mode/);
  assert.throws(() => helper.payload({
    mode: "computer_use", maxTurns: "0", requestTimeout: "80", frameMaxAge: "40", visionLinkEnabled: true,
  }), /Max turns/);
  assert.match(source("windows_equipment.js"), /AX4LABEquipmentComputerUseSettings\.payload/);
  assert.match(source("runtime_ide.js"), /AX4LABEquipmentComputerUseSettings\.payload/);
  assert.doesNotMatch(source("windows_equipment.js"), /function computerUseSettingsPayload/);
  assert.doesNotMatch(source("runtime_ide.js"), /function runtimeComputerUseSettingsPayload/);
  for (const template of ["windows_equipment.html", "runtime_ide.html"]) {
    const html = fs.readFileSync(path.join(root, "web/templates", template), "utf8");
    assert.match(html, /\/static\/equipment_computer_use_settings\.js/);
  }
});

test("Equipment Workspace serializes bounded next-execution settings without launching anything", async () => {
  const calls = [];
  let sharedPayloadCalls = 0;
  let localPayloadCalls = 0;
  const context = vm.createContext({
    selectedEquipmentProfileId: "profile-a",
    selectedEquipmentSkill: {skill_id: "demo", version: "1.0.0"},
    computerUseModeInput: {value: "computer_use"},
    computerUseMaxTurnsInput: {value: "32"},
    computerUseRequestTimeoutInput: {value: "90"},
    computerUseFrameMaxAgeInput: {value: "45"},
    equipmentVisionLinkInput: {checked: true},
    computerUseSettingsStatus: {textContent: "", dataset: {}},
    computerUseReadinessOutput: {textContent: "", dataset: {}},
    btnSaveComputerUseSettings: {disabled: false},
    renderComputerUseSettings() {},
    renderComputerUseReadiness() {},
    setBusy(button, busy) { button.disabled = busy; },
    apiJson: async (url, options = {}) => {
      calls.push({url, method: options.method || "GET", body: options.body ? JSON.parse(options.body) : null});
      if (url.includes("readiness")) return {ready: true, blockers: []};
      return {workspace_settings: {
        vision_link_enabled: true,
        execution_mode: "computer_use",
        computer_use: {max_turns: 32, request_timeout_s: 90, frame_max_age_s: 45},
      }};
    },
    refreshComputerUseReadiness: async () => {
      const url = "/api/equipment/profiles/profile-a/computer-use-readiness?skill_id=demo&version=1.0.0";
      return context.apiJson(url);
    },
    encodeURIComponent,
    URLSearchParams,
    Number,
    Error,
    window: {AX4LABEquipmentComputerUseSettings: {payload(values) {
      sharedPayloadCalls += 1;
      return expectedSettingsPayload(values);
    }}},
    computerUseSettingsPayload(values) {
      localPayloadCalls += 1;
      return expectedSettingsPayload(values);
    },
  });
  vm.runInContext(block("windows_equipment.js", "async function saveComputerUseSettings", "async function loadEquipmentProfileState"), context);

  await context.saveComputerUseSettings();

  assert.deepEqual(calls.map(({url, method, body}) => ({url, method, body})), [
    {
      url: "/api/equipment/profiles/profile-a/settings",
      method: "POST",
      body: {
        vision_link_enabled: true,
        execution_mode: "computer_use",
        computer_use: {max_turns: 32, request_timeout_s: 90, frame_max_age_s: 45},
      },
    },
    {
      url: "/api/equipment/profiles/profile-a/computer-use-readiness?skill_id=demo&version=1.0.0",
      method: "GET",
      body: null,
    },
  ]);
  assert.equal(calls.some(({url}) => /agentic-run|models\/load|run-program|\/test(?:\?|$)/.test(url)), false);
  assert.match(context.computerUseSettingsStatus.textContent, /next execution/i);
  assert.equal(sharedPayloadCalls, 1);
  assert.equal(localPayloadCalls, 0);
});

test("Equipment Workspace rejects invalid bounded values before saving", () => {
  const helperPath = path.join(root, "web/static/equipment_computer_use_settings.js");
  assert.equal(fs.existsSync(helperPath), true, "shared computer-use settings helper must exist");
  const helper = require(helperPath);
  assert.throws(() => helper.payload({
    mode: "computer_use", maxTurns: "0", requestTimeout: "120", frameMaxAge: "150", visionLinkEnabled: false,
  }), /Max turns/);
  assert.throws(() => helper.payload({
    mode: "computer_use", maxTurns: "64", requestTimeout: "NaN", frameMaxAge: "150", visionLinkEnabled: false,
  }), /Request timeout/);
  assert.throws(() => helper.payload({
    mode: "other", maxTurns: "64", requestTimeout: "120", frameMaxAge: "150", visionLinkEnabled: false,
  }), /Execution mode/);
});

test("Equipment Workspace restores the new settings button label after save", () => {
  const names = [
    "btnNewProfile", "btnApplyProfile", "btnDeleteProfile", "btnScan", "btnRefresh", "btnTest", "btnProgram1", "btnUtm", "btnAbort",
    "btnScreenshot", "btnListLocators", "btnCaptureLocator", "btnLoadUtmProfile", "btnSaveUtmProfile", "btnOpenBridgeGui", "btnLocalStart",
    "btnLocalStop", "btnLocalHealth", "btnLocalSelect", "btnReadiness", "btnLivePreflight", "btnLiveValidation", "btnVisionProofDraft",
    "btnLivePhysicalValidation", "btnEvidenceAudit", "btnProofPackage", "btnVerifyProofPackage", "btnCompletionAudit", "btnRequestLog",
    "btnAgenticRun", "btnAgenticStop",
  ];
  const button = {id: "btn-equipment-save-computer-use-settings", disabled: false, textContent: "Save Settings", dataset: {}};
  const values = Object.fromEntries(names.map(name => [name, null]));
  const context = vm.createContext({
    ...values,
    btnSaveComputerUseSettings: button,
    document: {querySelectorAll: () => []},
  });
  vm.runInContext(block("windows_equipment.js", "function setBusy", "function writeLog"), context);

  context.rememberButtonLabels();
  context.setBusy(button, true);
  context.setBusy(button, false);

  assert.equal(button.textContent, "Save Settings");
});

test("Runtime IDE serializes through the shared profile settings contract", async () => {
  const elements = {
    "ide-computer-use-settings-status": {textContent: ""},
    "ide-computer-use-readiness": {textContent: "Unavailable · worker capability missing"},
    "ide-equipment-execution-mode": {value: "computer_use"},
    "ide-computer-use-max-turns": {value: "9"},
    "ide-computer-use-request-timeout": {value: "30"},
    "ide-computer-use-frame-max-age": {value: "20"},
    "ide-equipment-vision-link": {checked: true},
  };
  let sharedPayloadCalls = 0;
  let localPayloadCalls = 0;
  let posted = null;
  const context = vm.createContext({
    runtimeEquipmentFlowProfileId: "profile-a",
    document: {getElementById: id => elements[id]},
    requestJson: async (_url, options) => { posted = JSON.parse(options.body); },
    loadRuntimeEquipmentSkillFlow: async () => {},
    resetRuntimeComputerUseDraft() {},
    encodeURIComponent,
    JSON,
    Number,
    Error,
    window: {AX4LABEquipmentComputerUseSettings: {payload(values) {
      sharedPayloadCalls += 1;
      return expectedSettingsPayload(values);
    }}},
    runtimeComputerUseSettingsPayload(values) {
      localPayloadCalls += 1;
      return expectedSettingsPayload(values);
    },
  });
  vm.runInContext(block("runtime_ide.js", "async function saveRuntimeComputerUseSettings", "function renderRuntimeEquipmentSkillFlow"), context);

  await context.saveRuntimeComputerUseSettings();

  assert.deepEqual(posted, {
    vision_link_enabled: true,
    execution_mode: "computer_use",
    computer_use: {max_turns: 9, request_timeout_s: 30, frame_max_age_s: 20},
  });
  assert.equal(sharedPayloadCalls, 1);
  assert.equal(localPayloadCalls, 0);
});

test("Runtime IDE preserves both next-execution confirmation and readiness blockers after save", async () => {
  const elements = {
    "ide-computer-use-settings-status": {textContent: ""},
    "ide-computer-use-readiness": {textContent: "Unavailable · initial"},
    "ide-equipment-execution-mode": {value: "computer_use"},
    "ide-computer-use-max-turns": {value: "18"},
    "ide-computer-use-request-timeout": {value: "75"},
    "ide-computer-use-frame-max-age": {value: "35"},
    "ide-equipment-vision-link": {checked: true},
  };
  const context = vm.createContext({
    runtimeEquipmentFlowProfileId: "profile-a",
    document: {getElementById: id => elements[id]},
    requestJson: async () => ({ok: true}),
    resetRuntimeComputerUseDraft() {},
    loadRuntimeEquipmentSkillFlow: async () => {
      elements["ide-computer-use-settings-status"] = {textContent: ""};
      elements["ide-computer-use-readiness"] = {textContent: "Unavailable · worker capability missing"};
    },
    encodeURIComponent,
    JSON,
    Number,
    Error,
    window: {AX4LABEquipmentComputerUseSettings: {payload: expectedSettingsPayload}},
  });
  vm.runInContext(block("runtime_ide.js", "async function saveRuntimeComputerUseSettings", "function renderRuntimeEquipmentSkillFlow"), context);

  await context.saveRuntimeComputerUseSettings();

  assert.match(elements["ide-computer-use-settings-status"].textContent, /next execution/i);
  assert.match(elements["ide-computer-use-settings-status"].textContent, /pins remain unchanged/i);
  assert.match(elements["ide-computer-use-readiness"].textContent, /worker capability missing/i);
});

test("Runtime IDE renders readiness independently from transient save status", () => {
  const equipmentFlowOutput = {innerHTML: ""};
  const context = vm.createContext({
    equipmentFlowOutput,
    runtimeEquipmentFlowPayload: {
      flow: {blocks: []}, execution: {}, vision_tasks: [],
      workspace_settings: {execution_mode: "computer_use", computer_use: {}},
      computer_use_readiness: {ready: false, blockers: [{message: "Worker capability missing"}]},
      readiness: {ready: false},
    },
    runtimeEquipmentProfiles: [{profile_id: "profile-a", label: "Profile A"}],
    runtimeEquipmentFlowProfileId: "profile-a",
    document: {getElementById: () => null},
    escapeHtml(value) { return String(value); },
    runtimeComputerUseValuesForRender: () => ({
      mode: "computer_use", maxTurns: "64", requestTimeout: "120", frameMaxAge: "150", visionLinkEnabled: false,
    }),
    bindRuntimeComputerUseDraftControls() {},
  });
  vm.runInContext(block("runtime_ide.js", "function renderRuntimeEquipmentSkillFlow", "async function loadRuntimeEquipmentSkillFlow"), context);

  context.renderRuntimeEquipmentSkillFlow();

  const readiness = equipmentFlowOutput.innerHTML.match(/id="ide-computer-use-readiness"[^>]*>([^<]*)<\/p>/);
  const saveStatus = equipmentFlowOutput.innerHTML.match(/id="ide-computer-use-settings-status"[^>]*>([^<]*)<\/p>/);
  assert.ok(readiness, "Runtime IDE must render a dedicated readiness element");
  assert.match(readiness[1], /Worker capability missing/);
  assert.ok(saveStatus, "Runtime IDE must render a separate save-status element");
  assert.doesNotMatch(saveStatus[1], /Worker capability missing/);
});

test("Runtime IDE same-profile polling preserves dirty values and focused field until save or profile change", () => {
  const elements = {
    "ide-computer-use-settings-form": {dataset: {profileId: "profile-a"}},
    "ide-equipment-execution-mode": {id: "ide-equipment-execution-mode", value: "computer_use"},
    "ide-computer-use-max-turns": {id: "ide-computer-use-max-turns", value: "19", selectionStart: 1, selectionEnd: 2},
    "ide-computer-use-request-timeout": {id: "ide-computer-use-request-timeout", value: "77"},
    "ide-computer-use-frame-max-age": {id: "ide-computer-use-frame-max-age", value: "33"},
    "ide-equipment-vision-link": {id: "ide-equipment-vision-link", checked: true},
  };
  let focused = "";
  const document = {
    activeElement: elements["ide-computer-use-max-turns"],
    getElementById(id) { return elements[id] || null; },
  };
  const context = vm.createContext({runtimeEquipmentFlowProfileId: "profile-a", runtimeComputerUseDraft: null, document});
  vm.runInContext(block("runtime_ide.js", "function runtimeComputerUseFormValues", "async function saveRuntimeComputerUseSettings"), context);

  context.captureRuntimeComputerUseDraft(true);
  const values = context.runtimeComputerUseValuesForRender({
    execution_mode: "skill_flow",
    computer_use: {max_turns: 64, request_timeout_s: 120, frame_max_age_s: 150},
    vision_link_enabled: false,
  });
  assert.deepEqual(JSON.parse(JSON.stringify(values)), {
    mode: "computer_use", maxTurns: "19", requestTimeout: "77", frameMaxAge: "33", visionLinkEnabled: true,
  });

  elements["ide-computer-use-max-turns"] = {
    id: "ide-computer-use-max-turns", value: "19",
    focus() { focused = this.id; },
    setSelectionRange(start, end) { this.selectionStart = start; this.selectionEnd = end; },
  };
  context.restoreRuntimeComputerUseDraftFocus();
  assert.equal(focused, "ide-computer-use-max-turns");
  assert.equal(elements["ide-computer-use-max-turns"].selectionStart, 1);
  assert.equal(elements["ide-computer-use-max-turns"].selectionEnd, 2);

  context.runtimeEquipmentFlowProfileId = "profile-b";
  const changedProfile = context.runtimeComputerUseValuesForRender({
    execution_mode: "skill_flow",
    computer_use: {max_turns: 8, request_timeout_s: 20, frame_max_age_s: 10},
    vision_link_enabled: false,
  });
  assert.equal(changedProfile.mode, "skill_flow");
  assert.equal(changedProfile.maxTurns, "8");

  context.runtimeEquipmentFlowProfileId = "profile-a";
  context.resetRuntimeComputerUseDraft();
  const reset = context.runtimeComputerUseValuesForRender({
    execution_mode: "skill_flow",
    computer_use: {max_turns: 64, request_timeout_s: 120, frame_max_age_s: 150},
    vision_link_enabled: false,
  });
  assert.equal(reset.mode, "skill_flow");
  assert.equal(reset.maxTurns, "64");
});

test("Equipment Workspace passive polling does not rehydrate the settings form", () => {
  const text = source("windows_equipment.js");
  const polling = text.slice(text.indexOf("window.setInterval"));
  assert.doesNotMatch(polling, /loadEquipmentProfileState\(/);
  assert.match(polling, /refreshEquipmentRuntime\(\)/);
  assert.match(polling, /refreshEquipmentSkillFlowRuntime\(\)/);
});

test("progress projection preserves relationships while hostile model text stays text", () => {
  const context = vm.createContext({});
  vm.runInContext(block("windows_equipment.js", "function computerUseProgressView", "function renderEquipmentRuntimeOverview"), context);
  const hostile = '<img src=x onerror="globalThis.pwned=true">';
  const view = context.computerUseProgressView({
    metadata: {skill_execution: {computer_use: {turn: 4, kind: hostile, observation_id: "obs-4"}}},
    raw_result: {
      computer_use: {turns: 4, request_log_ref: "/safe/evidence"},
      output_artifacts: [{kind: "computer_use_step", local_path: "/safe/step.json", sha256: "abc"}],
    },
  });
  assert.deepEqual(JSON.parse(JSON.stringify(view)), {
    visible: true,
    turn: 4,
    action: hostile,
    observationId: "obs-4",
    evidenceRef: "/safe/evidence",
    artifacts: [{kind: "computer_use_step", localPath: "/safe/step.json", sha256: "abc"}],
  });
  const output = {textContent: "", hidden: true};
  context.renderComputerUseProgress(output, view);
  assert.equal(output.hidden, false);
  assert.ok(output.textContent.includes(hostile));
  assert.equal(context.pwned, undefined);
});

test("Skill policy JSON remains versioned workflow data and rejects malformed editor input", () => {
  const editor = require("../../web/static/equipment_skill_workflow_editor.js");
  const policy = {schema: "ax4lab.equipment_computer_use.policy.v1", postconditions: [{type: "image"}]};
  assert.deepEqual(editor.parseComputerUsePolicy(editor.serializeComputerUsePolicy(policy)), policy);
  assert.equal(editor.parseComputerUsePolicy("   "), null);
  assert.throws(() => editor.parseComputerUsePolicy("{not json}"), /valid JSON/i);
  const hostile = {application: {window_title: "</textarea><script>globalThis.pwned=true</script>"}};
  assert.deepEqual(editor.parseComputerUsePolicy(editor.serializeComputerUsePolicy(hostile)), hostile);
  assert.equal(globalThis.pwned, undefined);
});
