"""Behavioural test for the loop-normal repair (Blender background mode).

A loop can end up with no normal to shade with. Either the vertex normal we
were handed is zero length, because the vertex only touches faces the build
dropped, or Blender before 4.1 could not store the normal at all: it encodes a
custom split normal as a short2 offset against the loop's own reference normal,
so a normal exactly opposite that reference is the singularity of the encoding
and decodes as zero. Either way the loop shades as a hole, which is the
"degenerate" look reported on Blender 3.4 in issue #8.

Both cases go through ``mesh_data_to_blender``, the real entry point, so the
test fails wherever the repair is missing.

Run:
  blender --background --python test/test_mesh_io_normal_repair.py
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

# A slightly bent quad, so the build has real geometry to shade.
_VERTS = [
    [0.0, 0.0, 0.0],
    [1.0, 0.0, 0.0],
    [1.0, 1.0, 0.1],
    [0.0, 1.0, 0.1],
]


def _build(name, normals):
    import numpy as np
    from Blender_AutoTopo.utils.mesh_io import MeshData, mesh_data_to_blender

    md = MeshData()
    md.vertices = np.array(_VERTS, dtype=np.float64)
    md.faces = np.array([[0, 1, 2, 3]])
    md.normals = np.array(normals, dtype=np.float64)
    assert md.validate(), "test mesh data is invalid"

    obj = mesh_data_to_blender(md, name=name)
    assert obj is not None
    return obj.data


def _loop_normals(mesh):
    """The normals Blender shades with, read the way the addon now reads them.

    ``loops.foreach_get("normal")`` is deliberately not used: on 3.6 it reports
    uninitialised memory for a mesh that was just written, which is the reading
    that corrupted the output in issue #8.
    """
    import numpy as np
    corners = getattr(mesh, "corner_normals", None)
    if corners is not None and len(corners) == len(mesh.loops):
        return np.array([tuple(c.vector) for c in corners], dtype=np.float64)
    mesh.calc_normals_split()
    return np.array([tuple(loop.normal) for loop in mesh.loops], dtype=np.float64)


def _face_normal(mesh):
    import numpy as np
    out = np.zeros((len(mesh.polygons), 3), dtype=np.float64)
    mesh.polygons.foreach_get("normal", out.ravel())
    return out[0]


def _run():
    import numpy as np

    # Case 1: every vertex normal we are handed is zero length. Written
    # through unchanged, that is what used to reach the shader on 3.4.
    mesh = _build("Repair_Zero", np.zeros((4, 3)))
    assert mesh.has_custom_normals, "custom normals were not applied"
    got = _loop_normals(mesh)
    lengths = np.linalg.norm(got, axis=1)
    assert (lengths > 0.5).all(), (
        f"a zero-length normal survived into the mesh: {got.tolist()}"
    )

    # The direction restored is the face normal: representable by construction
    # and the only direction the loop carries without inventing geometry.
    unit = got / lengths[:, np.newaxis]
    expected = _face_normal(mesh)
    for li in range(len(unit)):
        assert np.allclose(unit[li], expected, atol=1e-4), (
            f"loop {li} was given {unit[li]} instead of the face normal {expected}"
        )

    # Case 2: a normal that is not on the singularity is kept exactly as asked,
    # so the repair cannot reshape shading nobody complained about.
    tilted = (0.6, 0.0, 0.8)
    mesh2 = _build("Repair_Untouched", [tilted] * 4)
    got2 = _loop_normals(mesh2)
    for li, n in enumerate(got2):
        assert np.allclose(n, tilted, atol=1e-4), (
            f"working normal rewritten on loop {li}: {n.tolist()} != {list(tilted)}"
        )

    print("=== MESH IO NORMAL REPAIR TEST PASSED ===")


def test_mesh_io_normal_repair():
    import pytest
    pytest.importorskip("bpy", reason="requires Blender background mode")
    _run()


if __name__ == "__main__":
    _run()
