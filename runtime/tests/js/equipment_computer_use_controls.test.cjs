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

test("Equipment Workspace serializes bounded next-execution settings without launching anything", async () => {
  const calls = [];
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
    encodeURIComponent,
    URLSearchParams,
    Number,
    Error,
  });
  vm.runInContext(block("windows_equipment.js", "function computerUseSettingsPayload", "async function loadEquipmentProfileState"), context);

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
});

test("Equipment Workspace rejects invalid bounded values before saving", () => {
  const context = vm.createContext({Number, Error});
  vm.runInContext(block("windows_equipment.js", "function computerUseSettingsPayload", "async function loadEquipmentProfileState"), context);
  assert.throws(() => context.computerUseSettingsPayload({
    mode: "computer_use", maxTurns: "0", requestTimeout: "120", frameMaxAge: "150", visionLinkEnabled: false,
  }), /Max turns/);
  assert.throws(() => context.computerUseSettingsPayload({
    mode: "computer_use", maxTurns: "64", requestTimeout: "NaN", frameMaxAge: "150", visionLinkEnabled: false,
  }), /Request timeout/);
  assert.throws(() => context.computerUseSettingsPayload({
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

test("Runtime IDE serializes the same profile settings contract", () => {
  const context = vm.createContext({Number, Error});
  vm.runInContext(block("runtime_ide.js", "function runtimeComputerUseSettingsPayload", "function renderRuntimeEquipmentSkillFlow"), context);
  const payload = context.runtimeComputerUseSettingsPayload({
    mode: "computer_use", maxTurns: "9", requestTimeout: "30", frameMaxAge: "20", visionLinkEnabled: true,
  });
  assert.deepEqual(JSON.parse(JSON.stringify(payload)), {
    vision_link_enabled: true,
    execution_mode: "computer_use",
    computer_use: {max_turns: 9, request_timeout_s: 30, frame_max_age_s: 20},
  });
  assert.throws(() => context.runtimeComputerUseSettingsPayload({
    mode: "computer_use", maxTurns: "257", requestTimeout: "30", frameMaxAge: "20", visionLinkEnabled: true,
  }), /Max turns/);
});

test("Runtime IDE preserves next-execution confirmation across the flow re-render", async () => {
  const elements = {
    "ide-computer-use-settings-status": {textContent: ""},
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
    loadRuntimeEquipmentSkillFlow: async () => {
      elements["ide-computer-use-settings-status"] = {textContent: "Unavailable · fixture"};
    },
    encodeURIComponent,
    JSON,
    Number,
    Error,
  });
  vm.runInContext(block("runtime_ide.js", "function runtimeComputerUseSettingsPayload", "function renderRuntimeEquipmentSkillFlow"), context);

  await context.saveRuntimeComputerUseSettings();

  assert.match(elements["ide-computer-use-settings-status"].textContent, /next execution/i);
  assert.match(elements["ide-computer-use-settings-status"].textContent, /pins remain unchanged/i);
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
