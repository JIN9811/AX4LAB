# LLM Connections Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans. Track the checks below; preserve the existing uncommitted PLC and LLM fixes.

**Goal:** Open a separate LLM Connections window with the existing Current Mode model controls, plus editable API/local endpoints, connection tests, and persistent settings.

**Architecture:** Reuse the dashboard's model-card markup and existing load/unload APIs. Add a small connection-settings service and dedicated page/script. Saved settings override deployment defaults on startup without loading models or starting experiments.

**Tech Stack:** Existing FastAPI, Pydantic, Jinja, vanilla JavaScript, httpx, pytest.

**Spec:** User-approved scope in this conversation, amended to a separate window. Current Mode loads the current runtime configuration and retains the existing presentation. API and Local LLM are editor views, not automatic backend switches.

## Global Constraints

- Keep the dashboard layout and experiment loop unchanged.
- Store overrides only in private memory; do not edit `.env` or deployment YAML.
- Preserve managed NemoClaw routing; custom local endpoints explicitly bypass managed routing.
- Never expose stored keys or send an existing key to a changed endpoint automatically.
- Save/apply only while idle; tests send a bounded standalone greeting with no tools or fallback.
- Use English UI labels. No commit or push requested.

## Approaches

The user chose a separate window rather than adding an inline form or modal. Shared card markup preserves the Current Mode appearance without loading the full experiment dashboard script.

## Review Focus

1. Changing endpoint must not leak an existing API credential.
2. Managed/custom local routing must affect actual requests, not just labels.
3. Reload/restart must retain saved settings; malformed input must not mutate them.
4. Test failures/empty replies must not show success or fall back to another provider.
5. Busy inference and stale UI refresh must not overwrite an in-flight route or unsaved edits.

### Task 1: Connection service and APIs

**Files:** `runtime/app/llm_connections.py`, `runtime/app/main.py`, `runtime/tests/unit/test_llm_connections.py`, `runtime/tests/integration/test_llm_connections_api.py`.

**Interfaces:** GET/PUT `/api/runtime/llm-connections`; POST `/api/runtime/llm-connections/test`. Request selects `openai` or `vllm`, contains a connection profile and a test role. Public responses omit credentials.

- [x] RED: persistence, invalid URLs, managed/custom dispatch, credential isolation, failed/empty response, busy refusal.
- [x] GREEN: implement validation, atomic private store, router/client updates, bounded direct probe, startup loading.
- [x] Run unit and API regressions in an isolated source snapshot with no device configuration.

### Task 2: Separate window and Current Mode

**Files:** `runtime/web/templates/index.html`, shared model-control partial, `runtime/web/templates/llm_connections.html`, `runtime/web/static/llm_connections.js`, `runtime/web/static/llm_connections.css`.

**Interfaces:** Dashboard link opens `/llm-connections` in a separate window. Current Mode reads current status; editor views use Task 1 APIs; existing key and model actions remain on their existing endpoints.

- [x] RED: page exposes a separate-window entry, existing cards, and working editor forms.
- [x] GREEN: implement Current Mode/API/Local LLM views, explicit refresh, save/apply/test feedback, no background edit replacement.
- [x] Browser: desktop and narrow viewport; actual current values, successful test, invalid form, saving/reloading, console and screenshot checks.

### Task 3: Integration and handoff

- [x] Update user instructions and distribution manifest for new files.
- [x] Run Basic CI and LLM/module regressions in the isolated snapshot. Do not invoke unrelated hardware/integration suites for this GUI change.
- [x] Fresh reviewer inspects the complete change, then fix significant findings with regression tests.
- [x] Apply web-server changes and verify the new page plus actual API/local probes. Do not run equipment.

## Execution notes

- Continuing in the explicitly selected AX4LAB main checkout; previous changes are preserved. Verification uses disposable source snapshots, as in the preceding fixes.
- No additional implementation-choice round: the user approved immediate implementation and then specified the separate-window behavior.
- Review fixes: endpoint-pinned key dialogs, provider-only overrides, leased probes,
  disabled controls during saves, and validated persisted envelopes.
- Browser verification used the existing cached Playwright/Chromium runtime against
  a device-disconnected server and a local HTTP inference fixture. Desktop
  1920x1080 and mobile 390x844 passed; main-dashboard popup entry also passed.
- Final targeted suite: 145 passed, 1 skipped (opt-in distribution archive build),
  24 pre-existing dependency/deprecation warnings. Python/JavaScript syntax and
  `git diff --check` passed. Multi-window stale-key rejection also passed in the browser.
- User subsequently approved a web restart and bounded verification. Production
  application and probes were checked during the local-model-catalog follow-up.
  No model-serving process or equipment was restarted during verification.
