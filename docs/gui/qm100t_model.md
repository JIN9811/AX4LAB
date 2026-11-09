# QM100T model

Open **Device Bridge → Serial Communication → Qmesys QM100T → 3D model**.
The model and its dependencies are bundled with AX4LAB; a standalone preview
server or external CDN is not required. The back link preserves the selected
profile. Without a profile, `/serial/modules/qm_indicator/views/model` opens a manual preview.

The complete measured model is preserved: detached indicator and mounting arm,
rear load-cell label, full black top plate, upper/lower jig holders and moving
crosshead. Indicator cable/connectors and exterior front/right stickers are
omitted as requested. Base width/depth are 920/750 mm, deck height 531 mm,
overall height 1910 mm, column widths/clearance 205/472/205 mm. Frame depth
placement is front 120 / column 320 / rear 310 mm.
The initial compression platen contact gap is 30 mm, as measured by the operator.

## Serial data path

`/serial/modules/qm_indicator/views/model?profile_id=<QM100T profile id>` reads
`GET /api/serial/profiles/<id>/latest` every 500 ms while visible. It reuses the
communication workspace's server session. Opening the page never connects a
port, sends a measurement request, starts recording or controls equipment.
Connect/disconnect remains in the communication workspace.

The page displays Load, DISP1 and DISP2 exactly as decoded by that workspace.
Missing values show `—`; disconnected/stale samples are visibly inactive.
Network errors clear the current sample. The latest snapshot is available as
`window.qm100tSerial` and the `detail` of `qm100t:serial-snapshot` on `window`:

```js
{
  schema: 'ax4lab.qm100t_model.serial.v1',
  profile_id, state, stale, age_s,
  measurement // original serial values, units, validity, timestamp, etc.
}
```

## Operator calibration

Edit `runtime/device_bridges/serial_communication/modules/qm_indicator/views/model/calibration.mjs`:

```js
export const calibration = Object.freeze({
  channel: 'disp1',          // Confirm the instrument's displacement channel.
  referenceAbsMm: null,     // Absolute displacement at the reference pose.
  referenceGapMm: 30,       // Measured compression gap at that same pose.
});
```

Return the **physical distance between the two platen contact surfaces in mm**.
`null` leaves the manual model position unchanged. The operator specified that
absolute displacement increases downward, with an instrument datum associated
with the upper tensile fixture. The prepared mapping is therefore:

`gap_mm = referenceGapMm - (abs(displacement_mm) - referenceAbsMm)`

The reference remains unset, so serial data cannot move the preview yet. Confirm
the channel and measure displacement and compression gap at the same pose before
setting `referenceAbsMm`. The mentioned 677.8 mm was tentative and is not applied.
If confirmed at a 30 mm gap, the result would be `707.8 - abs(displacement_mm)`;
a 10 mm increase in absolute displacement then reduces the gap to 20 mm.
Only finite numeric readings whose decoded unit is `mm` are used. No zeroing or
calibration command is sent to the indicator; displayed raw readings are retained.

Only connected, non-stale samples marked valid with a valid checksum reach the
function. Its result must be a finite number inside the model's 0–740 mm range;
zero is accepted and out-of-range values are rejected, not clamped. This is a
geometric preview range, not a measured machine stroke. An accepted sample
pauses animation and updates only the virtual crosshead/bellows. Hardware motion
and load calibration are outside this page.

After `qm100t:model-ready`, `window.qm100tModel` exposes `limits`, `getGapMm()`
and `setGapMm(mm)` for calibration tooling. The setter returns false for invalid
or out-of-range input. Refresh the page after changing the calibration module.

## Assets

Navigation is declared by `views` in the device's `module.yaml`. Shared serial
HTML/JavaScript/API contain no QM100T-specific branch. Generic routes validate
module/view/profile ownership and keep assets within that view's directory.
Removing the module and refreshing the catalog removes its navigation and view.

The deployment bundle is `runtime/device_bridges/serial_communication/modules/qm_indicator/views/model/`. `scene.json.gz` stores
geometry, kinematics and provenance; `parameters.json` and `measurements/*.json`
retain measured/approximate distinctions without publishing reference photos.
GLB and USD downloads are bundled with lossless gzip compression; extract `.gz`
before importing them. The viewer decompresses its scene locally using the
browser's `DecompressionStream`. Geometry is in metres. The USD's
relative textures are included under `exports/textures/`.

Each compressed file remains under the publication guard's 5 MB limit. Exact
hash reviews in `system/knowledge/publication_allowlist.json` cover generated
geometry and the two synthetic product/display textures. No source photographs,
manual PDF, live readings or local profile files are included.

Third-party credits travel with the bundle: Three.js (MIT, `vendor/THREE-LICENSE.txt`)
and the emergency-stop cap/collar by Henrique Enzweiler from FreeCAD-library
(CC BY 3.0, `assets/emergency-stop/ATTRIBUTION.md`). The source model was finalized
on 2026-11-09; the current 30 mm pose is retained in the viewer and exports.
