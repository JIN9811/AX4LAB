"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const {
  agenticRunTerminalBadgeView,
  candidateSelectionView,
  confirmCandidateSelection,
  equipmentProfileView,
  profileConnectionStatus,
  selectedCandidatesFirst,
  skillIdFromRecordingName,
} = require("../../web/static/windows_equipment_selection.js");

test("workspace name and link use the viewed profile without changing the applied profile", () => {
  const payload = {selected_profile_id: "utm_a", profiles: [
    {profile_id: "utm_a", label: "UTM A"}, {profile_id: "utm_b", label: "UTM B"},
  ]};
  assert.deepEqual(equipmentProfileView(payload, "utm_b"), {
    profileId: "utm_b", label: "UTM B", href: "/equipment/windows?profile_id=utm_b",
  });
  assert.equal(payload.selected_profile_id, "utm_a");
});

test("a removed viewed profile falls back to the server-applied profile and its current name", () => {
  assert.deepEqual(equipmentProfileView({selected_profile_id: "utm_a", profiles: [
    {profile_id: "utm_a", label: "Renamed UTM"},
  ]}, "removed"), {profileId: "utm_a", label: "Renamed UTM", href: "/equipment/windows?profile_id=utm_a"});
});

test("missing profiles cannot invent a device name or a stale profile link", () => {
  assert.deepEqual(equipmentProfileView({profiles: []}, "removed"), {
    profileId: "", label: "No profile selected", href: "/equipment/windows",
  });
});

test("selected candidate view is explicit, disabled, and accessible", () => {
  const selected = candidateSelectionView({
    candidate_alias: "windows_192.168.50.40_Nextpc",
    selected: true,
  });
  const standby = candidateSelectionView({
    candidate_alias: "windows_192.168.50.58",
    selected: false,
  });

  assert.deepEqual(selected, {
    selected: true,
    cardClass: "equipment-candidate-card selected",
    ariaCurrent: "true",
    buttonText: "Selected",
    buttonDisabled: true,
    buttonClass: "btn mini primary",
    ariaPressed: "true",
  });
  assert.deepEqual(standby, {
    selected: false,
    cardClass: "equipment-candidate-card",
    ariaCurrent: null,
    buttonText: "Select",
    buttonDisabled: false,
    buttonClass: "btn mini",
    ariaPressed: "false",
  });
});

test("selection confirmation rejects application failure and alias mismatch", () => {
  const requested = "windows_192.168.50.40_Nextpc";
  assert.equal(
    confirmCandidateSelection(
      { ok: true, selected: true, selected_candidate: requested },
      requested,
    ).selected_candidate,
    requested,
  );
  assert.throws(
    () => confirmCandidateSelection(
      { ok: false, failure_code: "PYAUTOGUI_CANDIDATE_NOT_FOUND" },
      requested,
    ),
    /PYAUTOGUI_CANDIDATE_NOT_FOUND/,
  );
  assert.throws(
    () => confirmCandidateSelection(
      { ok: true, selected: true, selected_candidate: "windows_other" },
      requested,
    ),
    /did not confirm requested candidate/,
  );
});

test("profile connection display derives selected state when status is absent", () => {
  assert.equal(profileConnectionStatus({ selected: true }), "selected");
  assert.equal(profileConnectionStatus({ selected: true, status: "unknown" }), "selected");
  assert.equal(profileConnectionStatus({ selected: false }), "missing");
  assert.equal(profileConnectionStatus({ selected: true, status: "ready" }), "ready");
});

test("saved candidates put the selected worker first without changing standby order", () => {
  const candidates = [
    { candidate_alias: "worker-a", selected: false },
    { candidate_alias: "worker-b", selected: true },
    { candidate_alias: "worker-c", selected: false },
  ];

  const ordered = selectedCandidatesFirst(candidates);

  assert.deepEqual(ordered.map((candidate) => candidate.candidate_alias), ["worker-b", "worker-a", "worker-c"]);
  assert.deepEqual(candidates.map((candidate) => candidate.candidate_alias), ["worker-a", "worker-b", "worker-c"]);
});

test("recording names become editable Linux Skill ID defaults", () => {
  assert.equal(skillIdFromRecordingName("Equipment demonstration", "rec-unused"), "equipment_demonstration");
  assert.equal(skillIdFromRecordingName("  UTM Test #2  ", "rec-unused"), "utm_test_2");
  assert.equal(skillIdFromRecordingName("", "rec-2026-abc"), "rec_2026_abc");
});

test("finished agentic progress runs return the live badge to idle", () => {
  assert.deepEqual(agenticRunTerminalBadgeView({ ok: true, summary: "done" }), {
    state: "idle",
    detail: "",
  });
  assert.deepEqual(agenticRunTerminalBadgeView({ ok: false, message: "blocked" }), {
    state: "idle",
    detail: "",
  });
});
