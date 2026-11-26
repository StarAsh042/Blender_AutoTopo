"""Behavioural repro for issue #8 (Blender background mode).

A MeshData carrying custom normals must convert into a Blender object on
Blender 4.1+, where ``Mesh.use_auto_smooth`` no longer exists. Before the fix
this raises ``AttributeError`` at ``utils/mesh_io.py:221``.

Run:
  blender --background --python test/test_mesh_io_normals.py
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


def _run():
    import numpy as np
    from Blender_AutoTopo.utils.mesh_io import MeshData, mesh_data_to_blender

    # Tilted on purpose: a quad in the XY plane has geometric normal +Z, so
    # reading back +Z would mean the custom normals were dropped. Only the
    # requested direction proves the 4.1+ skip branch keeps them.
    tilted = np.array([0.6, 0.0, 0.8])

    md = MeshData()
    md.vertices = np.array(
        [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.0, 0.0]]
    )
    md.faces = np.array([[0, 1, 2, 3]])
    md.normals = np.array([tilted] * 4)
    assert md.validate()

    obj = mesh_data_to_blender(md, name="Issue8_Normals")
    assert obj is not None
    mesh = obj.data
    assert len(mesh.polygons) == 1
    assert mesh.has_custom_normals, "custom normals were not applied"

    # 3.x keeps loop normals lazy: they read back as (0, 0, 0) until asked for.
    # 4.1+ removed the call because loop normals are always evaluated.
    if hasattr(mesh, "calc_normals_split"):
        mesh.calc_normals_split()

    expected = tuple(round(float(c), 3) for c in tilted)
    for loop in mesh.loops:
        got = tuple(round(c, 3) for c in loop.normal)
        assert got == expected, f"loop normal {got} != requested {expected}"
    print("=== MESH IO NORMALS TEST PASSED ===")


def test_mesh_io_normals():
    import pytest
    pytest.importorskip("bpy", reason="requires Blender background mode")
    _run()


if __name__ == "__main__":
    _run()
