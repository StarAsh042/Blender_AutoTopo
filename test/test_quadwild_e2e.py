"""End-to-end QuadWild engine test in Blender background mode.

Run:
  blender --background --python test/test_quadwild_e2e.py

Under pytest without Blender this module is skipped (see conftest.py /
``pytest.importorskip``).
"""
import os
import sys

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_TEST_DIR)
_PACKAGE_PARENT = os.path.dirname(_PROJECT_ROOT)
for _p in (_TEST_DIR, _PACKAGE_PARENT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Marked as needing a real Blender environment; conftest.py turns this
# into the ``blender`` marker + a skip when bpy is unavailable.
BLENDER_TEST = True


def _run():
    # Test-only: borrow scipy from system Python 3.10 (appended so
    # Blender's own numpy stays in charge).
    try:
        import scipy  # noqa: F401
    except ImportError:
        sys.path.append(r"C:\Program Files (x86)\Python\lib\site-packages")

    import bpy
    import numpy as np  # noqa: F401

    from Blender_AutoTopo.utils.mesh_io import blender_to_mesh_data
    from Blender_AutoTopo.engines.quadwild_engine import (
        run_quadwild, is_quadwild_available,
    )

    print("=== QuadWild e2e test ===")
    print("available:", is_quadwild_available())

    # Build a subdivided cube as test input
    bpy.ops.mesh.primitive_cube_add(size=2.0)
    obj = bpy.context.active_object
    sub = obj.modifiers.new("sub", 'SUBSURF')
    sub.levels = 3
    bpy.ops.object.modifier_apply(modifier=sub.name)

    mesh = blender_to_mesh_data(obj)
    print(f"input: {mesh.n_verts} verts, {mesh.n_faces} faces, "
          f"sharp: {len(mesh.sharp_edges)}")

    def cb(step, pct):
        print(f"[progress] {step} ({pct:.0f}%)")

    result = run_quadwild(
        mesh,
        target_face_count=500,
        tolerance_percent=10.0,
        sharp_angle=30.0,
        keep_sharp=True,
        progress_callback=cb,
    )

    print(f"success: {result.success}")
    assert result.success, f"QuadWild failed: {result.error_message}"
    print(f"output: {result.output_vert_count} verts, "
          f"{result.output_face_count} faces")
    print(f"quads: {result.output_quad_count}, tris: {result.output_tri_count} "
          f"({result.triangle_ratio * 100:.1f}%)")
    print(f"silhouette error: {result.silhouette_error:.4f}")
    print(f"time: {result.time_total:.2f}s")
    assert result.output_face_count > 0
    print("=== QuadWild e2e test PASSED ===")


def test_quadwild_e2e():
    import pytest
    pytest.importorskip("bpy", reason="requires Blender background mode")
    _run()


if __name__ == "__main__":
    _run()
