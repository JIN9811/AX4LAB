# Serial Communication

AX4LAB's manual serial workspace shares one service between the GUI and HTTP API.
It is independent of experiment orchestration and opens no device on startup.

## Install and open

From `runtime/`, using the AX4LAB Python environment:

```sh
python -m pip install -r device_bridges/serial_communication/requirements.txt
```

Alternatively, install the project with the `serial` extra. Start AX4LAB normally,
then open **Device Workspaces → Serial Communication** (`/serial`) on the server PC.
Linux requires permission to access the selected serial device and `fuser`
(usually provided by `psmisc`). Port enumeration never probes device commands.

1. Select a device icon and create a named profile.
2. Choose a detected port and communication settings; press **Set**.
3. Press **Connect**. **Read once** waits for a fresh measurement. Only modules
   declaring polling support show **Start polling**.
4. **Start recording** preserves RX bytes, TX requests, timing and decoded values.
   Stop recording or disconnect to finalize it, then download the files.

Set is not Connect: changes made while connected take effect only after explicit
disconnect/reconnect. Reloading a tab neither reconnects nor stops the shared
session. Profile deletion requires confirmation and keeps recordings.

The port list is an OS inventory, not proof of successful communication. Connect
checks ownership. USB serial identity is retained where available; ambiguous or
missing devices fail without selecting a different device. Adapters without a
unique serial number cannot provide the same physical-identity guarantee.
If different hardware reuses an unchanged port name, Set rejects rebinding;
create a new profile for the replacement device.

## Modules

`modules/<name>/module.yaml`, `protocol.py`, and an optional local icon constitute
an installed device. The workspace scans descriptors; there is no GUI device list.
Copy an existing folder, change its ID, label, settings, channels and protocol.
Press **Refresh modules** after adding/removing a folder. Existing profiles survive
module removal. Restart the server after changing already-loaded protocol code.

The descriptor uses `schema: ax4lab.serial_device.v1`, a unique snake_case `id`,
semantic `version`, `label`, `icon`, `defaults`, `fields`, `channels`, and
`capabilities` (`read`, optionally `polling`). Field types are `port`, `select`
(with `options`) and `number` (with `min`, `max`, optional `step`). Every field has
a `key`, `label` and default. Common settings are port, baudrate, bytesize, parity,
stopbits, flow_control, timeout_s, stale_after_s and interval_s.

`protocol.py` exports `create_protocol(variant)` returning an object with:

- `feed(bytes) -> list[dict]`: each measurement has `values`, `units`, `quality`,
  and `valid`; preserve uninterpreted evidence rather than guessing it.
- `request() -> bytes | None`: the module's measurement request, or passive receive.
- `reset()`: discard an incomplete response before a new request.
- `errors`: rejected-frame count.

Modules are trusted, locally installed Python code—not browser uploads. Scan does
not import protocols. Duplicate IDs and malformed descriptors are excluded and
reported without breaking valid modules. Paths cannot escape the module folder.

### Module-owned views

An optional `views: [{id: model, label: 3D model}]` declaration adds navigation
links to that module's toolbar without device-name branches in the shared shell.
Each view owns `views/<view-id>/index.html` and its local dependencies under the
device module folder. No script, import, URL or arbitrary entry path is accepted
in the descriptor; the installed view code uses this fixed convention.

The generic host serves `/serial/modules/<module-id>/views/<view-id>` and the
contained assets at `/api/serial/modules/<module-id>/views/<view-id>/assets/<path>`.
Both inherit loopback/same-origin checks. Optional `profile_id` must belong to
that module. Missing/invalid views are isolated on discovery, and a removed
module's views disappear on catalog refresh. Views do not import protocol code.
Adding a deployed view also requires explicit wheel/sdist entries in
`runtime/distribution-files.json`, preserving the positive packaging contract.

QM100T's `views/model/` contains its measured scene, viewer, vendor licenses and
`calibration.mjs`. The installed reference maps |DISP2|=677.8 mm to the operator's
30 mm compression gap. The view reads the existing latest-measurement API only.
The model display targets 10 Hz with one read in flight. Normal successful
profile/status/latest/events GETs are omitted from terminal access logs;
HTTP failures and explicit device actions remain visible. This does not disable
the in-page raw-event inspector or user-started recordings.
The module-owned `views/workcell/` entry embeds the local MoveIt workcell viewer
at port 8878, preserving the selected profile. See
[model integration](../../../docs/gui/qm100t_model.md).

### Included protocols

| Module | Defaults | Receive/request contract |
|---|---|---|
| Qmesys QM100T | 115200, 8N1, no flow control | Passive only. Manual 42-byte encoder and 52-byte encoder/POT formats; separately selected observed 60-byte format. Length, framing and checksum are verified. |
| CAS MWII Plus | 9600, 8N1, no flow control | Send exactly uppercase `P` (`0x50`), parse timestamped `W:` text and optional date. No zero, tare, setup or mode commands. |

For this installation's `observed60` format, byte 48 (one-based) is the load-range
selection code. Passive observation found transitions through 0–3; the operator's
screen confirmed code 1 at 2000 kgf and the operator approved the range table
`0: 1000, 1: 2000, 2: 5000, 3: 10000` kgf on 2026-11-02. The parser emits both
`load_range_code` and `values.load_range`, so GUI, API and recording use the same
mapping. It never aliases the fourth numeric/POT field to the range. Unknown
codes retain the rest of the measurement and emit a null capacity. Manual 42/52
formats expose their documented range code without assuming this site's capacity
table. Revalidate the table if the instrument's range configuration changes.

Sources: [Qmesys Indicator Manual](../../../docs/knowledge/manuals/sources/Indicator%20Manual.pdf),
communication section pp. 43–46; CAS MWII Plus user manual, revision 241219,
print/communication section pp. 17–24. CAS 8N1 and the Qm 60-byte variant are based
on captured device responses, not a claim that the manuals define them.
Qm decoded channels are provisional until checked against the configured
indicator; `disp1`, `disp2`, and `pot` are **not** certified absolute platen height.
CAS print text does not establish stable/unstable state (`stable: null`).
This workspace does not replace Qm RAW-file collection or calculate SEA.

## Storage and boundaries

The host injects private paths:

- `<memory_root>/serial_communication/profiles.json`: atomic versioned config.
- `<log_root>/serial_communication/<recording-id>/`: `manifest.json`, `raw.bin`,
  `chunks.jsonl`, `tx.jsonl`, `measurements.jsonl`, `measurements.csv`.

`raw.bin` contains RX only; chunk offsets and host timestamps reconstruct its
timing. CSV is long-form (one channel per row). Manifest includes saved connection
snapshot and module metadata. Only `complete: true` indicates a finalized log.
Queue overflow, storage failure or device error marks incomplete. A process crash
leaves the initial incomplete manifest; the workspace does not silently repair it.
No recording deletion API is provided.

Memory is bounded to 1,000 session events and a 2,048-item writer queue; the browser
keeps 100 display lines. Closing/hiding the page does not stop recording. Explicitly
disconnect to release a device. Use one AX4LAB owning process: multi-process web
workers sharing this private store are not supported.

## API

All endpoints are same-origin, loopback-only. No wildcard CORS, remote serial
forwarding, arbitrary transmit endpoint, or motion controls are exposed.

| Method / path under `/api/serial` | Purpose |
|---|---|
| `GET /modules`, `POST /modules/refresh` | Discover installed devices |
| `GET /modules/{id}/icon` | Contained module asset or fallback |
| `GET /ports` | Detected server ports; does not open them |
| `GET, POST /profiles` | List/create saved profiles |
| `GET, PUT, DELETE /profiles/{id}` | Read, Set, confirmed deletion |
| `POST /profiles/{id}/connect`, `/disconnect` | Explicit connection lifecycle |
| `GET /profiles/{id}/status`, `/latest` | Connection, age/staleness, measurement |
| `GET /profiles/{id}/events?after=0` | Bounded cursor history with gap flag |
| `POST /profiles/{id}/read` | Fresh measurement; timeout does not return cached data |
| `POST /profiles/{id}/polling` | `{ "enabled": true, "interval_s": 1 }` |
| `POST /profiles/{id}/recording` | `{ "enabled": true }` / false |
| `GET /recordings`, `/recordings/{id}/{filename}` | List/download retained evidence |

Create: `{"module_id":"cas_mwii_plus","name":"Balance"}`. Set:
`{"revision":1,"settings":{"port":"<detected port>","baudrate":9600}}`.
The response returns the next revision; stale writes return 409. Delete requires
`{"revision":2,"confirmed":true}`. Optional read timeout: `{"timeout_s":10}`.
An instrument response timeout returns HTTP **504** with `detail.code: "timeout"`.
The request is not retried automatically; another read requires an explicit call
(or explicitly enabled polling). Do not use HTTP 408 for this downstream timeout:
Firefox can replay that response's POST and transmit the measurement request again.
Do not send private `device_id`/`stable_path` values: Set derives them from the
selected detected port. No start/connect request is implied by reading metadata.
