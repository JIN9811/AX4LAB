# Local Model Catalog Implementation Plan

> Use superpowers:executing-plans for inline implementation and bounded verification.

**Goal:** Simplify LLM Control and discover/register local models from endpoints.

**Architecture:** Extend the private connection store with a local model catalog.
Resolve model routes in the existing vLLM client; share catalog-driven cards
between the dashboard and separate connections window.

**Tech Stack:** Existing FastAPI/Pydantic/httpx, Jinja, vanilla JavaScript.

**Spec:** Conversation: vLLM without NemoClaw branding, Agent Work/Ready,
endpoint discovery and selected-model add/remove, synchronized model lists.
User requested immediate restart and simple verification.

## Global Constraints

- Remove registrations only, never model files or running model servers.
- Preserve managed lifecycle and external API routing.
- Do not forward credentials between endpoints or follow redirects.
- Preserve existing settings and unrelated uncommitted changes.
- Restart only the idle web server; no equipment actions.
- Bounded smoke checks only; no full suite or experiment loop.
- No commit or push requested.

## Review Focus

- Failed discovery must not erase the saved catalog.
- Assigned models require a replacement before removal.
- Custom routes bypass provisioning and isolate credentials.
- Existing managed entries retain load/unload controls.
- Both windows reflect the same saved catalog after reload.

## Task 1: Catalog and discovery

Files: app/llm_connections.py, app/main.py, backends/vllm_client.py,
tests/unit/test_llm_connections.py, tests/integration/test_llm_connections_api.py.

- [x] RED: discovery, persistence/removal, assigned-model and credential protection.
- [x] GREEN: catalog store, GET /models discovery, register/remove APIs, custom model routing.
- [x] Run focused connection tests in an isolated snapshot.

## Task 2: UI and deployment

Files: llm_control partial, llm_connections HTML/JS/CSS, app.js,
llm_model_cards.js, configs/models.yaml, docs/gui/gui.md, distribution-files.json.

- [x] Endpoint discovery and registered list drive roles and both card surfaces.
- [x] Visible vLLM and Agent Work/Ready labels.
- [x] Browser smoke: discover/add/remove, cards, reload, console.
- [x] Bounded independent review and important fixes.
- [x] Web restart, idle state, production page and one real response.

## Execution ledger

Continue the selected checkout; use isolated fixture server for device-free tests.
No extra approval round: user requested restart and verification immediately.
Existing managed models are seeded without changing their running state.

- Focused checks: 27 connection unit tests and 11 connection/key API tests passed.
- Browser plugin not available; cached Playwright/Chromium used. Isolated UI flow
  passed at 1920x1080 and 390x844, including both card surfaces and reload persistence.
- Review fixes cover endpoint-token reuse/redaction, managed re-registration and
  catalog refresh after load/unload. No full suite or hardware actions were run.
- Production was an unresponsive autoreload process; its latest planning store
  had no execution requests. Replaced only that web process, with reload disabled.
  Production returns idle; loaded 31B and unloaded E4B states were retained.
- Actual 31B model discovery and short reply succeeded (0.48 s).
- Added remote-endpoint instructions to the existing GUI guide, English/Korean
  operator walkthroughs, installation guide and cheat sheet; no new document hierarchy.
