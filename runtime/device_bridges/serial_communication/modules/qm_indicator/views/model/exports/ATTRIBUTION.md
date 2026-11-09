# Emergency stop button asset

“Emergency stop mushroom head push-button - 22 mm” by **Henrique Enzweiler**, distributed in the FreeCAD community parts library under **Creative Commons Attribution 3.0 Unported (CC BY 3.0)**.

- Source asset: https://github.com/FreeCAD/FreeCAD-library/blob/e6cb89e6bbde7fa807b2fcf753e6f7227f40395b/Electrical%20Parts/Push%20buttons/Emergency%20stop%20mushroom%20head%20push-button%20-%2022%20mm.FCStd
- Authorship commit: https://github.com/FreeCAD/FreeCAD-library/commit/e6cb89e6bbde7fa807b2fcf753e6f7227f40395b
- Repository asset license: https://github.com/FreeCAD/FreeCAD-library/blob/master/LICENSE-Assets
- License: https://creativecommons.org/licenses/by/3.0/

This adaptation extracts the original red cap and dark collar from the source's complete yellow enclosure, tessellates the existing BRep, changes axes/origin, and closes only the hidden planar material-interface openings. The visible cap/collar geometry is neither remodeled nor scaled. Keep this attribution with redistributed models containing these parts, and describe further changes. No author endorsement is implied.

The repository explicitly applies CC BY 3.0 to all FCStd/STEP/STL assets. The FCStd internal document property still contains FreeCAD's “All rights reserved” text; this is preserved in the original download and noted here rather than silently removed. The explicit repository distribution license is the license relied on for this adaptation.

## Import

`red_cap.npz` and `dark_collar.npz` each contain `vertices` (N×3 float64), `faces` (M×3 integer triangle indices), and `color` (RGB floats 0–1). Equivalent binary STL files are included. Units are **millimeters**. Multiply vertices by `0.001` for a meter-based scene.

The origin is the rear center of the black collar. **+Z points outward** from the mounting panel; X/Y lie in the panel plane. The collar occupies Z=0…12 mm and has maximum diameter 30 mm. The red head occupies Z=12…24.0204103 mm and has diameter 40 mm. The original nominal 22 mm refers to mounting cutout.

Both parts were checked for finite vertices, valid indices, nondegenerate triangles, consistent winding, positive volume and watertight manifold edges. Results are in `verification.json`.

The photographed UTM's manufacturer and exact emergency-stop model are unconfirmed. This is a generic existing community CAD asset. The source has no white twist arrows or fine cap perimeter ribs. Its yellow enclosure is omitted; the photo's separate rectangular upper/lower guard must be reconstructed separately and should not be attributed to this source as an exact downloaded part.

Scene adaptation: mm to m; source +Z to world -Y; red material recolored. White arrow and yellow guard are separate photo reconstructions.
