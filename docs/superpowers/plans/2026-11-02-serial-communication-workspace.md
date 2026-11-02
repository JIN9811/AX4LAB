# Serial Communication Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An AX4LAB-hosted, folder-discovered serial-device workspace with saved port selection, shared API, receive/request sessions, and downloadable logs.

**Architecture:** A standalone Python serial core owns installed module discovery, profiles, port ownership, parsing, and bounded sessions. A thin FastAPI router and existing-style HTML/JS workspace consume that core. Device-specific defaults, icons, field metadata, and parsers live inside each installed module directory.

**Tech Stack:** Python 3.11+, pySerial, PyYAML, FastAPI/Pydantic, existing Jinja/static CSS/JS; pytest, pseudo-terminals, browser tests.

**Spec:** `docs/superpowers/specs/2026-11-02-serial-communication-workspace-design.md`

## Global Constraints

- No experimental-loop changes, equipment motion, automatic physical connection, or server restart.
- AX4LAB loopback-only API; no browser WebSerial, remote forwarding, or new public listener.
- Independent core: inject config/log paths, port enumerator, and transport factory.
- Module icons, settings, defaults, value labels, and capabilities are discovered from module folders, never a GUI device switch/list.
- Set saves config atomically; connection retains its old snapshot until explicit reconnect.
- Qm passive reception; CAS requests exactly `P`. Raw evidence retained; unsupported semantics stay unknown.
- Preserve the existing dirty checkout. No shared-branch push or broad staging.

## Review Focus

1. A USB path reused by a different device must not inherit the saved identity (Task 2).
2. Corrupt config or disk-full must not silently reset settings or claim complete logs (Tasks 1/2).
3. Module deletion/duplicate IDs/missing icons must not erase profiles or break all device pages (Tasks 1/4).
4. Concurrent tabs, read requests, polling, and disconnect must not duplicate writes or strand a port (Task 2).
5. Cross-origin/remote requests and asset/log traversal must not gain access through convenience routes (Task 3).

## Task 1: Module catalog, protocol parsers, and profile persistence

**Files:** `runtime/device_bridges/serial_communication/{__init__,catalog,profiles,errors}.py`, `modules/{qm_indicator,cas_mwii_plus}/{module.yaml,protocol.py,icon.svg}`; `runtime/tests/unit/test_serial_catalog_profiles.py`, `test_serial_protocols.py`.

**Interfaces:** `ModuleCatalog(root=None).refresh()/list()/get(module_id)/protocol(module_id,variant)`; `ProfileStore(path).list()/get(id)/create(data)/update(id,data,revision)/delete(id,revision)`; parser `feed(bytes)->list[dict]`, `request()->bytes|None`, `reset()`; `SerialError(code,message)`.

- [ ] Write tests proving third-folder discovery, duplicate/bad descriptor isolation, icon path containment, persisted Set/revision conflicts, and corrupt-file preservation.
- [ ] Write literal protocol fixtures: CAS 8.56 g and spaced negative values, date/partial/combined lines; Qm 42/52/observed60 frames, checksum errors, unknown fields, resynchronization.
- [ ] Run new tests: expect failures because the package does not yet exist.
- [ ] Implement catalog validation, contained local plugin loading, atomic profile JSON, and module-local parsers/defaults/icons. Protocol imports never happen on scan.
- [ ] Run both files; all tests must pass.

## Task 2: Transport, sessions, recording, service

**Files:** package `{transport,recording,session,service}.py`; `runtime/tests/unit/test_serial_service.py`, `runtime/tests/integration/test_serial_pty.py`.

**Interfaces:** `SerialService(config_path,log_root,*,catalog_root=None,port_provider=None,transport_factory=None)` exposing module/profile CRUD, `ports()`, `connect(id)`, `disconnect(id)`, `status(id)`, `latest(id)`, `events(id,after)`, `read(id,timeout_s)`, `polling(id,enabled,interval_s)`, `record(id,enabled)`, `recordings()`, `recording_file(id,name)`, `shutdown()`.

- [ ] Write fake-transport behavior tests for two profiles, alias ownership, Set while connected, request once, cached-value rejection, timeout, polling, concurrent reads, disconnect/unplug, and error recovery.
- [ ] Write persistence/log tests for bounded event gaps, raw RX/TX and parsed export, completed/incomplete manifests, writer errors, and no log path traversal.
- [ ] Run tests and confirm RED.
- [ ] Implement read-only enumeration and explicit exclusive-open transport, bounded session readers and writer queues, atomic manifests, service ownership, and cooperative shutdown.
- [ ] Add a real pseudo-terminal test without physical device access and run all serial tests GREEN.

## Task 3: API and AX4LAB integration

**Files:** package `{api,module,host}.py`, `runtime/app/main.py`, `runtime/pyproject.toml`, package `requirements.txt`; `runtime/tests/integration/test_serial_api.py`.

**Interfaces:** `create_router(service, templates=None)->APIRouter`; `install_serial_workspace(app, paths, templates)->None` creates a lazy service binding, routes, and shutdown cleanup only. Existing `BridgeModule MODULE` describes the package without importing hardware libraries.

- [ ] Write API tests on a minimal FastAPI host with temporary stores and fake transports; test module catalog, CRUD/Set, connect/read/logs, errors, remote/cross-origin rejection, and icon containment.
- [ ] Run tests RED; implement routes from the spec and isolated loopback guard without changing unrelated host routes.
- [ ] Register the thin adapter in the existing app and metadata discovery. Declare pySerial as an install extra plus bridge requirements; absent pySerial must not prevent startup.
- [ ] Run API and serial suite GREEN; run existing module-discovery regressions.

## Task 4: Workspace UI and documentation

**Files:** `runtime/web/templates/serial.html`, `runtime/web/static/serial_workspace.{js,css}`, `runtime/web/templates/index.html`, package `README.md`, `docs/gui/serial_communication.md`; browser test outside source checkout.

**Interfaces:** shared GUI consumes `/api/serial/modules`, module field/action metadata, and existing service routes; `/serial?module_id=...&profile_id=...` selects the device view. No hardcoded device IDs.

- [ ] Write route/render tests for catalog entry and device shell, plus JS/browser cases for module navigation, port dropdown, Set/reload, unavailable devices, and delete confirmation.
- [ ] Run missing-route/assets tests RED, then implement compact AX4LAB-style catalog and per-module connection/communications/logging view. Poll incrementally at 5 Hz only while visible, serialize fetches, and retain unsaved form input.
- [ ] Document module folder contract/template, API examples, manual sources, provisional Qm fields, private port storage, and no loop/hardware integration.
- [ ] Test in a standalone loopback fixture app with temporary config and fake transport. Browser plugin unavailable: use installed Playwright, desktop and mobile screenshots outside repo.

## Task 5: Final verification and review

- [ ] Run all serial unit/API/pseudo-terminal tests, module-contract regressions, JS syntax checks, and the project's default pytest command in a hardware-denied isolated environment; report baseline/collection failures rather than modifying unrelated logic.
- [ ] Request one fresh-context implementation review; fix important findings with RED→GREEN regression tests.
- [ ] Check scoped diff, no unrelated file changes, no secrets/device IDs in tracked defaults, no physical connections or server restart.
- [ ] Leave a clear completion record with tests and remaining deployment/hardware verification limits. No push was requested.

## Execution decisions

- User explicitly requested plan followed immediately by code; proceed inline without another plan-approval pause.
- Checkpoint commits are limited to this task in its isolated branch, if worktree consent is provided. Do not commit the pre-existing dirty changes in the user's checkout.
