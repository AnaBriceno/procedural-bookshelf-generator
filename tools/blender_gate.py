"""
blender_gate.py - Technical Art Quality Gate & Verification Library for Blender

Provides machine-readable execution sentinels (AGENT_OK / AGENT_FAIL),
numeric assertions (dimensions, applied scale, material assignment),
self-checking procedural scene audits, and lightweight verification helpers.
Zero external dependencies (pure Python + optional bpy).
"""

import json
import math
import sys
import traceback
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class Verdict(str, Enum):
    PASS = "PASS"
    REFINE_CODE = "refine-code"
    REFINE_SPEC = "refine-spec"
    REQUEST_INPUT = "request-input"
    STOP = "stop"


SENTINEL_OK = "AGENT_OK"
SENTINEL_FAIL = "AGENT_FAIL"


def _emit_sentinel(tag: str, step: str, verdict: Verdict, metrics: Dict[str, Any], error: Optional[Dict[str, Any]] = None):
    payload = {
        "step": str(step),
        "verdict": verdict.value if isinstance(verdict, Verdict) else str(verdict),
        "metrics": metrics or {},
        "error": error
    }
    line = f"{tag} {json.dumps(payload, ensure_ascii=True, sort_keys=True)}"
    sys.stdout.write("\n" + line + "\n")
    sys.stdout.flush()
    return payload


def emit_ok(step: str, metrics: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
    """Emit the machine-readable success sentinel with measured metrics."""
    m = dict(metrics or {})
    m.update(kwargs)
    return _emit_sentinel(SENTINEL_OK, step, Verdict.PASS, m, None)


def emit_fail(
    step: str,
    error: Any,
    verdict: Verdict = Verdict.REFINE_CODE,
    failed_condition: Optional[str] = None,
    metrics: Optional[Dict[str, Any]] = None,
    **kwargs
) -> Dict[str, Any]:
    """Emit the machine-readable failure sentinel carrying structured error data."""
    m = dict(metrics or {})
    m.update(kwargs)
    if failed_condition:
        m["failed_condition"] = failed_condition

    if isinstance(error, BaseException):
        tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        err_dict = {
            "type": type(error).__name__,
            "message": str(error),
            "traceback": tb.strip()
        }
    elif isinstance(error, dict):
        err_dict = error
    else:
        err_dict = {"type": "AssertionError", "message": str(error), "traceback": ""}

    return _emit_sentinel(SENTINEL_FAIL, step, verdict, m, err_dict)


# ==============================================================================
# NUMERIC VERIFICATION & HARD GATES (BPY-AWARE)
# ==============================================================================

def _get_bpy():
    try:
        import bpy
        return bpy
    except ImportError:
        return None


def get_world_bbox(obj) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
    """Return world-space ((min_x, min_y, min_z), (max_x, max_y, max_z)) for an object."""
    bpy = _get_bpy()
    if bpy is None:
        raise RuntimeError("bpy is required to calculate world bbox.")

    if isinstance(obj, str):
        obj = bpy.data.objects.get(obj)
        if not obj:
            raise ValueError(f"Object '{obj}' not found in bpy.data.objects.")

    mathutils = __import__('mathutils')
    corners = [obj.matrix_world @ mathutils.Vector(corner) for corner in obj.bound_box]
    xs = [c.x for c in corners]
    ys = [c.y for c in corners]
    zs = [c.z for c in corners]
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def assert_transforms_applied(obj_or_name, tol: float = 1e-4) -> bool:
    """Verify that object scale is (1.0, 1.0, 1.0) and dimensions are non-zero."""
    bpy = _get_bpy()
    if bpy is None:
        return True
    obj = bpy.data.objects.get(obj_or_name) if isinstance(obj_or_name, str) else obj_or_name
    if not obj:
        raise AssertionError(f"Object '{obj_or_name}' does not exist.")

    sx, sy, sz = obj.scale
    if abs(sx - 1.0) > tol or abs(sy - 1.0) > tol or abs(sz - 1.0) > tol:
        raise AssertionError(
            f"Object '{obj.name}' scale is not applied: ({sx:.4f}, {sy:.4f}, {sz:.4f}) != (1.0, 1.0, 1.0)"
        )
    return True


def assert_dimensions(obj_or_name, expected: Tuple[float, float, float], tol: float = 0.005) -> bool:
    """Verify that object dimensions match expected (x, y, z) within tolerance."""
    bpy = _get_bpy()
    if bpy is None:
        return True
    obj = bpy.data.objects.get(obj_or_name) if isinstance(obj_or_name, str) else obj_or_name
    if not obj:
        raise AssertionError(f"Object '{obj_or_name}' does not exist.")

    dx, dy, dz = obj.dimensions
    ex, ey, ez = expected
    errs = []
    if abs(dx - ex) > tol:
        errs.append(f"X: actual {dx:.4f}m vs expected {ex:.4f}m (tol {tol}m)")
    if abs(dy - ey) > tol:
        errs.append(f"Y: actual {dy:.4f}m vs expected {ey:.4f}m (tol {tol}m)")
    if abs(dz - ez) > tol:
        errs.append(f"Z: actual {dz:.4f}m vs expected {ez:.4f}m (tol {tol}m)")

    if errs:
        raise AssertionError(f"Dimension mismatch on '{obj.name}': {', '.join(errs)}")
    return True


def assert_materials_assigned(obj_or_name, allow_empty: bool = False) -> List[str]:
    """Verify that renderable mesh object has valid materials assigned (no empty slots, no pink shaders)."""
    bpy = _get_bpy()
    if bpy is None:
        return []
    obj = bpy.data.objects.get(obj_or_name) if isinstance(obj_or_name, str) else obj_or_name
    if not obj:
        raise AssertionError(f"Object '{obj_or_name}' does not exist.")

    if obj.type != 'MESH':
        return []

    slots = obj.material_slots
    if not slots and not allow_empty:
        raise AssertionError(f"Mesh object '{obj.name}' has no material slots assigned.")

    mat_names = []
    for idx, slot in enumerate(slots):
        if not slot.material:
            raise AssertionError(f"Mesh object '{obj.name}' slot {idx} is empty (missing material).")
        mat_names.append(slot.material.name)
    return mat_names


def check_bbox_overlap(obj_a, obj_b, margin: float = -0.001) -> bool:
    """
    Check if two objects' axis-aligned world bounding boxes overlap.
    A negative margin allows touching faces without triggering an overlap.
    """
    (min_a, max_a) = get_world_bbox(obj_a)
    (min_b, max_b) = get_world_bbox(obj_b)

    overlap_x = (min_a[0] <= max_b[0] + margin) and (max_a[0] >= min_b[0] - margin)
    overlap_y = (min_a[1] <= max_b[1] + margin) and (max_a[1] >= min_b[1] - margin)
    overlap_z = (min_a[2] <= max_b[2] + margin) and (max_a[2] >= min_b[2] - margin)

    return overlap_x and overlap_y and overlap_z


# ==============================================================================
# PROCEDURAL SCENE AUDITOR (SELF-CHECKING GENERATOR)
# ==============================================================================

def audit_procedural_scene(
    name_filter: Optional[str] = None,
    enclosing_bbox: Optional[Tuple[Tuple[float, float, float], Tuple[float, float, float]]] = None,
    require_scale_applied: bool = True,
    require_materials: bool = True,
    check_mesh_overlaps: bool = False
) -> Dict[str, Any]:
    """
    Comprehensive self-check for procedural scenes:
    - Counts active objects and meshes
    - Validates applied scale on all generated components
    - Ensures every mesh has valid materials
    - Verifies objects stay strictly within enclosing bounds (no shelf protrusions)
    - Detects unintended bounding box collisions
    """
    bpy = _get_bpy()
    if bpy is None:
        return {"status": "SKIPPED_NO_BPY"}

    objects = list(bpy.data.objects)
    if name_filter:
        objects = [o for o in objects if name_filter in o.name]

    mesh_objs = [o for o in objects if o.type == 'MESH']
    report = {
        "total_objects": len(objects),
        "mesh_objects": len(mesh_objs),
        "scale_violations": [],
        "material_violations": [],
        "bounds_violations": [],
        "overlap_pairs": [],
        "summary": "PASS"
    }

    # 1. Scale check
    if require_scale_applied:
        for o in mesh_objs:
            sx, sy, sz = o.scale
            if abs(sx - 1.0) > 1e-4 or abs(sy - 1.0) > 1e-4 or abs(sz - 1.0) > 1e-4:
                report["scale_violations"].append(f"{o.name}: ({sx:.3f}, {sy:.3f}, {sz:.3f})")

    # 2. Material check
    if require_materials:
        for o in mesh_objs:
            if not o.material_slots or any(not s.material for s in o.material_slots):
                report["material_violations"].append(o.name)

    # 3. Enclosure / Bounds check
    if enclosing_bbox:
        (b_min, b_max) = enclosing_bbox
        for o in mesh_objs:
            (o_min, o_max) = get_world_bbox(o)
            tol = 0.002
            if o_min[0] < b_min[0] - tol or o_max[0] > b_max[0] + tol or \
               o_min[1] < b_min[1] - tol or o_max[1] > b_max[1] + tol or \
               o_min[2] < b_min[2] - tol or o_max[2] > b_max[2] + tol:
                report["bounds_violations"].append(
                    f"{o.name} extends outside enclosure: [{o_min[0]:.3f}..{o_max[0]:.3f}, {o_min[1]:.3f}..{o_max[1]:.3f}, {o_min[2]:.3f}..{o_max[2]:.3f}]"
                )

    # 4. Overlaps
    if check_mesh_overlaps and len(mesh_objs) <= 150:  # O(N^2) guard
        for i in range(len(mesh_objs)):
            for j in range(i + 1, len(mesh_objs)):
                if check_bbox_overlap(mesh_objs[i], mesh_objs[j]):
                    report["overlap_pairs"].append((mesh_objs[i].name, mesh_objs[j].name))

    has_failures = bool(
        report["scale_violations"] or
        report["material_violations"] or
        report["bounds_violations"] or
        report["overlap_pairs"]
    )
    report["summary"] = "FAIL" if has_failures else "PASS"
    return report


# ==============================================================================
# FAST CHEAP PREVIEW HELPER (NUMERIC & QUICK PIXEL LADDER)
# ==============================================================================

def render_quick_preview(filepath: str, resolution: Tuple[int, int] = (512, 320), samples: int = 16) -> str:
    """
    Renders a fast low-sample preview to check framing and lighting
    BEFORE committing to an expensive multi-minute Cycles production render.
    """
    bpy = _get_bpy()
    if bpy is None:
        raise RuntimeError("bpy required for preview render.")

    scene = bpy.context.scene
    orig_x = scene.render.resolution_x
    orig_y = scene.render.resolution_y
    orig_samples = scene.cycles.samples if scene.render.engine == 'CYCLES' else 16
    orig_path = scene.render.filepath

    try:
        scene.render.resolution_x = resolution[0]
        scene.render.resolution_y = resolution[1]
        if scene.render.engine == 'CYCLES':
            scene.cycles.samples = samples
        scene.render.filepath = filepath
        bpy.ops.render.render(write_still=True)
        return filepath
    finally:
        scene.render.resolution_x = orig_x
        scene.render.resolution_y = orig_y
        if scene.render.engine == 'CYCLES':
            scene.cycles.samples = orig_samples
        scene.render.filepath = orig_path
