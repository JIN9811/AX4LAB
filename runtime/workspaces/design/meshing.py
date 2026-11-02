"""Finite-domain fields: rotate sampling coordinates, close the crop, inspect STL."""


def create_grid(request):
    import numpy as np
    size = np.asarray(request["specimen_size_mm"], dtype=float)
    n = request["resolution"]
    axes = [np.linspace(-extent / 2, extent / 2, n) for extent in size]
    world = np.meshgrid(*axes, indexing="ij")
    x, y, z = np.deg2rad(request["orientation_deg"])
    rx = np.array([[1, 0, 0], [0, np.cos(x), -np.sin(x)], [0, np.sin(x), np.cos(x)]])
    ry = np.array([[np.cos(y), 0, np.sin(y)], [0, 1, 0], [-np.sin(y), 0, np.cos(y)]])
    rz = np.array([[np.cos(z), -np.sin(z), 0], [np.sin(z), np.cos(z), 0], [0, 0, 1]])
    rotation = rz @ ry @ rx
    # Inverse rotation samples an actively rotated object in the fixed world box.
    local = np.einsum("ji,j...->i...", rotation, np.asarray(world))
    return {"x": local[0], "y": local[1], "z": local[2], "world_x": world[0], "world_y": world[1],
            "world_z": world[2], "spacing_mm": (size / (n - 1)).tolist(),
            "bounds_mm": [-size / 2, size / 2], "shape": (n, n, n), "units": "mm"}


def mesh_field(grid, result, stl_path):
    import numpy as np
    import trimesh
    from skimage.measure import marching_cubes
    if not isinstance(result, dict) or not {"field", "units", "bounds_mm", "method"} <= set(result):
        raise ValueError("Provider field requires units, bounds_mm and method metadata")
    if result["units"] not in {"mm", "dimensionless"} or not isinstance(result["method"], str) or not result["method"]:
        raise ValueError("Invalid field units or method")
    field = np.asarray(result["field"], dtype=np.float32)
    if field.shape != grid["shape"] or not np.isfinite(field).all() or not np.any(field < 0):
        raise ValueError("Provider field must be finite, shape-compatible and nonempty")
    if not np.array_equal(np.asarray(result["bounds_mm"]), np.asarray(grid["bounds_mm"])):
        raise ValueError("Provider bounds do not match sampled domain")
    spacing = np.asarray(grid["spacing_mm"])
    bounds = np.asarray(grid["bounds_mm"])
    padded = np.pad(field, 1, constant_values=max(1., float(field.max())))
    vertices, faces, _, _ = marching_cubes(padded, level=0, spacing=spacing, gradient_direction="descent")
    vertices += bounds[0] - spacing
    vertices = np.clip(vertices, bounds[0], bounds[1])
    # Snap only float32-roundoff distance from a grid plane before STL welding.
    planes = np.round((vertices - bounds[0]) / spacing) * spacing + bounds[0]
    vertices = np.where(np.abs(vertices - planes) <= np.finfo(np.float32).eps * (bounds[1] - bounds[0]), planes, vertices)
    mesh = trimesh.Trimesh(vertices=vertices.astype(np.float32), faces=faces, process=True)
    mesh.update_faces(mesh.nondegenerate_faces())
    mesh.update_faces(mesh.unique_faces())
    mesh.remove_unreferenced_vertices()
    mesh.export(stl_path)
    metadata = {key: value for key, value in result.items() if key not in {"field", "bounds_mm"}}
    metadata.update(field_bounds_mm=bounds.tolist(), spacing_mm=spacing.tolist(),
                    sampled_solid_fraction=float(np.count_nonzero(field < 0) / field.size),
                    sampling="uniform_finite_domain", boundary_closure="one_voxel_padding_clamped_to_domain",
                    orientation="active_xyz_degrees_RzRyRx_before_clipping")
    return metadata


def validate_mesh(stl_path, specimen_size_mm):
    import numpy as np
    import trimesh
    from mcp_tools.mesh_quality import inspect_stl
    checked = inspect_stl(stl_path)
    if not checked["ok"]:
        return checked
    mesh = trimesh.load_mesh(stl_path, process=True)
    half = np.asarray(specimen_size_mm) / 2
    bounds = mesh.bounds
    inside = bool(np.all(bounds[0] >= -half - 1e-5) and np.all(bounds[1] <= half + 1e-5))
    normals = bool(np.isfinite(mesh.face_normals).all() and np.allclose(np.linalg.norm(mesh.face_normals, axis=1), 1.))
    volume = float(mesh.volume)
    if not inside:
        checked["reject_reasons"].append("outside_specimen_bounds")
    if not normals:
        checked["reject_reasons"].append("invalid_normals")
    if not np.isfinite(volume) or volume > float(np.prod(half * 2)) + 1e-4:
        checked["reject_reasons"].append("invalid_volume")
    return {**checked, "ok": not checked["reject_reasons"], "bounds_mm": bounds.tolist(),
            "component_count": checked["disconnected_components"], "within_envelope": inside,
            "normals_finite_unit": normals, "stl_reload": "passed", "self_intersections": "unchecked",
            "physical_printability": "unchecked", "mechanical_properties": "unchecked",
            "wall_thickness": "unchecked", "periodic_boundary": "unchecked"}
