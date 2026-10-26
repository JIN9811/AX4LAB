# Endpoint-based LLM connections implementation plan

> **For agentic workers:** Use test-driven-development for changes and independent review before handoff. Preserve all pre-existing worktree changes.

**Goal:** Route API and local inference by endpoint registration, not by a hard-coded model name, while retaining local Loading/Unloading controls.

**Architecture:** Stable endpoint IDs identify connections. Each record stores provider, base URL, served model ID, optional credential, capabilities and optional server-management target. Orchestrator/Worker roles refer to endpoints; backend adapters translate references into model IDs only at the HTTP boundary. Managed deployment configuration is independent of served model names.

**Tech stack:** Existing Python/FastAPI/Pydantic/httpx, YAML, and plain JavaScript templates.

**Spec:** Approved conversation design: endpoint-based inference and selection; retain model startup/shutdown; remove E4B registrations/roles/default fallback; preserve model weight files. No experiment behavior changes.

## Global constraints

- Do not delete model files, change hardware, restart production, load/unload a real model, or invoke paid inference during implementation.
- Preserve API-primary routing and endpoint-bound credential isolation.
- Preserve existing dirty changes. Do not commit/push unrelated changes.
- Migrate legacy settings in memory; persist the new schema only on explicit Save. Never rewrite historical run artifacts.
- No model discovery UI; users register the served model ID as endpoint data.
- An absent or ambiguous connection fails clearly, never selects an invented/default model.
- Keep deployment names/model repositories only as operator configuration, never model-name conditionals in routing code.

## Interfaces

- `endpoint:<id>` is a stable internal connection reference in existing `model: str` call signatures.
- Endpoint record: `{id, label, provider: openai|vllm, base_url, model, management_id: str, capabilities: {text, vision}, access_token: str|null}`. Public records omit tokens.
- Connection profiles: `{orchestrator_endpoint, worker_endpoint, orchestrator_fallback, worker_fallback}` contain endpoint IDs (empty optional fallback). Public profiles also project `base_url` for the existing endpoint-bound API key dialog.
- `GET /api/runtime/llm-connections` returns `endpoints`, `profiles`, `management_targets`, existing status metadata, and compatibility `local_models` rows.
- `PUT /api/runtime/llm-connections/endpoints/{id}` saves a record; `DELETE` rejects assigned records. Existing profile PUT saves role IDs.
- Existing model load/unload routes accept `endpoint_id` (legacy model references can resolve uniquely). Buttons remain in Current Mode and the main GUI.
- Bootstrap config `system.llm_connections.endpoints` seeds endpoint records. vLLM managed registry keys become management IDs, not served model names.

## Review focus

1. Two endpoints serving the same model must retain distinct URL/token/lifecycle identity.
2. Changing a URL must never reuse credentials from the old address or follow credential-bearing redirects.
3. Legacy profiles with a retired managed model must not invalidate unrelated API settings or resurrect E4B.
4. Saved endpoint deletion, malformed settings, and unknown old pins must fail without silently routing elsewhere.
5. A saved custom endpoint must not cause the local manager to load/unload an unrelated deployment.

## Tasks

- [x] 1. Add regression tests for endpoint identity, same-model/different-URL calls, missing registration, token isolation and managed lifecycle mapping. Run RED, implement shared endpoint resolution and HTTP-boundary adapters, run GREEN.
- [x] 2. Replace `e4b` runtime role with `worker`, normalize legacy role keys at the import boundary, remove invented Qwen defaults, seed endpoint-backed configuration and generic management IDs. Verify direct/module routing and capabilities.
- [x] 3. Implement endpoint CRUD, atomic v2 storage, legacy migration, role assignment, bounded probes and public projections. Verify restart round-trips, removal protection and retired registration handling.
- [x] 4. Update FastAPI routes and GUI to select endpoint IDs, add/edit/remove endpoint records, preserve Loading/Unloading and API enable/disable, remove E4B-specific chips. Verify interactions with mocked external I/O.
- [x] 5. Update user/system docs and startup examples. Run relevant backend/UI suites in an isolated, hardware-blocked test environment. Review changed connection paths and explicitly record the verification boundary below.

## Execution notes

Changes are made in the existing checkout because the approved task extends its substantial uncommitted connection editor. Tests use temporary state and mocked transport/process boundaries; the production process is not reloaded. The internal endpoint-reference representation preserves existing agent call signatures and recovery records; legacy concrete pins resolve only when uniquely registered.

## Verification and deployment boundary

- Final focused regression: **272 passed**, 22 existing framework/deprecation warnings, no failures/skips. Includes endpoint clients, CRUD/migration, API-key integration, management lifecycle, module routing, launcher/bootstrap, multimodal capabilities and frontend interactions.
- Tests ran with a read-only source filesystem, isolated network/PID namespaces, private device/run/temp mounts, a blank-mounted production `.env`, and temporary runtime data roots. No production stores or devices were writable/reachable.
- Rendered frontend checks used intercepted APIs at desktop and mobile sizes; no real connection probe, model start or model stop was invoked. Legacy-server responses disable mutation controls until the server is updated.
- Independent review found and prompted fixes for management-target credential rebinding, unused legacy catalog loss, and original-endpoint authentication loss after role changes. Primary and fallback-only credential retention now have regression coverage.
- Only `vllm` and `openai` are selectable runtime backends. Standalone legacy adapter files remain, but unsupported saved module overrides fail explicitly and stay visible for operator replacement.
- Scope adjustment: the full laboratory/hardware test suite was not run for this connection-only change; focused contract and integration suites were used. Real-server authentication/readiness, live model startup/shutdown, and production restart remain deployment checks, not claims made by these mocked tests.
- Model files and historical run artifacts remain untouched. No production restart, live inference, experiment, commit or push was performed.
