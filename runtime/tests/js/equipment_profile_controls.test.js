const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../web/static/windows_equipment.js"), "utf8");
const controls = source.slice(source.indexOf("async function createEquipmentProfile()"), source.indexOf("async function loadEquipmentProfileState()"));

function setup(value, api) {
  const calls = [], navigations = [];
  const ctx = vm.createContext({
    window: {prompt: () => null, confirm: () => false},
    profileItems: {selectedOptions: [{textContent: "Second UTM"}]},
    profileNameInput: {value, focus() {this.focused = true;}},
    profileApplyStatus: {textContent: ""},
    btnNewProfile: {disabled: false}, btnApplyProfile: {disabled: false}, btnDeleteProfile: {disabled: false},
    selectedEquipmentProfileId: "utm_second", selectedBridgeId: "paired-worker",
    setBusy: (button, busy) => {button.disabled = busy;},
    openEquipmentProfile: id => navigations.push(id),
    refreshConfig: async () => {},
    apiJson: async (url, options) => {
      calls.push({url, body: JSON.parse(options.body)});
      return api ? api(url, options) : {profile: {profile_id: "utm_created"}, worker_id: "paired-worker"};
    },
  });
  vm.runInContext(controls, ctx);
  return {ctx, calls, navigations};
}

test("creates from the inline name and opens only the server-confirmed profile", async () => {
  const {ctx, calls, navigations} = setup("  Second UTM  ");
  await ctx.createEquipmentProfile();
  assert.deepEqual(calls, [{url: "/api/equipment/profiles", body: {label: "Second UTM"}}]);
  assert.deepEqual(navigations, ["utm_created"]);
});

test("blank name keeps focus in the input without creating a profile", async () => {
  const {ctx, calls, navigations} = setup("   ");
  await ctx.createEquipmentProfile();
  assert.equal(calls.length, 0);
  assert.equal(navigations.length, 0);
  assert.equal(ctx.profileNameInput.focused, true);
  assert.ok(ctx.profileApplyStatus.textContent);
});

test("failed creation keeps the typed name and allows retry", async () => {
  const {ctx, navigations} = setup("Duplicate", async () => {throw new Error("Profile already exists");});
  await ctx.createEquipmentProfile();
  assert.equal(ctx.profileNameInput.value, "Duplicate");
  assert.equal(ctx.btnNewProfile.disabled, false);
  assert.equal(ctx.profileApplyStatus.textContent, "Profile already exists");
  assert.equal(navigations.length, 0);
});

test("repeated Enter or clicks cannot create twice while saving", async () => {
  let resolve;
  const pending = new Promise(done => {resolve = done;});
  const {ctx, calls} = setup("Second UTM", () => pending);
  const first = ctx.createEquipmentProfile();
  await ctx.createEquipmentProfile();
  assert.equal(calls.length, 1);
  resolve({profile: {profile_id: "utm_created"}});
  await first;
});

test("Apply uses the existing Saved Workers selection without another selector", async () => {
  const {ctx, calls} = setup("");
  await ctx.applyEquipmentProfile();
  assert.deepEqual(calls, [{url: "/api/equipment/profiles/utm_second/apply", body: {worker_id: "paired-worker"}}]);
  assert.equal(ctx.btnApplyProfile.disabled, false);
});

test("cancelled deletion shows the exact profile name and makes no request", async () => {
  const {ctx, calls, navigations} = setup("");
  let message;
  ctx.window.confirm = text => {message = text; return false;};
  await ctx.deleteEquipmentProfile();
  assert.ok(message.includes("Second UTM"));
  assert.equal(calls.length, 0);
  assert.equal(navigations.length, 0);
});

test("confirmed deletion uses DELETE and returns to the server-selected profile", async () => {
  const {ctx, calls, navigations} = setup("", async (url, options) => {
    assert.equal(options.method, "DELETE");
    return {ok: true, selected_profile_id: "utm_windows_v1"};
  });
  ctx.window.confirm = () => true;
  await ctx.deleteEquipmentProfile();
  assert.deepEqual(calls, [{url: "/api/equipment/profiles/utm_second", body: {confirmed: true}}]);
  assert.deepEqual(navigations, ["utm_windows_v1"]);
});

test("blocked deletion keeps the profile open and permits retry", async () => {
  const {ctx, navigations} = setup("", async () => {throw new Error("Equipment job is active");});
  ctx.window.confirm = () => true;
  await ctx.deleteEquipmentProfile();
  assert.equal(ctx.profileApplyStatus.textContent, "Equipment job is active");
  assert.equal(ctx.btnDeleteProfile.disabled, false);
  assert.equal(navigations.length, 0);
});

test("protected profile cannot open confirmation or send a deletion request", async () => {
  const {ctx, calls} = setup("");
  ctx.btnDeleteProfile.disabled = true;
  ctx.window.confirm = () => {throw new Error("Protected profile must not open confirmation");};
  await ctx.deleteEquipmentProfile();
  assert.equal(calls.length, 0);
});

test("Delete Profile label is restored when busy state ends after a failed request", () => {
  const button = {id: "btn-equipment-delete-profile", textContent: "Delete Profile", dataset: {}, disabled: false};
  const context = vm.createContext({document: {
    getElementById: id => id === button.id ? button : null,
    querySelectorAll: () => [],
  }});
  const declarations = [...source.matchAll(/^const btn\w+ = document\.getElementById\([^\n]+/gm)].map(match => match[0]).join("\n");
  vm.runInContext(declarations + "\n" + source.slice(source.indexOf("function setBusy("), source.indexOf("function writeLog(")), context);
  context.rememberButtonLabels();
  context.setBusy(button, true);
  context.setBusy(button, false);
  assert.equal(button.textContent, "Delete Profile");
  assert.equal(button.disabled, false);
});
