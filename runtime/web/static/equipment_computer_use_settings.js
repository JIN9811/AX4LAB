(function equipmentComputerUseSettingsFactory(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.AX4LABEquipmentComputerUseSettings = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function equipmentComputerUseSettings() {
  "use strict";

  function payload(values) {
    const mode = String(values?.mode || "");
    if (!["skill_flow", "computer_use"].includes(mode)) throw new Error("Execution mode is invalid.");
    const maxTurns = Number(values?.maxTurns);
    const requestTimeout = Number(values?.requestTimeout);
    const frameMaxAge = Number(values?.frameMaxAge);
    if (!Number.isInteger(maxTurns) || maxTurns < 1 || maxTurns > 256) throw new Error("Max turns must be an integer from 1 to 256.");
    if (!Number.isFinite(requestTimeout) || requestTimeout < 1 || requestTimeout > 300) throw new Error("Request timeout must be from 1 to 300 seconds.");
    if (!Number.isFinite(frameMaxAge) || frameMaxAge < 1 || frameMaxAge > 600) throw new Error("Frame max age must be from 1 to 600 seconds.");
    return {
      vision_link_enabled: values?.visionLinkEnabled === true,
      execution_mode: mode,
      computer_use: {max_turns: maxTurns, request_timeout_s: requestTimeout, frame_max_age_s: frameMaxAge},
    };
  }

  return Object.freeze({payload});
});
