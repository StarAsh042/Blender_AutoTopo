"""P0 regression test: engines/obj_io.write_obj must accept mixed
triangle/quad (inhomogeneous) face lists.

Bug (audit finding #2): ``write_obj`` called ``np.asarray(faces)`` on a
list of tuples with differing arity. On numpy >= 1.24 that raises
``ValueError: setting an array element with a sequence ... inhomogeneous
shape``, so the mixed tri/quad object-dtype fallback on the next line was
dead code and any mesh containing both triangles and quads crashed on
export (the QuadWild pipeline produces exactly such meshes).

These tests fail against the buggy implementation and pass once
``np.asarray(faces, dtype=object)`` is used.

Runs under plain Python (numpy only); also executable directly:
``python test/test_obj_io_mixed_faces.py``.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pytest  # noqa: E402

import _pkgload  # noqa: E402

_obj_io = _pkgload.load_module("engines/obj_io.py")
write_obj, read_obj = _obj_io.write_obj, _obj_io.read_obj

_HERE = os.path.dirname(os.path.abspath(__file__))


def _tmp(name):
    return os.path.join(_HERE, name)


def test_write_obj_mixed_tri_quad_does_not_raise():
    """The exact failing case: a list mixing 4-tuples and 3-tuples."""
    verts = np.array([
        [0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1],
    ], dtype=np.float64)
    faces = [(0, 1, 2, 3), (0, 1, 4), (1, 2, 4)]  # quad + 2 tris

    path = _tmp("_test_mixed_faces.obj")
    try:
        # Must not raise ValueError (numpy inhomogeneous-shape error).
        write_obj(path, verts, faces)
        rv, rf = read_obj(path)
    finally:
        if os.path.exists(path):
            os.remove(path)

    assert rv.shape == (5, 3), f"vertex shape {rv.shape}"
    assert [tuple(f) for f in rf] == faces, f"face round-trip mismatch: {rf}"


def test_write_obj_mixed_ngon_and_quad():
    """n-gons mixed with quads must also survive (no ragged crash)."""
    verts = np.zeros((6, 3), dtype=np.float64)
    faces = [(0, 1, 2, 3), (0, 1, 2, 3, 4, 5)]  # quad + hexagon

    path = _tmp("_test_mixed_ngon.obj")
    try:
        write_obj(path, verts, faces)
        _, rf = read_obj(path)
    finally:
        if os.path.exists(path):
            os.remove(path)

    assert [tuple(f) for f in rf] == faces, f"n-gon round-trip mismatch: {rf}"


def test_write_obj_uniform_quad_array_still_works():
    """Guard: the uniform (M, 4) ndarray fast path must keep working."""
    verts = np.array([
        [0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
    ], dtype=np.float64)
    quads = np.array([[0, 1, 2, 3]], dtype=np.int64)

    path = _tmp("_test_uniform_quads.obj")
    try:
        write_obj(path, verts, quads)
        _, rf = read_obj(path)
    finally:
        if os.path.exists(path):
            os.remove(path)

    assert [tuple(f) for f in rf] == [(0, 1, 2, 3)], f"quads mismatch: {rf}"


def test_write_obj_empty_faces():
    """Empty face list must write only vertices, without error."""
    verts = np.array([[0, 0, 0], [1, 1, 1]], dtype=np.float64)
    path = _tmp("_test_empty_faces.obj")
    try:
        write_obj(path, verts, [])
        rv, rf = read_obj(path)
    finally:
        if os.path.exists(path):
            os.remove(path)

    assert rv.shape == (2, 3), f"vertex shape {rv.shape}"
    assert rf == [], f"expected no faces, got {rf}"


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            print(f"--- {_name} ---")
            _fn()
    print("=== OBJ_IO MIXED-FACE REGRESSION TESTS PASSED ===")
