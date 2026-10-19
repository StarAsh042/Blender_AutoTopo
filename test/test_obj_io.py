"""Standalone test for engines/obj_io.py: write -> read round-trip.

Runs under plain Python (needs numpy only) via pytest, and can also be
executed directly: ``python test/test_obj_io.py``.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402

import _pkgload  # noqa: E402

_obj_io = _pkgload.load_module("engines/obj_io.py")
write_obj, read_obj = _obj_io.write_obj, _obj_io.read_obj


def test_obj_io_roundtrip():
    here = os.path.dirname(os.path.abspath(__file__))

    # A cube: 8 verts, 6 quad faces, plus one triangle -> mixed arity.
    verts = np.array([
        [0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
        [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1],
    ], dtype=np.float64)
    quads = [
        (0, 1, 2, 3), (4, 7, 6, 5),
        (0, 4, 5, 1), (2, 6, 7, 3),
        (1, 5, 6, 2), (0, 3, 7, 4),
    ]
    tris = [(0, 1, 4)]

    path = os.path.join(here, "_test_roundtrip.obj")
    try:
        write_obj(path, verts, quads + tris)
        rv, rf = read_obj(path)

        assert rv.shape == (8, 3), f"vertex shape {rv.shape}"
        assert np.allclose(rv, verts), "vertex mismatch"
        assert len(rf) == 7, f"face count {len(rf)}"
        assert rf[:6] == [tuple(q) for q in quads], f"quads mismatch: {rf[:6]}"
        assert rf[6] == (0, 1, 4), f"tri mismatch: {rf[6]}"

        # Also test v/vt/vn style parsing and negative indices.
        with open(path, 'w') as f:
            f.write("v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\n")
            f.write("f 1//1 2//1 3//1 4//1\n")
            f.write("f -4 -3 -2\n")  # negative indices
        rv2, rf2 = read_obj(path)
        assert rf2[0] == (0, 1, 2, 3), f"v//vn parse failed: {rf2[0]}"
        assert rf2[1] == (0, 1, 2), f"negative index parse failed: {rf2[1]}"
    finally:
        if os.path.exists(path):
            os.remove(path)

    print("obj_io round-trip test PASSED")


if __name__ == "__main__":
    test_obj_io_roundtrip()
