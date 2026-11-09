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
  channel: 'disp2',          // Installed indicator's position channel.
  referenceAbsMm: 677.8,     // Absolute displacement at the reference pose.
  referenceGapMm: 30,       // Measured compression gap at that same pose.
});
```

Return the **physical distance between the two platen contact surfaces in mm**.
`null` leaves the manual model position unchanged. The operator specified that
absolute displacement increases downward, with an instrument datum associated
with the upper tensile fixture. The prepared mapping is therefore:

`gap_mm = referenceGapMm - (abs(displacement_mm) - referenceAbsMm)`

The installed workcell uses the operator-reported 30 mm gap and 677.8 mm
reference. On 2026-11-09 the live frame showed DISP1=1.93 mm and DISP2=677.8 mm,
identifying DISP2 as the reference channel. The mapping is
`707.8 - abs(DISP2_mm)`; a 10 mm increase reduces the gap to 20 mm.
This is this workcell's display reference, not a manufacturer calibration.
Update it if the indicator datum or fixtures change; opening/reconnecting never
auto-zeros the mapping.
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

## Full workcell entry

Open **Device Bridge → Serial Communication Bridge → Qmesys QM100T →
전체 모델 · 로봇 + UTM**. The standalone 3D model also links to this view.
The module-owned page `/serial/modules/qm_indicator/views/workcell` embeds the
local read-only MoveIt workcell viewer at `http://127.0.0.1:8878/` and preserves
`profile_id`. Shared navigation discovers it from the QM module descriptor.
Use **Refresh modules** if AX4LAB was running before the new view was installed;
no device session restart is needed.

The workcell viewer runs from the actual `rebot-vr-moveit` workspace with
`python3 tools/workcell_preview.py` (after `tools/export_workcell_preview.py`
has generated its local assets). Unlike the bundled UTM-only view, this full
workcell requires that local viewer service and the robot assets. It does not
start hardware processes. Without robot feedback the arms display SRDF home;
fresh robot feedback supplies joint coordinates. The QM source uses the same
existing AX4LAB serial profile. **시리얼 위치 보정** allows per-profile local
overrides, release to manual control, and restore of the installed reference.

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
