"""Behavioural test for dropping zero-area faces while building the mesh.

A polygon whose corners are collinear encloses no area, so it has no normal
direction. Blender 4.1+ stores the zero-length custom normal it is given and
shades it as a hole, which is part of the "degenerate" look reported on
Blender 3.4 in issue #8. Such a face can never cover a pixel, so the build
drops it rather than hand Blender geometry it cannot shade.

Run:
  blender --background --python test/test_mesh_io_zero_area.py
"""
import os
import sys

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_TEST_DIR)
_PACKAGE_PARENT = os.path.dirname(_PROJECT_ROOT)
for _p in (_TEST_DIR, _PACKAGE_PARENT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

BLENDER_TEST = True

# 0-3 form a unit square. 4-7 repeat two positions, so the second quad is
# folded flat along the y axis: its two fan triangles have equal and opposite
# normals and the polygon encloses no area at all.
_VERTS = [
    [0.0, 0.0, 0.0],
    [1.0, 0.0, 0.0],
    [1.0, 1.0, 0.0],
    [0.0, 1.0, 0.0],
    [2.0, 0.0, 0.0],
    [2.0, 1.0, 0.0],
    [2.0, 0.0, 0.0],
    [2.0, 1.0, 0.0],
]
_GOOD_FACE = (0, 1, 2, 3)
_FLAT_FACE = (4, 5, 6, 7)


def _build():
    import numpy as np
    from Blender_AutoTopo.utils.mesh_io import MeshData, mesh_data_to_blender

    md = MeshData()
    md.vertices = np.array(_VERTS, dtype=np.float64)
    md.faces = np.array([_GOOD_FACE, _FLAT_FACE])
    obj = mesh_data_to_blender(md, name="ZeroArea")
    assert obj is not None
    return obj.data


def _run():
    mesh = _build()
    assert len(mesh.polygons) == 1, (
        f"expected only the real face to survive, got {len(mesh.polygons)} "
        f"polygons with areas {[round(p.area, 9) for p in mesh.polygons]}"
    )
    assert mesh.polygons[0].area > 0.0, (
        f"the surviving face has no area: {mesh.polygons[0].area}"
    )
    print("=== MESH IO ZERO AREA TEST PASSED ===")


def test_mesh_io_zero_area():
    import pytest
    pytest.importorskip("bpy", reason="requires Blender background mode")
    _run()


if __name__ == "__main__":
    _run()
