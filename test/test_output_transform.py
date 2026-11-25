"""Behavioural repro: the retopo output must land where its source object is.

The mesh extraction in ``utils/mesh_io.blender_to_mesh_data`` reads the
object's *local* vertex coordinates, and ``mesh_data_to_blender`` builds the
result at the origin with an identity transform. When the source object
carries a non-identity transform (imported FBX assets commonly carry
``scale = 0.01`` plus a rotation) the retopo object therefore appears ~100x
too large, unrotated and offset from the input, which reads as a failed or
useless retopology.

Run:
  blender --background --python test/test_output_transform.py
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

# Source transform deliberately far from identity: imported FBX meshes use
# exactly this shape (0.01 scale, quarter-turn rotation, offset).
SOURCE_LOCATION = (3.0, -2.0, 1.5)
SOURCE_ROTATION = (1.5708, 0.0, -1.5708)
SOURCE_SCALE = (0.01, 0.01, 0.01)


class _FakeResult:
    """Minimal stand-in for ``EngineResult``; enough for the done-handler."""

    success = True
    error_message = ""
    time_total = 0.0
    output_vert_count = 4
    output_face_count = 1
    output_quad_count = 0
    triangle_ratio = 1.0
    silhouette_error = 0.0
    patch_count = 1

    def __init__(self, mesh_data):
        self.output_mesh = mesh_data


def _run():
    import numpy as np
    import bpy
    import addon_utils

    # Load the addon the way an installed user has it.
    addon_utils.enable("Blender_AutoTopo", default_set=False, handle_error=None)
    ops_mod = sys.modules["Blender_AutoTopo.ui.operators"]
    mesh_io = sys.modules["Blender_AutoTopo.utils.mesh_io"]

    # A source quad with a non-identity transform.
    src_mesh = bpy.data.meshes.new("_transform_src_mesh")
    src_mesh.from_pydata(
        [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)]
    )
    src_mesh.update()
    src = bpy.data.objects.new("TransformSrc", src_mesh)
    src.location = SOURCE_LOCATION
    src.rotation_euler = SOURCE_ROTATION
    src.scale = SOURCE_SCALE
    bpy.context.collection.objects.link(src)
    bpy.context.view_layer.update()
    expected = src.matrix_world.copy()

    # Output geometry in the same local space as the source data.
    md = mesh_io.MeshData()
    md.vertices = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0],
                            [1.0, 1.0, 0.0], [0.0, 1.0, 0.0]])
    md.faces = np.array([[0, 1, 2, 3]])
    assert md.validate()

    # Drive the real done-handler, i.e. the code an actual run reaches.
    ops_mod._obj_name = src.name
    ops_mod._source_matrix = expected.copy()
    ops_mod._handle_pipeline_done(_FakeResult(md))

    out = bpy.data.objects.get(f"{src.name}_retopo")
    assert out is not None, "done-handler created no output object"

    got = out.matrix_world
    for row in range(4):
        for col in range(4):
            want = expected[row][col]
            have = got[row][col]
            assert abs(have - want) < 1e-5, (
                "output transform does not match the source object: "
                f"[{row}][{col}] expected {want:.6f}, got {have:.6f}"
            )

    # The scale is what the user sees as "the retopo mesh is enormous".
    src_dims = src.dimensions
    out_dims = out.dimensions
    for axis in range(3):
        assert abs(out_dims[axis] - src_dims[axis]) < 1e-4, (
            "output world size differs from the source: "
            f"axis {axis} source {src_dims[axis]:.6f}, output {out_dims[axis]:.6f}"
        )

    print("=== OUTPUT TRANSFORM TEST PASSED ===")


def test_output_transform():
    import pytest
    pytest.importorskip("bpy", reason="requires Blender background mode")
    _run()


if __name__ == "__main__":
    _run()
