# Serial Communication Workspace

Status: proposed design; implementation has not started.

## Intent and agreed scope

Add a Serial Communication entry to AX4LAB's existing Device Workspaces. Operators
configure serial devices, inspect received values, request measurements, and save
logs through a GUI backed by one API/service. This is an AX4LAB-hosted feature now,
with a separable core for a future standalone device workspace.

The user selected the embedded-service approach and requested:

- Qmesys UTM support based on its Indicator Manual.
- CAS MWII Plus support based on its own manual.
- A dropdown of ports currently detected by the server, with a Set button that
  persists the selected port and communication settings in each device's config.
- Shared GUI/API operations, without changing the existing experimental loop.
- An icon-based module catalog when the workspace opens. Clicking an icon opens
  that device module's settings and communication view.
- Folder-discovered device modules: no hardcoded device/icon list in the GUI, and
  adding/removing modules must not require editing the workspace shell.

No equipment motion, automatic experiment progression, changes to SEA inputs,
replacement of Qm RAW-file collection, or remote Windows port forwarding belong
to this work. Configuration is not evidence of a successful device response.

## Approaches

1. **Embedded API with an independent serial core — selected.** Reuses AX4LAB's
   server and workspace presentation, while keeping protocol and transport code
   independent of agents, controllers, run state, and FastAPI. This meets the
   present deployment request and leaves an extraction boundary.
2. **Separate serial server immediately — deferred.** Adds deployment, access
   control, and service-discovery work without a current requirement. Later
   extraction will still require lifecycle/storage/API deployment integration;
   it is not promised to be a zero-change move.

## Source evidence and protocol limits

- `docs/knowledge/manuals/sources/Indicator Manual.pdf`, pp. 43–46: ASCII 8N1,
  9600–115200 baud, LOAD/DISP1/DISP2 and optional POT fields, framing/checksum,
  units, and commands. The manual diagrams describe 42/52-byte layouts.
- Existing diagnostic capture:
  `artifacts/diagnostics/qm-rs232-20261028-192801/raw.bin`, `chunks.jsonl`, and
  `plot_fd.py`. The observed device instead has 60-byte frames. Its diagnostic
  parser uses signed fields at offsets 4/14/24/34 and a decimal checksum at
  offsets 56–58, equal to `sum(frame[1:56]) % 256`. Treat this as an explicitly
  identified captured variant, not an excuse to apply these offsets to every
  Qm frame. Channel/unit interpretation in that diagnostic remains provisional.
- CAS MWII Plus manual, revision 241219, pp. 17–24, presently downloaded as
  `/tmp/cas-mwii-plus-manual.pdf`: print modes, baud settings, terminal keys,
  and connection diagram. This temporary pathname is evidence for design, not a
  runtime dependency. Include a durable source reference in the documentation;
  do not require or republish the complete manual in the application package.
- CAS was observed working at 9600 8N1 without flow control: one uppercase `P`
  byte produces a response such as ` 14:55:57 W:    8.56 g  \r\n`. An optional
  separate date line and a spaced negative sign also occur. 8N1 is confirmed by
  the local test, not explicitly asserted by the inspected CAS manual text.

Qm protocol variants must be separately tested. Preserve unknown fields and
unsupported frames as raw evidence; never fabricate decoded device state.
Label displacement channels by their source names, not as an absolute platen
height. Only convert units with an established mapping and retain original values
and codes. The workspace is not a motion-planning or safety input in this version.

## Components and extraction boundary

- A core package under `runtime/device_bridges/serial_communication/` owns
  transport, profile storage interfaces, sessions, parsing, and logging. Inject
  configuration/log roots and a transport factory; no imports from `app.main`,
  agents, controllers, or global run services.
- Separate Qm and CAS parsers implement a small common interface: consume bytes,
  emit measurements/raw-frame metadata, and declare supported request commands.
- A thin API router receives a service instance from AX4LAB integration. It maps
  typed inputs/results to HTTP without implementing serial I/O itself.
- The existing HTML/CSS/JavaScript workspace pattern is reused. The GUI uses the
  same API available to future callers, never browser-local serial access.
- One server-owned session per physical device. Separate bounded I/O workers keep
  serial reads and log writes off the HTTP event loop. Importing or starting the
  server does not open any hardware.
- `pyserial` belongs to this feature's declared dependency/install path; missing
  support produces a workspace-specific error, not a failure of all AX4LAB startup.

## Device module contract and discovery

AX4LAB already discovers installed bridges through
`runtime/device_bridges/module_discovery.py` and the declarative `BridgeModule`
contract. Register Serial Communication through that existing contract; do not
turn each serial device into a new agent or modify Runtime IDE graph membership.
Its own device catalog is a subregistry, not another hardcoded main-GUI list.

Proposed package convention (builder choice, not a pre-existing format):

```text
device_bridges/serial_communication/
  module.py                  # existing AX4LAB BridgeModule declaration
  modules/
    qm_indicator/
      module.yaml            # ID, version, label, icon, settings, channels, actions
      protocol.py            # fixed protocol-factory interface
      icon.svg
    cas_mwii_plus/
      module.yaml
      protocol.py
      icon.svg
```

- Scan immediate installed module directories for `module.yaml`; schema validation
  yields the catalog served by the API. The main page renders returned entries,
  and the device page renders their declarative settings, values, and supported
  actions. No `if device == CAS/Qm` branches in the shared GUI/service.
- The descriptor defines a versioned schema, safe ID, label, icon-relative path,
  protocol variant choices, default communication settings, field/value metadata,
  and named action capabilities. Defaults now attributed to specific devices in
  this document belong in those device folders, not a central lookup table.
- Discovery reads metadata only and performs no device I/O or protocol imports.
  Protocol implementations are trusted installed code loaded through a fixed
  package-local convention when selected; editable config cannot nominate arbitrary
  Python imports, shell commands, outside files, or remote scripts.
- Icons are served by catalog ID using resolved contained paths, not arbitrary
  download URLs. Reject path traversal/escaping symlinks. One generic missing-icon
  fallback is acceptable; per-device icon mappings in the frontend are not.
- Invalid or duplicate modules produce a concise catalog diagnostic without
  preventing valid modules or the rest of AX4LAB from loading. Duplicate IDs are
  excluded rather than arbitrarily selecting one directory.
- Add a trusted module folder and refresh the catalog to discover it; remove the
  folder to remove its catalog entry. Profiles/logs are never deleted by scanning.
  An affected saved profile becomes Module unavailable. A running session holds
  its loaded version until disconnected; it cannot silently switch implementation.
  Updating already-loaded Python code requires a normal server restart in v1;
  installing/cataloguing modules is distinct from live Python hot replacement.
- Profile configuration references `module_id` and the module-defined variant.
  A module describes a device type; profiles represent configured instances. Clicking
  an icon opens existing instance settings or offers to create its first profile.
- Addition/removal here is trusted folder installation, not uploading executable
  plugins through the browser. Include a small module template/contract document
  and a test-only third module proving discovery without central registrations.

## Profiles, port dropdown, and Set

Use versioned private configuration at
`RUNTIME_PATHS.memory_root / "serial_communication_config.json"`, passed to the
core by the host. Do not hardcode `/home/jin`, device serial numbers, or currently
assigned `/dev/ttyUSB*` paths in tracked defaults.

Each profile contains an ID/name, protocol preset/variant, selected port identity,
baud/data/parity/stop/flow settings, request interval/timeout, and freshness policy.
Qm defaults to 115200 8N1 receive-only; CAS defaults to the verified 9600 8N1,
no-flow-control request mode. Both remain disconnected until Connect is pressed.

- Populate the dropdown from OS enumeration without opening ports or sending
  probes. Display the port path plus device description/USB identity when present.
  Windows-hosted enumeration may show COM names; the current Linux server shows
  its own `/dev/...` ports, regardless of the browser's OS.
- Refresh updates the list without clearing an unsaved selection. A previously
  saved but missing device remains visible as unavailable, not silently replaced.
- Known busy or inaccessible ports are shown with a concise reason and cannot
  be selected for connection. A detection result is a snapshot, not a guarantee;
  unknown ownership must not be presented as confirmed free.
- **Set** validates and atomically saves profile configuration. It sends no bytes,
  does not connect, and does not interrupt an existing session. Failed persistence
  must not display Saved. Use a config revision to reject stale concurrent edits.
- Saving while connected updates saved configuration only. Show a short
  Reconnect to apply status and retain the active config snapshot. The next
  explicit Disconnect/Connect uses the saved values.
- Store the selected endpoint and, where available, a stable USB identity/by-id
  path. Renumbering can resolve the same unambiguous identity; never select another
  adapter of the same model by coincidence. Ambiguity requires a new selection.
- Connect revalidates presence, identity, permissions, and exclusive ownership.
  Competing profiles/tabs cannot acquire the same device under different aliases.
- Ownership is per physical serial endpoint, not per active experimental run.
  Before opening, check known external holders without reading their ports, then
  acquire the platform's exclusive-open mechanism as well as the service lease.
  A busy or unverifiable endpoint returns an ownership error; never kill another
  reader, steal bytes, or alter its settings. POSIX advisory flock alone is not
  sufficient for non-cooperating serial readers. If external ownership cannot be
  checked reliably, this endpoint is unavailable to the workspace until resolved.
  The Qm Windows RAW-file collector uses its existing bridge/file path and is not
  replaced or gated here. Independent physical endpoints may coexist. Do not add
  a global run-active block or new experiment-start/stop conditions.
- Profile deletion requires confirmation and a disconnected/non-recording state.

## Session and measurement behavior

State reports distinguish disconnected, connecting, connected, and error, plus
receiving/no-data/stale, recording, and polling state. Include the active and saved
config revision, latest host receive time, counters, parse/checksum failures, and
the last error. An open port alone is not a successful measurement.

- Qm initially receives passively; no motion, return, stop, range, unit-change,
  or zeroing commands are dispatched. A fresh read waits for the next valid frame.
- CAS Read Once sends exactly `P`, without an unsolicited newline. One request
  may be pending per device; serialize it with polling. Only a complete response
  arriving after the request may satisfy it, never a cached measurement. Timestamp
  fields are host reception time and device-reported time separately. The protocol
  has no transaction ID; an unsolicited stream cannot prove request attribution.
- Expose named supported read requests, not arbitrary state-changing bytes in v1.
  CAS `Z/T/S/M` and Qm movement commands are outside this monitoring scope.
- Optional CAS polling starts only on explicit request, permits one outstanding
  request, and records timeouts. Qm passive reception needs no polling command.
- Refresh/new tabs subscribe to the same status/data; they do not create duplicate
  readers, pollers, recordings, or commands. Browser closure does not disconnect.
- Disconnect cancels polling/pending reads and finalizes logging, then closes the
  handle. Unplug/error leaves an explicit error and stale last value. Do not
  retry writes or switch ports automatically. Server restart restores config,
  not a silently resumed physical connection.

## API contract

All routes live below `/api/serial`; the workspace is `/serial`. These are internal
AX4LAB routes, not a new publicly exposed server or cross-origin integration.
For v1, restrict these routes to loopback clients/hosts and the same-origin local
workspace; do not broaden the whole application's listener/access settings.
Reject cross-origin mutation requests and do not introduce wildcard CORS or trust
arbitrary forwarded headers to establish local access. This trusts local OS users,
not an authenticated user-account/session model: Origin checks are not
authentication. Remote/LAN access and authentication are a future deployment
decision. Keep host/browser access checks in the API adapter.

| Route group | Behavior |
| --- | --- |
| `GET /modules`, `POST /modules/refresh` | Discover installed module metadata; no hardware I/O |
| `GET /modules/{id}/icon` | Contained, module-owned icon asset |
| `GET /ports` | Enumerated ports and observed availability; no probes |
| `GET/POST /profiles` | List/create device profiles |
| `GET/PUT/DELETE /profiles/{id}` | Read, Set/save with revision, delete |
| `POST /profiles/{id}/connect` and `/disconnect` | Idempotent session lifecycle |
| `GET /profiles/{id}/status` and `/latest` | State and cached measurement with age/validity |
| `POST /profiles/{id}/read` | Bounded fresh measurement request/wait |
| `POST /profiles/{id}/polling` | Explicit enable/disable and interval |
| `GET /profiles/{id}/events` | Bounded cursor-based incremental RX/TX/measurement events |
| `POST /profiles/{id}/recording/start` and `/stop` | Idempotent log lifecycle |
| `GET /recordings` and `/recordings/{id}/...` | List/download recordings by opaque ID |

Results carry schema version, profile/session identity, sequence number, timestamps,
raw/source units, normalized fields where justified, and validity/error codes.
Fresh reads distinguish timeout, disconnect, invalid data, and success. A timed-out
request does not stop the service or claim an experiment failed. Downloads resolve
only service-owned IDs under the injected log root, never caller-supplied paths.

## Recording, performance, and UI principles

Record raw received bytes plus timestamp/offset chunks, separate TX events, parsed
measurements, and a manifest with protocol/config/version and completeness status.
CSV export is a derivative; keep original data unmodified. Date text reported by
the scale must not replace the host timestamp.

Bound receive buffers, event history, pending requests, disk-writer queues, and GUI
updates. Retain full-rate data on disk while presenting a capped incremental view
(proposed 5 Hz). Queue/disk failures must be visible and mark the recording
incomplete instead of silently discarding samples or stopping unrelated workflows.
No large historic logs are copied into global controller snapshots.

Use the existing workspace appearance with short labels, status lights, and concise
action messages. The entry page is a module-icon catalog; its selected module page
contains profile/configuration/communications, with a route back to the catalog.
Do not add long permanent explanatory text or move existing equipment/PLC controls.
No chart, digital twin, or new experiment-stage integration is required for this
first version.

## Validation and rollout

1. Pure parser tests for split/coalesced/corrupt/unknown Qm frames and CAS signed
   values, dates, units, partial lines, and printer control bytes. Keep provisional
   Qm interpretations visibly provisional and never turn unknown bits into labels.
2. Fake transport/pseudo-terminal tests for request timeouts, stale data, polling,
   two devices, contention, aliases, unplug, reconnect, and recording completeness.
3. API/config tests for dropdown enumeration without I/O, Set persistence/revision,
   unavailable saved ports, active-vs-saved settings, delete confirmation, and logs.
4. Catalog tests: add a test module folder without central code changes; remove it,
   retain logs/profiles, validate duplicate/bad descriptors, path containment,
   absent icons, declaration-only scans, and active-session version pinning.
5. Browser tests for existing workspace entry, discovered icons/device pages,
   Set/reload, incremental receive, multiple tabs, bounded logs, and readable errors.
6. Focused AX4LAB regressions: no changes to automatic-loop routes, Qm CSV
   collection, equipment command execution, or other device workspaces.
7. Only after software checks, explicitly requested bounded hardware reception or
   a CAS `P` request may validate the service. Never send UTM control commands.
   Applying through a running-server restart remains a separate deployment action.

The repository contains unrelated uncommitted changes; preserve them. No benchmark,
long-running hardware monitor, server restart, or device actuation is part of design
review. Implementation file granularity and small error-message details are left
to the builder. Any broader command/control support requires a separate decision.
