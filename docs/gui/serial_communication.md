# Serial Communication Workspace

Open **Device Workspaces → Serial Communication** from AX4LAB on the server PC.
Each installed device module supplies its icon, fields, defaults and parser.

## Connect and save

1. Select **Qmesys QM100T** or **CAS MWII Plus**.
2. Enter a profile name and select **New**.
3. Select a detected **Port**, review communication settings, then press **Set**.
4. Press **Connect**. **Read once** requests/waits for a new measurement; CAS also
   supports periodic requests with **Start polling**.

**Set** saves settings without connecting. If already connected, disconnect and
reconnect to apply changed settings. Profiles persist across browser refresh and
server restart; connections do not automatically resume after a server restart.
Use **Delete** to remove a disconnected profile, with confirmation.

## Record

Press **Start recording**, then **Stop recording** when finished. Downloads include
decoded CSV/JSONL, original received bytes, receive timing, transmitted requests
and metadata. Deleting a profile does not delete its recordings.

**Activity** shows recent connection changes and errors. Expand **Raw data** only
when inspecting packets; collapsing it does not stop reception or recording.
The QM100T display shows **Load**, **DISP1**, **DISP2** and **Load Range**. On the
installed device's `observed60` format, range codes `0 / 1 / 2 / 3` map to
`1000 / 2000 / 5000 / 10000 kgf`. The code changes with the device's range
selection; the capacity table is the operator-approved configuration, not a
capacity value transmitted directly by the instrument. Unknown codes show **—**.
POT is hidden; original bytes and decoded recording data are retained.

- **Measured · time**: a completed CAS single read, with a fixed host receive time.
  It stays visible until the next measurement; elapsed time alone does not dim it.
- **Receiving**: a recent measurement during UTM streaming or CAS polling.
- **No data**: connected but no valid measurement yet.
- **Stale**: continuous reception exceeded the configured age. A disconnected
  device is shown separately as **Disconnected**.
- **Incomplete** recording: inspect metadata for storage, queue or connection errors.

The port dropdown shows OS-detected ports—not a guarantee that an instrument is
responding. **Connect** checks access and ownership. A device already used by an
experiment or another application must not be opened again.

## Scope

This is a manual communication workspace. It does not alter the experiment loop,
control UTM motion, zero/tare the scale, or replace the UTM CSV collection stage.
Qm displacement channels are not yet calibrated absolute platen height.
Only the selected measurement request is transmitted (CAS: `P`); UTM is passive.

For dependency installation, module extension, protocol sources and API contracts,
see the [serial module reference](../../runtime/device_bridges/serial_communication/README.md).
